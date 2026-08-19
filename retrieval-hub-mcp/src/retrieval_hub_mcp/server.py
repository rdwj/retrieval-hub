"""RetrievalHub MCP server — catalog browsing and retrieval over MCP.

Exposes three read-only tools:

* ``list_sources``   — browse the catalog of queryable sources
* ``describe_source`` — full metadata for one source (recipe, prompts, counts)
* ``retrieve``       — semantic search against a source's physical index
"""

from __future__ import annotations

import base64
import logging
import uuid

import httpx
from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from sqlalchemy.orm import Session

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.models import PhysicalIndex, RecipeVersion, SamplePrompt, Source
from retrieval_hub.models.enums import SourceStatus
from retrieval_hub.retrieval.api import (
    SourceNotFoundError,
    SourceNotQueryableError,
    UnsupportedFamilyError,
)
from retrieval_hub.retrieval.api import (
    query as retrieval_query,
)
from retrieval_hub_mcp.schemas import (
    DataFreshness,
    RetrievalHit,
    RetrievalResponse,
    SourceDetail,
    SourceSummary,
    UsageRules,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP application
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "RetrievalHub",
    cache_ttl=3600,
    cache_scope="public",
)

# ---------------------------------------------------------------------------
# Database dependency (lazy singletons)
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(_get_engine())
    return _session_factory


def get_catalog_session() -> Session:
    """Return a SQLAlchemy session for a single tool invocation.

    FastMCP 4 beta does not resolve generator-based Depends, so we
    return a session directly.  The session is closed by the tool
    function after use (via a try/finally in each tool).
    """
    factory = _get_session_factory()
    return factory()


# ---------------------------------------------------------------------------
# GitHub file fetch
# ---------------------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"


async def _fetch_github_file(
    owner_repo: str, file_path: str, ref: str | None = None,
) -> tuple[str, str]:
    """Fetch a file from GitHub's public REST API.

    Returns ``(content, download_url)``.  Raises ``ToolError`` on failure.
    Logs remaining rate-limit quota from response headers.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner_repo}/contents/{file_path}"
    params: dict[str, str] = {}
    if ref:
        params["ref"] = ref

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url, params=params, headers={"Accept": "application/vnd.github.v3+json"},
        )

    remaining = resp.headers.get("x-ratelimit-remaining")
    limit = resp.headers.get("x-ratelimit-limit")
    if remaining is not None:
        logger.info("github.rate_limit remaining=%s limit=%s", remaining, limit)

    if resp.status_code == 404:
        raise ToolError(
            f"File {file_path!r} not found in {owner_repo}"
            + (f" at ref {ref!r}" if ref else "")
        )
    if resp.status_code == 403:
        raise ToolError(
            f"GitHub API rate limit exceeded (remaining={remaining}). "
            "Try again later or use a PAT."
        )
    if resp.status_code != 200:
        raise ToolError(
            f"GitHub API returned {resp.status_code} for {owner_repo}/{file_path}"
        )

    data = resp.json()
    if data.get("type") != "file":
        raise ToolError(f"{file_path!r} is a {data.get('type', 'unknown')}, not a file")

    content = base64.b64decode(data["content"]).decode("utf-8")
    download_url = data.get("html_url", data.get("download_url", ""))
    return content, download_url


def _resolve_github_repo(source_obj, session: Session) -> str | None:
    """Read ``github_repo`` from the source's active recipe content.

    Resolves the recipe through the active physical index, since
    ``Source.recipe_version_id`` may not be set directly.
    """
    if not source_obj or not source_obj.active_physical_index_id:
        return None
    pi = (
        session.query(PhysicalIndex)
        .filter(PhysicalIndex.id == source_obj.active_physical_index_id)
        .one_or_none()
    )
    if not pi or not pi.recipe_version_id:
        return None
    rv = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.id == pi.recipe_version_id)
        .one_or_none()
    )
    if rv and rv.content:
        return rv.content.get("github_repo")
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"catalog"},
)
async def list_sources(
    session: Session = Depends(get_catalog_session),
) -> list[SourceSummary]:
    """List all queryable data sources in the RetrievalHub catalog.

    Returns sources in the CURATED or PUBLISHED lifecycle states.
    Each entry includes the slug (use with ``retrieve``), display name,
    source family, lifecycle status, and document count.
    """
    try:
        sources = (
            session.query(Source)
            .filter(Source.status.in_([SourceStatus.CURATED, SourceStatus.PUBLISHED]))
            .all()
        )

        results: list[SourceSummary] = []
        for s in sources:
            doc_count = None
            if s.active_physical_index_id:
                pi = (
                    session.query(PhysicalIndex)
                    .filter(PhysicalIndex.id == s.active_physical_index_id)
                    .one_or_none()
                )
                if pi:
                    doc_count = pi.document_count

            results.append(
                SourceSummary(
                    slug=s.slug,
                    name=s.name,
                    family=s.family,
                    status=s.status,
                    description_short=s.description_short,
                    document_count=doc_count,
                )
            )
        return results
    finally:
        session.close()


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"catalog"},
)
async def describe_source(
    slug: str,
    session: Session = Depends(get_catalog_session),
) -> SourceDetail:
    """Get detailed metadata for a specific data source.

    Returns full catalog metadata including the recipe configuration,
    sample prompts, document/chunk counts, and ownership information.
    Use the slug from ``list_sources``.
    """
    try:
        source = session.query(Source).filter(Source.slug == slug).one_or_none()
        if source is None:
            raise ToolError(f"No source with slug {slug!r}")

        doc_count = None
        chunk_count = None
        if source.active_physical_index_id:
            pi = (
                session.query(PhysicalIndex)
                .filter(PhysicalIndex.id == source.active_physical_index_id)
                .one_or_none()
            )
            if pi:
                doc_count = pi.document_count
                if pi.build_metadata and "chunk_count" in pi.build_metadata:
                    chunk_count = pi.build_metadata["chunk_count"]

        recipe_content = None
        if source.recipe_version_id:
            rv = (
                session.query(RecipeVersion)
                .filter(RecipeVersion.id == source.recipe_version_id)
                .one_or_none()
            )
            if rv:
                recipe_content = rv.content

        prompts = (
            session.query(SamplePrompt)
            .filter(SamplePrompt.source_id == source.id)
            .all()
        )
        sample_prompts = [
            {
                "applies_to_llm_family": sp.applies_to_llm_family,
                "role": str(sp.role),
                "text": sp.text,
            }
            for sp in prompts
        ] or None

        return SourceDetail(
            slug=source.slug,
            name=source.name,
            family=source.family,
            status=source.status,
            description_short=source.description_short,
            description_long=source.description_long,
            owner_team=source.owner_team,
            document_count=doc_count,
            chunk_count=chunk_count,
            recipe_content=recipe_content,
            sample_prompts=sample_prompts,
        )
    finally:
        session.close()


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"retrieval"},
    timeout=30.0,
)
async def retrieve(
    query: str,
    source: str,
    top_k: int = 5,
    file_path: str | None = None,
    ref: str | None = None,
    session: Session = Depends(get_catalog_session),
) -> RetrievalResponse:
    """Search a data source and return relevant passages with provenance metadata.

    The response includes usage_rules (citation requirements, scope
    disclaimers, handling constraints) and data_freshness metadata
    authored by the data owner.  These ride with every retrieval so the
    consuming agent always sees the obligations that come with this data.

    Parameters:
        query: Natural-language search query.
        source: Source slug (from ``list_sources``).
        top_k: Number of results to return (default 5, max varies by source).
        file_path: Fetch a specific file from the source's GitHub repository
            instead of running vector search.  Requires the source recipe to
            include a ``github_repo`` field.
        ref: Git ref (branch, tag, or SHA) for the file fetch.  Only used
            when ``file_path`` is provided.  Defaults to the repo's default
            branch.
    """
    try:
        source_obj = session.query(Source).filter(Source.slug == source).one_or_none()

        if file_path is not None:
            return await _retrieve_file(
                source_slug=source,
                source_obj=source_obj,
                file_path=file_path,
                ref=ref,
                session=session,
            )

        results = retrieval_query(
            source_slug=source,
            query_text=query,
            session=session,
            top_k=top_k,
        )

        hits = [
            RetrievalHit(
                text=r.text,
                score=r.score,
                doc_title=r.doc_title,
                doc_url=r.doc_url,
                doc_section=r.doc_section,
                physical_index_id=r.physical_index_id,
                recipe_version=r.recipe_version,
                request_id=r.request_id,
            )
            for r in results
        ]

        return _build_response(hits, source_obj)
    except SourceNotFoundError as exc:
        raise ToolError(
            f"Source {source!r} not found. Use list_sources to see available sources."
        ) from exc
    except SourceNotQueryableError as exc:
        raise ToolError(
            f"Source {source!r} exists but has no active index. "
            f"It may still be ingesting data."
        ) from exc
    except UnsupportedFamilyError as exc:
        raise ToolError(
            f"Source {source!r} uses a family that is not yet supported for retrieval."
        ) from exc
    finally:
        session.close()


async def _retrieve_file(
    source_slug: str,
    source_obj,
    file_path: str,
    ref: str | None,
    session: Session,
) -> RetrievalResponse:
    """Handle the file_path code path: fetch a file from GitHub."""
    if source_obj is None:
        raise ToolError(
            f"Source {source_slug!r} not found. "
            "Use list_sources to see available sources."
        )

    github_repo = _resolve_github_repo(source_obj, session)
    if not github_repo:
        raise ToolError(
            f"Source {source_slug!r} does not have a github_repo in its recipe. "
            "File fetch requires a code source with a GitHub repository configured."
        )

    content, html_url = await _fetch_github_file(github_repo, file_path, ref)
    request_id = str(uuid.uuid4())

    hits = [
        RetrievalHit(
            text=content,
            score=1.0,
            doc_title=file_path,
            doc_url=html_url,
            doc_section=None,
            physical_index_id="github-live",
            recipe_version=0,
            request_id=request_id,
        ),
    ]
    return _build_response(hits, source_obj)


def _build_response(
    hits: list[RetrievalHit], source_obj,
) -> RetrievalResponse:
    """Assemble a RetrievalResponse with usage_rules and data_freshness."""
    usage_rules = None
    data_freshness = None
    if source_obj and source_obj.usage_rules:
        rules = source_obj.usage_rules
        usage_rules = UsageRules(
            citation=rules.get("citation"),
            scope_disclaimer=rules.get("scope_disclaimer"),
            handling=rules.get("handling"),
            custom_rules=rules.get("custom_rules"),
        )
        freshness_data = rules.get("data_freshness", {})
        if freshness_data:
            data_freshness = DataFreshness(
                source_name=freshness_data.get("source_name", source_obj.name),
                source_url=freshness_data.get("source_url"),
                last_refreshed=freshness_data.get("last_refreshed"),
                refresh_cadence=freshness_data.get("refresh_cadence"),
                staleness_note=freshness_data.get("staleness_note"),
            )

    return RetrievalResponse(
        hits=hits,
        usage_rules=usage_rules,
        data_freshness=data_freshness,
    )
