"""High-level retrieval entry point and normalized result shape.

``RetrievalResult`` is the normalized per-hit shape every adapter must return.
It carries the minimum information the MCP layer (future step 5) needs to
render a hit plus the lineage handle (``physical_index_id``, ``recipe_version``,
``request_id``) per ``docs/catalog.md`` and ``docs/mcp-server.md``.

``query`` is the one-shot entry point the hand-run query script uses. It
mirrors what a future MCP tool would do: look up the source by slug, resolve
its active physical index, build an adapter of the correct family, and run
the retrieve call.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from retrieval_hub.adapters.base import SourceAdapter
from retrieval_hub.adapters.document import DocumentAdapter
from retrieval_hub.adapters.process import ProcessAdapter
from retrieval_hub.model_registry import (
    ModelEndpoint,
    ModelNotFoundError,
    ModelUnavailableError,
    resolve_model,
)
from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    """Normalized per-hit result returned by every adapter.

    ``physical_index_id``, ``recipe_version`` and ``request_id`` form the
    lineage handle callers need to answer "where did this result come from?"
    without reading adapter internals.
    """

    chunk_id: str
    text: str
    score: float
    doc_title: str
    doc_url: str
    doc_section: str | None
    chunk_index: int | None
    physical_index_id: str
    recipe_version: int
    request_id: str
    source_slug: str = ""


@dataclass(frozen=True)
class RefineOutput:
    """Wrapper for refine results with truncation metadata."""

    results: list[RetrievalResult]
    truncated: bool = False
    total_chunks: int | None = None
    context: str | None = None


class SourceNotFoundError(LookupError):
    """Raised when ``query`` cannot find a source by slug."""


class SourceNotQueryableError(RuntimeError):
    """Raised when the source exists but has no active physical index."""


class UnsupportedFamilyError(RuntimeError):
    """Raised when no adapter exists for the source's family yet."""


def _resolve_embedding_endpoint(
    session: Session, recipe_version: RecipeVersion
) -> str | None:
    """Resolve the embedding endpoint via the model registry.

    Falls back to the recipe's ``embedding.endpoint`` field when the model
    is not registered, so existing deployments and local dev keep working.
    """
    content = recipe_version.content or {}
    embedding = content.get("embedding") or {}
    model_name = embedding.get("model")
    if not model_name:
        return None
    try:
        return resolve_model(session, model_name)
    except ModelUnavailableError:
        from sqlalchemy import select

        ep = session.execute(
            select(ModelEndpoint).where(ModelEndpoint.model_name == model_name)
        ).scalar_one_or_none()
        if ep and ep.endpoint_url:
            logger.warning(
                "Model %r is marked unhealthy; using endpoint anyway",
                model_name,
            )
            return ep.endpoint_url
        return None
    except ModelNotFoundError:
        recipe_endpoint = embedding.get("endpoint")
        if recipe_endpoint:
            logger.warning(
                "Model %r not in registry, falling back to recipe endpoint",
                model_name,
            )
        return recipe_endpoint


def _build_adapter(
    source: Source,
    physical_index: PhysicalIndex,
    recipe_version: RecipeVersion,
    *,
    vectors_db_url: str | None,
    embedding_endpoint: str | None = None,
) -> SourceAdapter:
    """Return the right adapter instance for the source's family."""
    if source.family == SourceFamily.GRAPH:
        from retrieval_hub.adapters.graph import GraphAdapter

        return GraphAdapter(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
            vectors_db_url=vectors_db_url,
            embedding_endpoint=embedding_endpoint,
        )
    if source.family == SourceFamily.TABULAR:
        from retrieval_hub.adapters.tabular import TabularAdapter

        return TabularAdapter(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
            vectors_db_url=vectors_db_url,
            embedding_endpoint=embedding_endpoint,
        )
    if source.family == SourceFamily.PROCESS:
        return ProcessAdapter(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
            vectors_db_url=vectors_db_url,
            embedding_endpoint=embedding_endpoint,
        )
    if source.family in (
        SourceFamily.DOCUMENT,
        SourceFamily.CLINICAL_DOCUMENT,
        SourceFamily.TECHNICAL_DOCUMENT,
        SourceFamily.CODE,
    ):
        return DocumentAdapter(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
            vectors_db_url=vectors_db_url,
            embedding_endpoint=embedding_endpoint,
        )
    raise UnsupportedFamilyError(
        f"No adapter implementation for family {source.family!r} yet. "
        f"Supported families: document, clinical_document, technical_document, "
        f"code, process, tabular, graph."
    )


def query(
    source_slug: str,
    query_text: str,
    *,
    session: Session,
    top_k: int = 10,
    vectors_db_url: str | None = None,
    request_id: str | None = None,
    doc_section: list[str] | None = None,
    scope_entity_id: str | None = None,
) -> list[RetrievalResult]:
    """Return top-k retrieval results for ``query_text`` against a source.

    Parameters
    ----------
    source_slug:
        The catalog slug of the source to query.
    query_text:
        The raw user query.
    session:
        A live SQLAlchemy session against the catalog database.
    top_k:
        How many hits to return. Defaults to 10.
    vectors_db_url:
        Optional override for the vectors-database connection URL. If absent,
        the document adapter will pull from the ``RETRIEVAL_HUB_VECTORS_DB_URL``
        environment variable.
    request_id:
        Optional caller-provided request id. One is generated if absent so
        every result carries a stable lineage handle.
    doc_section:
        Optional list of section names to restrict the search to. When
        provided, only chunks whose ``doc_section`` column matches one
        of the given values are returned. For graph sources this
        corresponds to entity types; for document sources it is section
        header text.
    scope_entity_id:
        Restrict retrieval to a specific subgraph by providing a seed
        entity ID.  The system traverses the graph from this entity to
        find all connected entities, then restricts the vector search
        to those entities.  Only works for graph-family sources.

    Raises
    ------
    SourceNotFoundError
        If no source exists with the given slug.
    SourceNotQueryableError
        If the source exists but has no active physical index.
    UnsupportedFamilyError
        If the source's family has no registered adapter.
    """
    source = session.query(Source).filter(Source.slug == source_slug).one_or_none()
    if source is None:
        raise SourceNotFoundError(f"No source with slug {source_slug!r}")

    if source.active_physical_index_id is None:
        raise SourceNotQueryableError(
            f"Source {source_slug!r} has no active physical index; "
            f"run ingestion before querying it."
        )

    physical_index = (
        session.query(PhysicalIndex)
        .filter(PhysicalIndex.id == source.active_physical_index_id)
        .one()
    )
    recipe_version = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.id == physical_index.recipe_version_id)
        .one()
    )

    embedding_endpoint = _resolve_embedding_endpoint(session, recipe_version)

    adapter = _build_adapter(
        source,
        physical_index,
        recipe_version,
        vectors_db_url=vectors_db_url,
        embedding_endpoint=embedding_endpoint,
    )

    effective_request_id = request_id or str(uuid.uuid4())
    logger.info(
        "retrieval.query source=%s top_k=%d request_id=%s",
        source_slug,
        top_k,
        effective_request_id,
    )

    results = adapter.retrieve(
        query_text,
        top_k=top_k,
        request_id=effective_request_id,
        doc_section=doc_section,
        scope_entity_id=scope_entity_id,
    )
    return [replace(r, source_slug=source_slug) for r in results]


def refine(
    source_slug: str,
    *,
    doc_title: str,
    chunk_index: int,
    query_text: str,
    window: int = 2,
    session: Session,
    vectors_db_url: str | None = None,
    request_id: str | None = None,
    strategy: str = "adjacent",
    max_context_tokens: int | None = None,
    min_score: float | None = None,
    edge_types: list[str] | None = None,
    max_nodes: int | None = None,
) -> RefineOutput:
    """Return adjacent context around a previously retrieved chunk.

    Raises the same exceptions as ``query`` for unknown / unqueryable sources.
    """
    source = session.query(Source).filter(Source.slug == source_slug).one_or_none()
    if source is None:
        raise SourceNotFoundError(f"No source with slug {source_slug!r}")

    if source.active_physical_index_id is None:
        raise SourceNotQueryableError(
            f"Source {source_slug!r} has no active physical index; "
            f"run ingestion before querying it."
        )

    physical_index = (
        session.query(PhysicalIndex)
        .filter(PhysicalIndex.id == source.active_physical_index_id)
        .one()
    )
    recipe_version = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.id == physical_index.recipe_version_id)
        .one()
    )

    embedding_endpoint = _resolve_embedding_endpoint(session, recipe_version)

    adapter = _build_adapter(
        source,
        physical_index,
        recipe_version,
        vectors_db_url=vectors_db_url,
        embedding_endpoint=embedding_endpoint,
    )

    effective_request_id = request_id or str(uuid.uuid4())
    logger.info(
        "retrieval.refine source=%s doc_title=%s chunk_index=%d strategy=%s window=%d request_id=%s",
        source_slug,
        doc_title,
        chunk_index,
        strategy,
        window,
        effective_request_id,
    )

    return adapter.refine(
        doc_title=doc_title,
        chunk_index=chunk_index,
        query=query_text,
        window=window,
        request_id=effective_request_id,
        strategy=strategy,
        max_context_tokens=max_context_tokens,
        min_score=min_score,
        edge_types=edge_types,
        max_nodes=max_nodes,
    )


def resolve_chunk_id(
    source_slug: str,
    chunk_id: str,
    *,
    session: Session,
    vectors_db_url: str | None = None,
) -> tuple[str, int]:
    """Resolve a chunk UUID to its (doc_title, chunk_index) pair.

    Raises ``SourceNotFoundError`` / ``SourceNotQueryableError`` for
    unknown or unindexed sources, and ``LookupError`` if the UUID
    does not exist in the physical index.
    """
    source = session.query(Source).filter(Source.slug == source_slug).one_or_none()
    if source is None:
        raise SourceNotFoundError(f"No source with slug {source_slug!r}")

    if source.active_physical_index_id is None:
        raise SourceNotQueryableError(
            f"Source {source_slug!r} has no active physical index; "
            f"run ingestion before querying it."
        )

    physical_index = (
        session.query(PhysicalIndex)
        .filter(PhysicalIndex.id == source.active_physical_index_id)
        .one()
    )
    recipe_version = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.id == physical_index.recipe_version_id)
        .one()
    )

    adapter = _build_adapter(
        source,
        physical_index,
        recipe_version,
        vectors_db_url=vectors_db_url,
    )

    row = adapter.get_chunk_by_id(chunk_id)
    if row is None:
        raise LookupError(
            f"No chunk with id {chunk_id!r} in source {source_slug!r}"
        )

    return row["doc_title"] or "", row["chunk_index"]


def rrf_merge(
    per_source_results: dict[str, list[RetrievalResult]],
    *,
    k: int = 60,
    top_k: int = 10,
) -> list[RetrievalResult]:
    """Merge ranked lists from multiple sources using Reciprocal Rank Fusion.

    Each source's results are ranked by their original score (highest first).
    The RRF score for each hit is 1/(k + rank), where rank is 1-based.
    Hits are keyed by (source_slug, chunk_id) -- no cross-source dedup.
    """
    merged: list[RetrievalResult] = []
    for source_slug, results in per_source_results.items():
        for rank, result in enumerate(results, start=1):
            rrf_score = 1.0 / (k + rank)
            merged.append(replace(result, score=rrf_score, source_slug=source_slug))
    merged.sort(key=lambda r: r.score, reverse=True)
    return merged[:top_k]


def multi_query(
    source_slugs: list[str],
    query_text: str,
    *,
    session: Session,
    top_k: int = 10,
    vectors_db_url: str | None = None,
    request_id: str | None = None,
    doc_section: list[str] | None = None,
    scope_entity_id: str | None = None,
) -> dict[str, list[RetrievalResult]]:
    """Query multiple sources and return per-source results.

    Calls ``query()`` for each source slug. Sources that fail with
    ``SourceNotQueryableError`` are logged and skipped (the source may
    have been deactivated between listing and querying).
    """
    effective_request_id = request_id or str(uuid.uuid4())
    results: dict[str, list[RetrievalResult]] = {}
    for slug in source_slugs:
        try:
            results[slug] = query(
                slug,
                query_text,
                session=session,
                top_k=top_k,
                vectors_db_url=vectors_db_url,
                request_id=effective_request_id,
                doc_section=doc_section,
                scope_entity_id=scope_entity_id,
            )
        except SourceNotQueryableError:
            logger.warning("multi_query: skipping unqueryable source %s", slug)
    return results
