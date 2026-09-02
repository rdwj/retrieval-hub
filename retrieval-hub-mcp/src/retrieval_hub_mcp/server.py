"""RetrievalHub MCP server — catalog browsing and retrieval over MCP.

Exposes five read-only tools:

* ``list_sources``    — browse the catalog of queryable sources
* ``describe_source`` — full metadata for one source (prompts, counts)
* ``retrieve``        — semantic search against a source's physical index
* ``refine``          — expand context around a previously retrieved chunk
* ``request_access``  — guidance for requesting access to a restricted source
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
from retrieval_hub.model_registry import ModelUnavailableError
from retrieval_hub.models import PhysicalIndex, RecipeVersion, SamplePrompt, Source
from retrieval_hub.models.enums import SourceStatus
from retrieval_hub.models.identity import Identity
from retrieval_hub.policy.access import can_access
from retrieval_hub.retrieval.api import (
    SourceNotFoundError,
    SourceNotQueryableError,
    UnsupportedFamilyError,
    resolve_chunk_id,
    rrf_merge,
)
from retrieval_hub.retrieval.api import (
    multi_query as retrieval_multi_query,
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
from retrieval_hub_mcp.auth import get_current_identity
from retrieval_hub_mcp.schemas import (
    ChunkConfig,
    DataFreshness,
    EvalBaseline,
    RefineHit,
    RefineResponse,
    RetrievalHit,
    RetrievalResponse,
    RewrittenQueryInfo,
    SourceDetail,
    SourceHealth,
    SourceRetrievalMetadata,
    SourceSummary,
    UsageRules,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP application (with optional auth)
# ---------------------------------------------------------------------------

_auth_jwks_uri = os.environ.get("RETRIEVAL_HUB_AUTH_JWKS_URI")
_auth_issuer = os.environ.get("RETRIEVAL_HUB_AUTH_ISSUER", "retrieval-hub-auth")
_auth_audience = os.environ.get("RETRIEVAL_HUB_AUTH_AUDIENCE", "retrieval-hub")

_google_client_id = os.environ.get("RETRIEVAL_HUB_GOOGLE_CLIENT_ID")
_google_client_secret = os.environ.get("RETRIEVAL_HUB_GOOGLE_CLIENT_SECRET")
_google_base_url = os.environ.get("RETRIEVAL_HUB_GOOGLE_BASE_URL")

_auth_provider = None

_jwt_verifier = None
if _auth_jwks_uri:
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    _jwt_verifier = JWTVerifier(
        jwks_uri=_auth_jwks_uri,
        issuer=_auth_issuer,
        audience=_auth_audience,
    )

_google_provider = None
if _google_client_id and _google_client_secret and _google_base_url:
    from fastmcp.server.auth.providers.google import GoogleProvider

    _google_provider = GoogleProvider(
        client_id=_google_client_id,
        client_secret=_google_client_secret,
        base_url=_google_base_url,
        required_scopes=["openid", "email", "profile"],
    )

if _google_provider and _jwt_verifier:
    from fastmcp.server.auth import MultiAuth

    _auth_provider = MultiAuth(
        server=_google_provider,
        verifiers=[_jwt_verifier],
    )
elif _google_provider:
    _auth_provider = _google_provider
elif _jwt_verifier:
    _auth_provider = _jwt_verifier

mcp = FastMCP(
    "RetrievalHub",
    auth=_auth_provider,
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
# Health endpoint
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Verify DB connectivity and model registry state."""
    from sqlalchemy import text
    from starlette.responses import JSONResponse

    from retrieval_hub.models.model_endpoint import ModelEndpoint

    checks = {}
    try:
        session = get_catalog_session()
        try:
            session.execute(text("SELECT 1"))
            checks["database"] = "ok"

            count = session.query(ModelEndpoint).count()
            checks["model_registry"] = f"{count} endpoint(s)"
            if count == 0:
                checks["model_registry"] = "empty"
        finally:
            session.close()
    except Exception as exc:
        checks["database"] = str(exc)
        return JSONResponse({"status": "unhealthy", "checks": checks}, status_code=503)

    status = "ok" if checks.get("model_registry") != "empty" else "degraded"
    return JSONResponse({"status": status, "checks": checks})


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


def _resolve_embedding_model(source_obj, session: Session) -> str | None:
    """Read ``embedding.model`` from the source's active recipe content."""
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
        embedding = rv.content.get("embedding") or {}
        return embedding.get("model")
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
# Access control helpers
# ---------------------------------------------------------------------------


def _check_source_access(
    identity: Identity | None,
    source: Source | None,
    action: str,
) -> None:
    """Raise ``ToolError`` if the identity cannot perform ``action`` on ``source``.

    Round 1: access decisions are based on identity kind, groups, and source
    visibility only. Scope-based enforcement (e.g., requiring ``sources.query``
    to call retrieve) is deferred to a future iteration.

    When auth is disabled (identity is None) or the source is None (will be
    handled by downstream not-found logic), all access is allowed.
    """
    if identity is None or source is None:
        return
    if not can_access(identity, source, action):
        raise ToolError(
            f"Access denied: you do not have permission to {action} source "
            f"{source.slug!r}. Use the request_access tool for guidance on "
            f"how to obtain access."
        )


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
        identity = get_current_identity()
        sources = (
            session.query(Source)
            .filter(Source.status.in_([SourceStatus.CURATED, SourceStatus.PUBLISHED]))
            .all()
        )

        results: list[SourceSummary] = []
        for s in sources:
            if identity is not None and not can_access(identity, s, "list"):
                continue

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

    Returns catalog metadata including sample prompts, document/chunk
    counts, and ownership information.  Use the slug from ``list_sources``.
    """
    try:
        identity = get_current_identity()
        source = session.query(Source).filter(Source.slug == slug).one_or_none()
        if source is None:
            raise ToolError(
                f"No source with slug {slug!r}. Use list_sources to see available sources."
            )
        _check_source_access(identity, source, "read")

        doc_count = None
        chunk_count = None
        eval_baseline = None
        chunk_config_data = None
        if source.active_physical_index_id:
            pi = (
                session.query(PhysicalIndex)
                .filter(PhysicalIndex.id == source.active_physical_index_id)
                .one_or_none()
            )
            if pi:
                doc_count = pi.document_count
                if pi.build_metadata:
                    if "chunk_count" in pi.build_metadata:
                        chunk_count = pi.build_metadata["chunk_count"]
                    if "eval_baseline" in pi.build_metadata:
                        eval_baseline = EvalBaseline(**pi.build_metadata["eval_baseline"])
                    if "chunk_config" in pi.build_metadata:
                        chunk_config_data = ChunkConfig(**pi.build_metadata["chunk_config"])

        prompts = session.query(SamplePrompt).filter(SamplePrompt.source_id == source.id).all()
        sample_prompts = [
            {
                "applies_to_llm_family": sp.applies_to_llm_family,
                "role": str(sp.role),
                "text": sp.text,
            }
            for sp in prompts
        ] or None

        # Resolve embedding model health from the registry
        embedding_model = _resolve_embedding_model(source, session)
        health = None
        if embedding_model:
            from retrieval_hub.models.model_endpoint import ModelEndpoint

            me = (
                session.query(ModelEndpoint)
                .filter(ModelEndpoint.model_name == embedding_model)
                .one_or_none()
            )
            if me is not None:
                health = SourceHealth(
                    status=me.status,
                    embedding_model=embedding_model,
                    last_checked=me.last_probed.isoformat() if me.last_probed else None,
                )
            else:
                health = SourceHealth(
                    status="unknown",
                    embedding_model=embedding_model,
                )

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
            sample_prompts=sample_prompts,
            health=health,
            eval_baseline=eval_baseline,
            chunk_config=chunk_config_data,
        )
    finally:
        session.close()


def _parse_source_slugs(
    source: str,
    session: Session,
    identity: Identity | None = None,
) -> list[str]:
    """Parse the source parameter into a list of slugs.

    Supports:
    - Single slug: "va-cpg"
    - Comma-separated: "va-cpg,pubmed-hypertension"
    - Wildcard: "*" (all queryable sources the caller can access)
    """
    if source.strip() == "*":
        sources = (
            session.query(Source)
            .filter(Source.active_physical_index_id.isnot(None))
            .all()
        )
        if identity is not None:
            sources = [s for s in sources if can_access(identity, s, "query")]
        return [s.slug for s in sources]
    slugs = [s.strip() for s in source.split(",") if s.strip()]
    return slugs


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

    Each hit includes a cosine similarity ``score``.  Scores reflect the
    combination of embedding model, corpus, and query -- all three shape
    the scale, so scores from different sources are not directly
    comparable.  The ``embedding_model`` field on the response identifies
    which model produced these scores.

    The response includes usage_rules (citation requirements, scope
    disclaimers, handling constraints) and data_freshness metadata
    authored by the data owner.  These ride with every retrieval so the
    consuming agent always sees the obligations that come with this data.

    The ``source`` parameter accepts a single slug, comma-separated slugs
    (e.g., ``"va-cpg,pubmed-hypertension"``), or ``"*"`` to search all
    queryable sources.  Multi-source queries merge results using Reciprocal
    Rank Fusion (RRF) -- scores represent rank-based fusion, not raw cosine
    similarity.  Per-source metadata (embedding model, usage rules) is in
    ``per_source_metadata``.

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
        identity = get_current_identity()
        slugs = _parse_source_slugs(source, session, identity)

        # file_path only works with single-source
        if file_path is not None:
            if len(slugs) != 1:
                raise ToolError(
                    "file_path requires a single source slug, not multiple sources or '*'."
                )
            source_obj = session.query(Source).filter(Source.slug == slugs[0]).one_or_none()
            _check_source_access(identity, source_obj, "query")
            return await _retrieve_file(
                source_slug=slugs[0],
                source_obj=source_obj,
                file_path=file_path,
                ref=ref,
                session=session,
            )

        # Single-source: existing code path (unchanged behavior)
        if len(slugs) == 1:
            source_obj = session.query(Source).filter(Source.slug == slugs[0]).one_or_none()
            _check_source_access(identity, source_obj, "query")

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
                        source_slug=slugs[0],
                        query_text=qt,
                        session=session,
                        top_k=top_k,
                    )
                )

            deduped = _deduplicate_hits(all_results, top_k)

            request_id = deduped[0].request_id if deduped else ""

            hits = [
                RetrievalHit(
                    chunk_id=r.chunk_id,
                    text=r.text,
                    score=r.score,
                    doc_title=r.doc_title,
                    doc_url=r.doc_url,
                    doc_section=r.doc_section,
                    chunk_index=r.chunk_index,
                    source_slug=getattr(r, "source_slug", None) or None,
                )
                for r in deduped
            ]

            embedding_model = _resolve_embedding_model(source_obj, session)

            return _build_response(
                hits,
                source_obj,
                request_id=request_id,
                rewritten_queries=rewritten_queries_info,
                embedding_model=embedding_model,
            )

        # Multi-source: check access on each explicit slug
        if identity is not None:
            for slug_item in slugs:
                src = session.query(Source).filter(Source.slug == slug_item).one_or_none()
                if src is not None:
                    _check_source_access(identity, src, "query")

        per_source = retrieval_multi_query(
            source_slugs=slugs,
            query_text=query,
            session=session,
            top_k=top_k,
        )
        merged = rrf_merge(per_source, top_k=top_k)

        request_id = merged[0].request_id if merged else str(uuid.uuid4())

        hits = [
            RetrievalHit(
                chunk_id=r.chunk_id,
                text=r.text,
                score=r.score,
                doc_title=r.doc_title,
                doc_url=r.doc_url,
                doc_section=r.doc_section,
                chunk_index=r.chunk_index,
                source_slug=r.source_slug,
            )
            for r in merged
        ]

        # Build per-source metadata
        per_source_meta: dict[str, SourceRetrievalMetadata] = {}
        for slug in slugs:
            src = session.query(Source).filter(Source.slug == slug).one_or_none()
            if src is None:
                continue
            emb_model = _resolve_embedding_model(src, session)
            usage_rules, data_freshness = _extract_usage(src)
            per_source_meta[slug] = SourceRetrievalMetadata(
                embedding_model=emb_model,
                usage_rules=usage_rules,
                data_freshness=data_freshness,
            )

        return RetrievalResponse(
            request_id=request_id,
            hits=hits,
            per_source_metadata=per_source_meta if per_source_meta else None,
        )
    except ModelUnavailableError as exc:
        raise ToolError(
            f"Embedding model for source {source!r} is currently unavailable. "
            f"The model endpoint may be down. Details: {exc}"
        ) from exc
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
            chunk_id="",
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
    embedding_model: str | None = None,
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
        embedding_model=embedding_model,
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
    "graph": "graph_traverse_from_seed",
}


def _resolve_refine_strategy(
    source_obj: object | None,
    tool_strategy: str | None,
    tool_max_tokens: int | None,
    tool_window: int | None,
) -> tuple[str, int | None, int, float | None]:
    """Determine which refinement strategy, token budget, window, and min_score to use.

    Resolution order:
    1. If ``tool_strategy`` is provided, use it.  Look up its config in
       ``refinement_strategies`` for default window/max_tokens/min_score.
    2. Source's ``semantic_context.refinement_strategies`` (first enabled entry).
    3. Family default: ``section`` for document/clinical_document, ``adjacent``
       for code.
    4. Fall back to ``adjacent`` if nothing else matches.

    Tool-level ``max_context_tokens`` and ``window`` override source defaults.
    ``min_score`` is only configurable via source config (no tool-level override).
    """
    strategy = "adjacent"
    source_max_tokens: int | None = None
    source_window: int = 2
    source_min_score: float | None = None

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
                            source_min_score = rs.min_score
                            break
                else:
                    for rs in sc.refinement_strategies:
                        if rs.enabled:
                            strategy = rs.kind
                            source_max_tokens = rs.max_context_tokens
                            source_window = rs.window
                            source_min_score = rs.min_score
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
    effective_min_score = source_min_score
    return strategy, effective_max_tokens, effective_window, effective_min_score


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
    chunk_id: str | None = None,
    edge_types: list[str] | None = None,
    max_nodes: int | None = None,
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

    For the ``entity_arc`` strategy, ``origin_chunk_index`` is -1 and
    ``is_origin`` is false for all chunks because there is no single
    origin — the entire arc is the result.

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
            comorbidity guidelines).  ``entity_arc`` traces all mentions
            of an entity across a single document in structural order;
            ``query`` carries the entity name and ``chunk_index`` is
            ignored.  When omitted, the source's configured default
            strategy is used.
        chunk_id: Stable UUID identifier from a prior ``retrieve`` or
            ``refine`` result.  When provided, ``doc_title`` and
            ``chunk_index`` are resolved automatically from the chunk's
            metadata — you can pass empty/zero values for those fields.
        edge_types: Restrict graph traversal to only follow edges of these
            relationship types.  Only applicable to the
            ``graph_traverse_from_seed`` strategy.  Accepts either
            human-readable form (``"Compound - treats - Disease"``) or
            Memgraph's sanitized form (``"Compound___treats___Disease"``).
        max_nodes: Cap the number of neighbor nodes returned by graph
            traversal.  Only applicable to the
            ``graph_traverse_from_seed`` strategy.
    """
    try:
        identity = get_current_identity()

        if chunk_id is not None:
            try:
                doc_title, chunk_index = resolve_chunk_id(
                    source, chunk_id, session=session,
                )
            except LookupError as exc:
                raise ToolError(
                    f"chunk_id {chunk_id!r} not found in source {source!r}. "
                    f"Verify the chunk_id was copied from a previous retrieve or refine result."
                ) from exc

        source_obj = session.query(Source).filter(Source.slug == source).one_or_none()
        _check_source_access(identity, source_obj, "query")

        effective_strategy, effective_max_tokens, effective_window, effective_min_score = _resolve_refine_strategy(
            source_obj, strategy, max_context_tokens, window,
        )

        refine_kwargs: dict = dict(
            source_slug=source,
            doc_title=doc_title,
            chunk_index=chunk_index,
            query_text=query,
            window=effective_window,
            session=session,
            strategy=effective_strategy,
            max_context_tokens=effective_max_tokens,
        )
        if effective_min_score is not None:
            refine_kwargs["min_score"] = effective_min_score
        if edge_types is not None:
            refine_kwargs["edge_types"] = edge_types
        if max_nodes is not None:
            refine_kwargs["max_nodes"] = max_nodes

        output = retrieval_refine(**refine_kwargs)

        if not output.results:
            raise ToolError(
                f"No chunks found for doc_title={doc_title!r} at chunk_index={chunk_index} "
                f"in source {source!r}. Verify that doc_title and chunk_index were copied "
                f"exactly from a previous retrieve result."
            )

        doc_url = output.results[0].doc_url

        is_entity_arc = effective_strategy == "entity_arc"
        is_cross_ref = effective_strategy == "cross_reference"

        chunks = [
            RefineHit(
                chunk_id=r.chunk_id,
                text=r.text,
                doc_section=r.doc_section,
                chunk_index=r.chunk_index,
                is_origin=(
                    False if is_entity_arc
                    else (r.chunk_index == chunk_index and r.doc_title == doc_title)
                ),
                doc_title=r.doc_title if is_cross_ref else None,
                doc_url=r.doc_url if is_cross_ref else None,
            )
            for r in output.results
        ]

        usage_rules, data_freshness = _extract_usage(source_obj)
        embedding_model = _resolve_embedding_model(source_obj, session)

        return RefineResponse(
            source=source,
            doc_title=doc_title,
            doc_url=doc_url,
            origin_chunk_index=-1 if is_entity_arc else chunk_index,
            strategy=effective_strategy,
            chunks=chunks,
            truncated=output.truncated,
            total_section_chunks=output.total_chunks,
            context=output.context,
            embedding_model=embedding_model,
            usage_rules=usage_rules,
            data_freshness=data_freshness,
        )
    except ModelUnavailableError as exc:
        raise ToolError(
            f"Embedding model for source {source!r} is currently unavailable. "
            f"The model endpoint may be down. Details: {exc}"
        ) from exc
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


# ---------------------------------------------------------------------------
# request_access
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"catalog"},
)
async def request_access(
    slug: str,
    session: Session = Depends(get_catalog_session),
) -> dict:
    """Explain how to request access to a restricted source.

    Returns structured guidance including the source's visibility policy,
    required groups, owner team, and contact information. For public
    sources, confirms that no special access is needed.
    """
    try:
        source = session.query(Source).filter(Source.slug == slug).one_or_none()
        if source is None:
            raise ToolError(
                f"No source with slug {slug!r}. Use list_sources to see available sources."
            )

        access = source.access or {}
        visibility = access.get("visibility", "public")
        allowed_groups = access.get("allowed_groups", [])
        allowed_emails = access.get("allowed_emails", [])
        owner_team = source.owner_team
        contacts: list[str] = []
        if hasattr(source, "owner_info") and source.owner_info:
            contacts = source.owner_info.get("contacts", [])

        if visibility == "public":
            return {
                "source": slug,
                "visibility": "public",
                "message": (
                    "This source is publicly accessible to all authenticated users. "
                    "No special access request is needed."
                ),
            }

        result = {
            "source": slug,
            "visibility": visibility,
            "required_groups": allowed_groups,
            "owner_team": owner_team,
            "contacts": contacts,
            "guidance": (
                "This source has restricted access. Contact the owner team "
                "to request membership in one of the required groups, or "
                "ask to have your email added to the allow-list."
            ),
        }
        if allowed_emails:
            result["allowed_emails"] = allowed_emails
        return result
    finally:
        session.close()
