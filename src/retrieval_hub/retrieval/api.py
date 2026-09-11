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

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

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
from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import OntologyConcept

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


@dataclass(frozen=True)
class ExpansionResult:
    """Separates doc_section filter values from query expansion terms.

    For graph-family sources, hierarchy children go into ``doc_section``
    (entity types are doc_section values). For document-family sources,
    hierarchy children go into ``query_terms`` (appended to query text
    before embedding).
    """

    doc_section: list[str] | None
    query_terms: list[str]


@dataclass(frozen=True)
class ConceptSourceMapping:
    """One source's role in a concept query."""

    source_slug: str
    local_names: list[str]
    authority_weight: float


class SourceNotFoundError(LookupError):
    """Raised when ``query`` cannot find a source by slug."""


class SourceNotQueryableError(RuntimeError):
    """Raised when the source exists but has no active physical index."""


class UnsupportedFamilyError(RuntimeError):
    """Raised when no adapter exists for the source's family yet."""


class ConceptNotMappedError(LookupError):
    """Raised when a concept has no queryable source mappings."""


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


def _expand_concepts_via_hierarchy(
    session: Session,
    canonical_names: set[str],
    max_depth: int = 5,
) -> set[str]:
    """Walk parent→child edges to find all descendant concepts.

    Given a set of canonical concept names, returns those names plus all
    their children (recursively, up to ``max_depth`` levels).  Uses
    iterative breadth-first expansion to avoid deep recursion.
    """
    if not canonical_names:
        return canonical_names

    expanded = set(canonical_names)
    frontier = set(canonical_names)

    for _ in range(max_depth):
        if not frontier:
            break
        children = (
            session.execute(
                select(OntologyConcept.name).where(
                    OntologyConcept.parent_name.in_(frontier)
                )
            )
            .scalars()
            .all()
        )
        new = set(children) - expanded
        if not new:
            break
        expanded |= new
        frontier = new

    return expanded


def expand_doc_section_via_registry(
    session: Session,
    source_slug: str,
    doc_section: list[str] | None,
    *,
    source_family: SourceFamily | None = None,
) -> ExpansionResult:
    """Expand doc_section values using the ontology_mapping registry.

    Performs a self-join on ontology_mapping to find local names in the
    target source whose canonical name matches any input value (either as
    a local_name in any source or as a canonical_name directly). Returns
    the union of original values and any registry-discovered expansions.

    When the ontology_concept table contains hierarchy data, the expansion
    also walks parent->child edges: searching for "Condition" will include
    children like "Hypertension", "PTSD", etc.

    For graph-family sources, hierarchy children go into the doc_section
    filter (entity types are doc_section values). For document-family
    sources, hierarchy children go into ``query_terms`` (appended to the
    query text before embedding) since doc_sections are structural
    headings, not concept types.

    Returns an ``ExpansionResult`` with ``doc_section`` unchanged and
    empty ``query_terms`` when the input is ``None`` or empty.
    """
    if not doc_section:
        return ExpansionResult(doc_section=doc_section, query_terms=[])

    # Resolve source family for routing hierarchy expansion.
    if source_family is None:
        source_obj = (
            session.query(Source).filter(Source.slug == source_slug).one_or_none()
        )
        family = source_obj.family if source_obj else SourceFamily.GRAPH
    else:
        family = source_family

    is_doc_family = family in (
        SourceFamily.DOCUMENT,
        SourceFamily.CLINICAL_DOCUMENT,
        SourceFamily.TECHNICAL_DOCUMENT,
        SourceFamily.CODE,
    )

    om_any = aliased(OntologyMapping)
    om_target = aliased(OntologyMapping)

    # Stage 1: Flat expansion (alias names ARE real doc_section values).
    stmt = (
        select(om_target.local_name)
        .select_from(om_any)
        .join(om_target, om_any.canonical_name == om_target.canonical_name)
        .where(
            om_target.source_slug == source_slug,
            (om_any.local_name.in_(doc_section))
            | (om_any.canonical_name.in_(doc_section)),
        )
        .distinct()
    )

    rows = session.execute(stmt).scalars().all()
    expanded = set(doc_section) | set(rows)

    # Stage 2: Hierarchy expansion -- route by family.
    # Wrapped in try/except so that deployments without the ontology_concept
    # migration fall back to flat expansion only.
    query_terms: list[str] = []
    try:
        input_canonicals_stmt = (
            select(OntologyMapping.canonical_name)
            .where(
                (OntologyMapping.local_name.in_(doc_section))
                | (OntologyMapping.canonical_name.in_(doc_section))
            )
            .distinct()
        )
        input_canonicals = set(
            session.execute(input_canonicals_stmt).scalars().all()
        )
        direct_canonical_stmt = (
            select(OntologyConcept.name).where(
                OntologyConcept.name.in_(doc_section)
            )
        )
        input_canonicals |= set(
            session.execute(direct_canonical_stmt).scalars().all()
        )

        if input_canonicals:
            all_concepts = _expand_concepts_via_hierarchy(session, input_canonicals)
            new_concepts = all_concepts - input_canonicals
            if new_concepts:
                child_locals_stmt = (
                    select(OntologyMapping.local_name)
                    .where(
                        OntologyMapping.source_slug == source_slug,
                        OntologyMapping.canonical_name.in_(new_concepts),
                    )
                    .distinct()
                )
                child_locals = set(
                    session.execute(child_locals_stmt).scalars().all()
                )

                if is_doc_family:
                    # Document sources: hierarchy children -> query terms
                    query_terms = sorted(child_locals | new_concepts)
                else:
                    # Graph sources: hierarchy children -> doc_section filter
                    expanded |= child_locals
                    expanded |= new_concepts
    except Exception:
        logger.debug(
            "ontology_concept table not available; skipping hierarchy expansion",
            exc_info=True,
        )

    return ExpansionResult(doc_section=list(expanded), query_terms=query_terms)


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

    expansion = expand_doc_section_via_registry(
        session, source_slug, doc_section,
        source_family=source.family,
    )
    if expansion.doc_section != doc_section or expansion.query_terms:
        logger.info(
            "retrieval.query ontology expansion source=%s original=%s "
            "doc_section=%s query_terms=%s",
            source_slug,
            doc_section,
            expansion.doc_section,
            expansion.query_terms,
        )

    effective_query = query_text
    if expansion.query_terms:
        effective_query = f"{query_text} {' '.join(expansion.query_terms)}"

    logger.info(
        "retrieval.query source=%s top_k=%d request_id=%s",
        source_slug,
        top_k,
        effective_request_id,
    )

    results = adapter.retrieve(
        effective_query,
        top_k=top_k,
        request_id=effective_request_id,
        doc_section=expansion.doc_section,
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
    source_weights: dict[str, float] | None = None,
) -> list[RetrievalResult]:
    """Merge ranked lists from multiple sources using Reciprocal Rank Fusion.

    Each source's results are ranked by their original score (highest first).
    The RRF score for each hit is 1/(k + rank), where rank is 1-based.
    Hits are keyed by (source_slug, chunk_id) -- no cross-source dedup.

    When ``source_weights`` is provided, each hit's RRF score is multiplied
    by the weight for its source (defaulting to 1.0 for unlisted sources).
    """
    merged: list[RetrievalResult] = []
    for source_slug, results in per_source_results.items():
        weight = source_weights.get(source_slug, 1.0) if source_weights else 1.0
        for rank, result in enumerate(results, start=1):
            rrf_score = (1.0 / (k + rank)) * weight
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


def resolve_concept_sources(
    session: Session,
    concept: str,
    *,
    expand_hierarchy: bool = True,
) -> list[ConceptSourceMapping]:
    """Resolve a canonical concept to queryable sources with per-source doc_section filters.

    Returns sources sorted by authority_weight descending.
    Only includes sources with an active physical index.
    """
    rows = (
        session.execute(
            select(OntologyMapping).where(
                func.lower(OntologyMapping.canonical_name) == concept.lower()
            )
        )
        .scalars()
        .all()
    )

    if expand_hierarchy:
        initial_canonicals = {r.canonical_name for r in rows}
        descendants = _expand_concepts_via_hierarchy(session, initial_canonicals)
        new_canonicals = descendants - initial_canonicals
        if new_canonicals:
            extra_rows = (
                session.execute(
                    select(OntologyMapping).where(
                        OntologyMapping.canonical_name.in_(new_canonicals)
                    )
                )
                .scalars()
                .all()
            )
            rows = list(rows) + list(extra_rows)

    groups: dict[str, list[OntologyMapping]] = {}
    for m in rows:
        groups.setdefault(m.source_slug, []).append(m)

    active_slugs: set[str] = set()
    if groups:
        active_sources = (
            session.execute(
                select(Source.slug).where(
                    Source.slug.in_(groups.keys()),
                    Source.active_physical_index_id.isnot(None),
                )
            )
            .scalars()
            .all()
        )
        active_slugs = set(active_sources)

    mappings = []
    for slug, group in groups.items():
        if slug not in active_slugs:
            continue
        local_names = sorted({m.local_name for m in group})
        authority_weight = max(m.authority_score for m in group)
        mappings.append(
            ConceptSourceMapping(
                source_slug=slug,
                local_names=local_names,
                authority_weight=authority_weight,
            )
        )

    mappings.sort(key=lambda m: m.authority_weight, reverse=True)
    return mappings


def concept_query(
    concept: str,
    query_text: str,
    *,
    session: Session,
    top_k: int = 10,
    vectors_db_url: str | None = None,
    request_id: str | None = None,
    expand_hierarchy: bool = True,
) -> tuple[list[RetrievalResult], dict[str, ConceptSourceMapping]]:
    """Query by canonical concept, fanning out to all mapped sources.

    Resolves the concept to source slugs via the ontology registry,
    queries each source with per-source doc_section filters, and merges
    results using authority-weighted RRF.

    Returns (merged_results, source_mappings_by_slug).
    Raises ConceptNotMappedError if no queryable sources map to the concept.
    """
    mappings = resolve_concept_sources(
        session, concept, expand_hierarchy=expand_hierarchy
    )
    if not mappings:
        raise ConceptNotMappedError(
            f"No queryable sources map to concept {concept!r}"
        )

    effective_request_id = request_id or str(uuid.uuid4())

    per_source: dict[str, list[RetrievalResult]] = {}
    for mapping in mappings:
        try:
            per_source[mapping.source_slug] = query(
                mapping.source_slug,
                query_text,
                session=session,
                top_k=top_k,
                vectors_db_url=vectors_db_url,
                request_id=effective_request_id,
                doc_section=mapping.local_names,
            )
        except SourceNotQueryableError:
            logger.warning(
                "concept_query: skipping unqueryable source %s",
                mapping.source_slug,
            )

    authority_weights = {m.source_slug: m.authority_weight for m in mappings}
    merged = rrf_merge(per_source, top_k=top_k, source_weights=authority_weights)
    mappings_dict = {m.source_slug: m for m in mappings}

    try:
        from retrieval_hub.ontology.monitoring import record_query_metrics
        record_query_metrics(session, concept, mappings_dict, per_source)
    except Exception:
        logger.debug("Query metrics recording failed", exc_info=True)

    return merged, mappings_dict
