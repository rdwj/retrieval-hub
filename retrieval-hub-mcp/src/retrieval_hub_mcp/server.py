"""RetrievalHub MCP server — catalog browsing and retrieval over MCP.

Exposes three read-only tools:

* ``list_sources``   — browse the catalog of queryable sources
* ``describe_source`` — full metadata for one source (recipe, prompts, counts)
* ``retrieve``       — semantic search against a source's physical index
"""

from __future__ import annotations

import logging

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
    """
    try:
        source_obj = session.query(Source).filter(Source.slug == source).one_or_none()

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
        if source_obj and source_obj.usage_rules:
            freshness_data = source_obj.usage_rules.get("data_freshness", {})
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
