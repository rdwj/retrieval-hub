"""RetrievalHub MCP server — catalog browsing and retrieval over MCP.

Exposes four read-only tools:

* ``list_sources``   — browse the catalog of queryable sources
* ``describe_source`` — full metadata for one source (recipe, prompts, counts)
* ``retrieve``       — semantic search against a source's physical index
* ``refine``         — expand context around a previously retrieved chunk
"""

from __future__ import annotations

import base64
import logging
import os
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
from retrieval_hub.retrieval.api import (
    refine as retrieval_refine,
)
from retrieval_hub.rewriter import LlmClient, RewriterService
from retrieval_hub.rewriter.schemas import RewriteResult
from retrieval_hub.schemas.rewriter import RewriterMetadata
from retrieval_hub_mcp.schemas import (
    DataFreshness,
    RefineHit,
    RefineResponse,
    RetrievalHit,
    RetrievalResponse,
    RewrittenQueryInfo,
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

_REWRITER_LLM_URL = os.environ.get(
    "RETRIEVAL_HUB_REWRITER_LLM_URL",
    "https://gpt-oss-120b-direct-gpt-oss-120b-model.apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1",
)
_REWRITER_LLM_MODEL = os.environ.get(
    "RETRIEVAL_HUB_REWRITER_LLM_MODEL",
    "/mnt/models",
)


async def _fetch_github_file(
    owner_repo: str,
    file_path: str,
    ref: str | None = None,
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
            url,
            params=params,
            headers={"Accept": "application/vnd.github.v3+json"},
        )

    remaining = resp.headers.get("x-ratelimit-remaining")
    limit = resp.headers.get("x-ratelimit-limit")
    if remaining is not None:
        logger.info("github.rate_limit remaining=%s limit=%s", remaining, limit)

    if resp.status_code == 404:
        raise ToolError(
            f"File {file_path!r} not found in {owner_repo}" + (f" at ref {ref!r}" if ref else "")
        )
    if resp.status_code == 403:
        raise ToolError(
            f"GitHub API rate limit exceeded (remaining={remaining}). Try again later or use a PAT."
        )
    if resp.status_code != 200:
        raise ToolError(f"GitHub API returned {resp.status_code} for {owner_repo}/{file_path}")

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
    rv = session.query(RecipeVersion).filter(RecipeVersion.id == pi.recipe_version_id).one_or_none()
    if rv and rv.content:
        return rv.content.get("github_repo")
    return None


# ---------------------------------------------------------------------------
# Query rewriter helpers
# ---------------------------------------------------------------------------


def _should_rewrite(source_obj: object | None) -> bool:
    """Return True if the source has rewriter metadata with enabled=True."""
    if source_obj is None:
        return False
    raw = getattr(source_obj, "rewriter_metadata", None)
    if not raw:
        return False
    try:
        metadata = RewriterMetadata.model_validate(raw)
        return metadata.enabled
    except Exception:
        logger.warning(
            "Invalid rewriter_metadata on source, skipping rewrite",
        )
        return False


async def _rewrite_query(
    query: str,
    source_obj: object,
) -> RewriteResult:
    """Rewrite a query using the source's rewriter metadata and the LLM."""
    raw = getattr(source_obj, "rewriter_metadata", None)
    metadata = RewriterMetadata.model_validate(raw)

    raw_sc = getattr(source_obj, "semantic_context", None)
    semantic = None
    if raw_sc:
        from retrieval_hub.schemas.semantic import SemanticContext

        semantic = SemanticContext.model_validate(raw_sc)

    async with LlmClient(
        _REWRITER_LLM_URL,
        model=_REWRITER_LLM_MODEL,
    ) as llm:
        service = RewriterService(llm)
        return await service.rewrite(query, metadata, semantic_context=semantic)


def _deduplicate_hits(
    results: list,
    top_k: int,
) -> list:
    """Deduplicate retrieval results by text, keeping the highest score."""
    seen: dict[str, object] = {}
    for r in results:
        text = r.text
        if text not in seen or r.score > seen[text].score:
            seen[text] = r
    ranked = sorted(seen.values(), key=lambda h: h.score, reverse=True)
    return ranked[:top_k]


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
            raise ToolError(
                f"No source with slug {slug!r}. Use list_sources to see available sources."
            )

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

        prompts = session.query(SamplePrompt).filter(SamplePrompt.source_id == source.id).all()
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
    timeout=60.0,
)
async def retrieve(
    query: str,
    source: str,
    top_k: int = 5,
    file_path: str | None = None,
    ref: str | None = None,
    no_rewrite: bool = False,
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
        no_rewrite: Skip automatic query rewriting even if the source has
            rewriter metadata enabled.  Useful for comparing raw vs rewritten
            retrieval quality.
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

        rewritten_queries_info = None
        query_texts = [query]

        if not no_rewrite and _should_rewrite(source_obj):
            try:
                rewrite_result = await _rewrite_query(query, source_obj)
                rewritten_queries_info = [
                    RewrittenQueryInfo(
                        text=q.text,
                        intent=q.intent,
                        confidence=q.confidence,
                    )
                    for q in rewrite_result.queries
                ]
                query_texts.extend(q.text for q in rewrite_result.queries)
            except Exception:
                logger.warning(
                    "Rewriter failed for source=%s, falling back to raw query",
                    source,
                    exc_info=True,
                )

        all_results = []
        for qt in query_texts:
            all_results.extend(
                retrieval_query(
                    source_slug=source,
                    query_text=qt,
                    session=session,
                    top_k=top_k,
                )
            )

        deduped = _deduplicate_hits(all_results, top_k)

        request_id = deduped[0].request_id if deduped else ""

        hits = [
            RetrievalHit(
                text=r.text,
                score=r.score,
                doc_title=r.doc_title,
                doc_url=r.doc_url,
                doc_section=r.doc_section,
                chunk_index=r.chunk_index,
            )
            for r in deduped
        ]

        return _build_response(
            hits,
            source_obj,
            request_id=request_id,
            rewritten_queries=rewritten_queries_info,
        )
    except SourceNotFoundError as exc:
        raise ToolError(
            f"Source {source!r} not found. Use list_sources to see available sources."
        ) from exc
    except SourceNotQueryableError as exc:
        raise ToolError(
            f"Source {source!r} exists but has no active index. It may still be ingesting data."
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
            f"Source {source_slug!r} not found. Use list_sources to see available sources."
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
        ),
    ]
    return _build_response(hits, source_obj, request_id=request_id)


def _build_response(
    hits: list[RetrievalHit],
    source_obj,
    *,
    request_id: str = "",
    rewritten_queries: list[RewrittenQueryInfo] | None = None,
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
        request_id=request_id,
        hits=hits,
        usage_rules=usage_rules,
        data_freshness=data_freshness,
        rewritten_queries=rewritten_queries,
    )


def _extract_usage(source_obj) -> tuple[UsageRules | None, DataFreshness | None]:
    """Pull usage_rules and data_freshness from a source object."""
    if not source_obj or not source_obj.usage_rules:
        return None, None
    rules = source_obj.usage_rules
    usage_rules = UsageRules(
        citation=rules.get("citation"),
        scope_disclaimer=rules.get("scope_disclaimer"),
        handling=rules.get("handling"),
        custom_rules=rules.get("custom_rules"),
    )
    freshness_data = rules.get("data_freshness", {})
    data_freshness = None
    if freshness_data:
        data_freshness = DataFreshness(
            source_name=freshness_data.get("source_name", source_obj.name),
            source_url=freshness_data.get("source_url"),
            last_refreshed=freshness_data.get("last_refreshed"),
            refresh_cadence=freshness_data.get("refresh_cadence"),
            staleness_note=freshness_data.get("staleness_note"),
        )
    return usage_rules, data_freshness


# ---------------------------------------------------------------------------
# refine
# ---------------------------------------------------------------------------

_FAMILY_DEFAULT_STRATEGY: dict[str, str] = {
    "document": "section",
    "clinical_document": "section",
    "code": "adjacent",
}


def _resolve_refine_strategy(
    source_obj: object | None,
    tool_strategy: str | None,
    tool_max_tokens: int | None,
    tool_window: int | None,
) -> tuple[str, int | None, int]:
    """Determine which refinement strategy, token budget, and window to use.

    Resolution order:
    1. If ``tool_strategy`` is provided, use it.  Look up its config in
       ``refinement_strategies`` for default window/max_tokens.
    2. Source's ``semantic_context.refinement_strategies`` (first enabled entry).
    3. Family default: ``section`` for document/clinical_document, ``adjacent``
       for code.
    4. Fall back to ``adjacent`` if nothing else matches.

    Tool-level ``max_context_tokens`` and ``window`` override source defaults.
    """
    strategy = "adjacent"
    source_max_tokens: int | None = None
    source_window: int = 2

    if source_obj is not None:
        family = getattr(source_obj, "family", None)
        if family:
            strategy = _FAMILY_DEFAULT_STRATEGY.get(str(family), "adjacent")

        raw_sc = getattr(source_obj, "semantic_context", None)
        if raw_sc:
            try:
                from retrieval_hub.schemas.semantic import SemanticContext

                sc = SemanticContext.model_validate(raw_sc)

                if tool_strategy is not None:
                    strategy = tool_strategy
                    for rs in sc.refinement_strategies:
                        if rs.kind == tool_strategy and rs.enabled:
                            source_max_tokens = rs.max_context_tokens
                            source_window = rs.window
                            break
                else:
                    for rs in sc.refinement_strategies:
                        if rs.enabled:
                            strategy = rs.kind
                            source_max_tokens = rs.max_context_tokens
                            source_window = rs.window
                            break
            except Exception:
                logger.warning(
                    "Failed to parse semantic_context for strategy resolution",
                    exc_info=True,
                )

        if tool_strategy is not None and not raw_sc:
            strategy = tool_strategy

    elif tool_strategy is not None:
        strategy = tool_strategy

    effective_max_tokens = tool_max_tokens if tool_max_tokens is not None else source_max_tokens
    effective_window = tool_window if tool_window is not None else source_window
    return strategy, effective_max_tokens, effective_window


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"retrieval"},
    timeout=30.0,
)
async def refine(
    source: str,
    doc_title: str,
    chunk_index: int,
    query: str,
    window: int | None = None,
    max_context_tokens: int | None = None,
    strategy: str | None = None,
    session: Session = Depends(get_catalog_session),
) -> RefineResponse:
    """Expand context around a previously retrieved chunk.

    Given a reference to a specific chunk (identified by ``source``,
    ``doc_title``, and ``chunk_index`` from a prior ``retrieve`` result),
    return the surrounding chunks from the same document.  Use this when
    a retrieve hit looks like part of a larger process, procedure, or
    section and you need to see what comes before and after it to
    determine whether you have the complete picture.

    The ``doc_title`` and ``chunk_index`` values must be copied exactly
    from a previous ``retrieve`` result — do not paraphrase or modify
    the ``doc_title``.

    The response contains chunks ordered by document position. Each
    chunk's ``doc_section`` field tells you which section it belongs to,
    so you can see if the context spans section boundaries.  The chunk
    where ``is_origin`` is true is the one you originally retrieved.

    When ``truncated`` is true in the response, the section was larger
    than the token budget and only a window around the origin chunk is
    included.  ``total_section_chunks`` tells you how large the full
    section is.

    Parameters:
        source: Source slug (from ``list_sources``).
        doc_title: Document title copied exactly from the ``retrieve`` hit.
        chunk_index: Chunk index from the ``retrieve`` hit.
        query: Describes what additional context you are looking for.
            Used by the ``cross_reference`` strategy to find
            semantically relevant chunks in related documents.
            For other strategies, logged for observability.
        window: How many chunks before and after to include.  Used by
            the ``adjacent`` strategy; for ``cross_reference``, controls
            how many cross-document hits to return.  Defaults to the
            source's configured window or 2 if unconfigured.
        max_context_tokens: Maximum number of tokens to return.  When
            the expanded context exceeds this budget, chunks are trimmed
            from the edges toward the origin chunk.  Omit for no limit.
        strategy: Refinement strategy to use.  ``section`` returns the
            full document section containing the chunk.  ``adjacent``
            returns chunks positionally near the origin.
            ``cross_reference`` follows entity relationships to find
            relevant content in related documents (e.g., PTSD to SUD
            comorbidity guidelines).  When omitted, the source's
            configured default strategy is used.
    """
    try:
        source_obj = session.query(Source).filter(Source.slug == source).one_or_none()

        effective_strategy, effective_max_tokens, effective_window = _resolve_refine_strategy(
            source_obj, strategy, max_context_tokens, window,
        )

        output = retrieval_refine(
            source_slug=source,
            doc_title=doc_title,
            chunk_index=chunk_index,
            query_text=query,
            window=effective_window,
            session=session,
            strategy=effective_strategy,
            max_context_tokens=effective_max_tokens,
        )

        if not output.results:
            raise ToolError(
                f"No chunks found for doc_title={doc_title!r} at chunk_index={chunk_index} "
                f"in source {source!r}. Verify that doc_title and chunk_index were copied "
                f"exactly from a previous retrieve result."
            )

        doc_url = output.results[0].doc_url

        is_cross_ref = effective_strategy == "cross_reference"

        chunks = [
            RefineHit(
                text=r.text,
                doc_section=r.doc_section,
                chunk_index=r.chunk_index,
                is_origin=(r.chunk_index == chunk_index and r.doc_title == doc_title),
                doc_title=r.doc_title if is_cross_ref else None,
                doc_url=r.doc_url if is_cross_ref else None,
            )
            for r in output.results
        ]

        usage_rules, data_freshness = _extract_usage(source_obj)

        return RefineResponse(
            source=source,
            doc_title=doc_title,
            doc_url=doc_url,
            origin_chunk_index=chunk_index,
            strategy=effective_strategy,
            chunks=chunks,
            truncated=output.truncated,
            total_section_chunks=output.total_chunks,
            usage_rules=usage_rules,
            data_freshness=data_freshness,
        )
    except SourceNotFoundError as exc:
        raise ToolError(
            f"Source {source!r} not found. Use list_sources to see available sources."
        ) from exc
    except SourceNotQueryableError as exc:
        raise ToolError(
            f"Source {source!r} exists but has no active index. It may still be ingesting data."
        ) from exc
    except UnsupportedFamilyError as exc:
        raise ToolError(
            f"Source {source!r} uses a family that is not yet supported for refinement."
        ) from exc
    finally:
        session.close()
