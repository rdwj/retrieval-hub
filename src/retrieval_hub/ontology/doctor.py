"""Ontology registry health checks."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from retrieval_hub.models import Source
from retrieval_hub.models.enums import SourceFamily, SourceStatus
from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import OntologyConcept as OntologyConceptModel
from retrieval_hub.models.ontology_relationship import (
    OntologyRelationship as OntologyRelationshipModel,
)

logger = logging.getLogger(__name__)


def check_missing_mappings(
    session: Session,
    *,
    source_slug: str | None = None,
    include_retired: bool = False,
) -> list[dict[str, Any]]:
    """Find source entities that have no ontology mapping."""
    query = session.query(Source)
    if source_slug is not None:
        query = query.filter(Source.slug == source_slug)

    findings: list[dict[str, Any]] = []
    for source in query.all():
        if source.status == SourceStatus.RETIRED and not include_retired:
            continue

        sc = source.semantic_context
        if not sc or not isinstance(sc, dict):
            continue
        entities = sc.get("entities")
        if not entities:
            continue

        entity_names = {e["name"] for e in entities if "name" in e}
        if not entity_names:
            continue

        mapped_local_names = {
            row.local_name
            for row in session.query(OntologyMapping.local_name).filter(
                OntologyMapping.source_slug == source.slug,
            )
        }

        unmapped = sorted(entity_names - mapped_local_names)
        if not unmapped:
            continue

        findings.append({
            "check": "missing_mappings",
            "source_slug": source.slug,
            "severity": "INFO" if not mapped_local_names else "WARN",
            "mapped_count": len(mapped_local_names),
            "total_entities": len(entity_names),
            "unmapped": unmapped,
        })

    return findings


def check_duplicate_mappings(
    session: Session,
    *,
    source_slug: str | None = None,
) -> list[dict[str, Any]]:
    """Find sources with multiple local names mapped to the same canonical name."""
    query = (
        session.query(
            OntologyMapping.source_slug,
            OntologyMapping.canonical_name,
            func.count(OntologyMapping.id).label("cnt"),
        )
        .group_by(OntologyMapping.source_slug, OntologyMapping.canonical_name)
        .having(func.count(OntologyMapping.id) > 1)
    )
    if source_slug is not None:
        query = query.filter(OntologyMapping.source_slug == source_slug)

    findings: list[dict[str, Any]] = []
    for slug, canonical, _cnt in query.all():
        local_names = sorted(
            row.local_name
            for row in session.query(OntologyMapping.local_name).filter(
                OntologyMapping.source_slug == slug,
                OntologyMapping.canonical_name == canonical,
            )
        )
        findings.append({
            "check": "duplicate_mappings",
            "source_slug": slug,
            "canonical_name": canonical,
            "severity": "INFO",
            "local_names": local_names,
        })

    return findings


def check_orphan_concepts(session: Session) -> list[dict[str, Any]]:
    """Find concepts not referenced by any ontology mapping."""
    mapped_names = {
        row.canonical_name
        for row in session.query(OntologyMapping.canonical_name).distinct()
    }

    findings: list[dict[str, Any]] = []
    for concept in session.query(OntologyConceptModel).all():
        if concept.name not in mapped_names:
            findings.append({
                "check": "orphan_concepts",
                "concept_name": concept.name,
                "severity": "INFO",
                "parent_name": concept.parent_name,
            })

    return findings


def check_dangling_relationships(session: Session) -> list[dict[str, Any]]:
    """Find relationships that reference non-existent concepts."""
    concept_names = {
        row.name
        for row in session.query(OntologyConceptModel.name)
    }

    findings: list[dict[str, Any]] = []
    for rel in session.query(OntologyRelationshipModel).all():
        src_missing = rel.source_concept not in concept_names
        tgt_missing = rel.target_concept not in concept_names

        if not src_missing and not tgt_missing:
            continue

        if src_missing and tgt_missing:
            dangling_end = "both"
        elif src_missing:
            dangling_end = "source"
        else:
            dangling_end = "target"

        findings.append({
            "check": "dangling_relationships",
            "severity": "WARN",
            "relationship_id": rel.id,
            "source_concept": rel.source_concept,
            "relationship": rel.relationship,
            "target_concept": rel.target_concept,
            "dangling_end": dangling_end,
        })

    return findings


_DOC_FAMILIES = frozenset({
    SourceFamily.DOCUMENT,
    SourceFamily.CLINICAL_DOCUMENT,
    SourceFamily.TECHNICAL_DOCUMENT,
    SourceFamily.CODE,
})


def check_stale_mappings(
    session: Session,
    *,
    source_slug: str | None = None,
    vectors_db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Find mappings whose local_name no longer exists in the source data."""
    from sqlalchemy import create_engine, text

    query = session.query(OntologyMapping)
    if source_slug is not None:
        query = query.filter(OntologyMapping.source_slug == source_slug)

    source_cache: dict[str, Source] = {}
    _index_table_cache: dict[str, str | None] = {}
    vectors_engine = None
    if vectors_db_url is not None:
        vectors_engine = create_engine(vectors_db_url)

    findings: list[dict[str, Any]] = []
    for mapping in query.all():
        slug = mapping.source_slug
        if slug not in source_cache:
            src = session.query(Source).filter(Source.slug == slug).first()
            source_cache[slug] = src
        src = source_cache[slug]
        if src is None:
            continue

        family = SourceFamily(src.family) if not isinstance(src.family, SourceFamily) else src.family

        if family in _DOC_FAMILIES:
            sc = src.semantic_context
            if not sc or not isinstance(sc, dict):
                continue
            entities = sc.get("entities") or []
            known_names = set()
            for e in entities:
                if "entity_type" in e:
                    known_names.add(e["entity_type"])
                if "name" in e:
                    known_names.add(e["name"])
                for alias in e.get("aliases", []):
                    known_names.add(alias)
            if mapping.local_name not in known_names:
                findings.append({
                    "check": "stale_mappings",
                    "source_slug": slug,
                    "canonical_name": mapping.canonical_name,
                    "local_name": mapping.local_name,
                    "severity": "WARN",
                    "reason": "local_name not in semantic_context entities",
                })

        elif family == SourceFamily.GRAPH:
            if vectors_engine is None:
                logger.warning(
                    "Skipping graph source %s: vectors_db_url not provided", slug
                )
                continue
            if not src.active_physical_index_id:
                logger.debug("No active index for graph source %s", slug)
                continue
            if slug not in _index_table_cache:
                from retrieval_hub.models.source import PhysicalIndex

                pi = session.query(PhysicalIndex).filter(
                    PhysicalIndex.id == src.active_physical_index_id,
                ).first()
                _index_table_cache[slug] = pi.location if pi else None
            table_name = _index_table_cache[slug]
            if table_name is None:
                continue
            if not table_name.replace("_", "").isalnum():
                logger.warning("Suspicious table name %r, skipping", table_name)
                continue
            with vectors_engine.connect() as conn:
                row = conn.execute(
                    text(
                        f"SELECT 1 FROM {table_name}"
                        " WHERE doc_section = :section"
                        " LIMIT 1"
                    ),
                    {"section": mapping.local_name},
                ).fetchone()
            if row is None:
                findings.append({
                    "check": "stale_mappings",
                    "source_slug": slug,
                    "canonical_name": mapping.canonical_name,
                    "local_name": mapping.local_name,
                    "severity": "WARN",
                    "reason": "local_name not found as doc_section in index",
                })

        else:
            logger.debug("Skipping staleness check for %s family: %s", family, slug)

    if vectors_engine is not None:
        vectors_engine.dispose()

    return findings


def check_family_mismatches(session: Session) -> list[dict[str, Any]]:
    """Find canonical concepts mapped across both graph and document families."""
    source_family_map: dict[str, SourceFamily] = {}
    for src in session.query(Source).all():
        source_family_map[src.slug] = (
            SourceFamily(src.family) if not isinstance(src.family, SourceFamily) else src.family
        )

    concept_sources: dict[str, list[str]] = {}
    for mapping in session.query(OntologyMapping).all():
        concept_sources.setdefault(mapping.canonical_name, []).append(mapping.source_slug)

    findings: list[dict[str, Any]] = []
    for canonical_name, slugs in sorted(concept_sources.items()):
        graph_sources: list[str] = []
        doc_sources: list[str] = []
        for slug in slugs:
            family = source_family_map.get(slug)
            if family is None:
                continue
            if family == SourceFamily.GRAPH:
                graph_sources.append(slug)
            elif family in _DOC_FAMILIES:
                doc_sources.append(slug)

        if graph_sources and doc_sources:
            findings.append({
                "check": "family_mismatches",
                "canonical_name": canonical_name,
                "severity": "INFO",
                "graph_sources": sorted(set(graph_sources)),
                "document_sources": sorted(set(doc_sources)),
            })

    return findings


def check_score_clustering(
    session: Session,
    *,
    concept_name: str | None = None,
) -> list[dict[str, Any]]:
    """Analyze authority score distribution for clustering issues."""
    query = session.query(OntologyMapping)
    if concept_name is not None:
        query = query.filter(OntologyMapping.canonical_name == concept_name)

    mappings = query.all()
    if not mappings:
        return []

    scores = [m.authority_score for m in mappings]
    min_score = min(scores)
    max_score = max(scores)

    findings: list[dict[str, Any]] = []

    spread = max_score - min_score
    if spread < 0.3:
        findings.append({
            "check": "score_clustering",
            "severity": "WARN",
            "issue": "narrow_range",
            "min_score": min_score,
            "max_score": max_score,
            "spread": round(spread, 4),
        })

    concepts_at_max = sorted({
        m.canonical_name for m in mappings if m.authority_score == max_score
    })
    if len(concepts_at_max) > 1:
        findings.append({
            "check": "score_clustering",
            "severity": "INFO",
            "issue": "shared_max",
            "max_score": max_score,
            "concepts_at_max": concepts_at_max,
        })

    per_concept: dict[str, list[float]] = {}
    for m in mappings:
        per_concept.setdefault(m.canonical_name, []).append(m.authority_score)

    for name, concept_scores in sorted(per_concept.items()):
        if len(concept_scores) >= 2 and len(set(concept_scores)) == 1:
            findings.append({
                "check": "score_clustering",
                "severity": "INFO",
                "issue": "no_within_concept_diff",
                "canonical_name": name,
                "score": concept_scores[0],
                "mapping_count": len(concept_scores),
            })

    return findings


def check_coverage_gaps(session: Session) -> list[dict[str, Any]]:
    """Find family groups where some sources lack mappings present in siblings."""
    source_family_map: dict[str, SourceFamily] = {}
    for src in session.query(Source).all():
        if src.status == SourceStatus.RETIRED:
            continue
        source_family_map[src.slug] = (
            SourceFamily(src.family) if not isinstance(src.family, SourceFamily) else src.family
        )

    family_groups: dict[SourceFamily, set[str]] = {}
    for slug, family in source_family_map.items():
        family_groups.setdefault(family, set()).add(slug)

    concept_family_sources: dict[str, dict[SourceFamily, set[str]]] = {}
    for mapping in session.query(OntologyMapping).all():
        family = source_family_map.get(mapping.source_slug)
        if family is None:
            continue
        concept_family_sources.setdefault(
            mapping.canonical_name, {}
        ).setdefault(family, set()).add(mapping.source_slug)

    findings: list[dict[str, Any]] = []
    for canonical_name, family_map in sorted(concept_family_sources.items()):
        for family, mapped_slugs in sorted(family_map.items(), key=lambda kv: kv[0].value):
            all_in_family = family_groups.get(family, set())
            unmapped = sorted(all_in_family - mapped_slugs)
            if unmapped:
                findings.append({
                    "check": "coverage_gaps",
                    "canonical_name": canonical_name,
                    "severity": "INFO",
                    "family": family.value,
                    "mapped_sources": sorted(mapped_slugs),
                    "unmapped_sources": unmapped,
                })

    return findings


def check_dead_mappings(
    session: Session,
    *,
    source_slug: str | None = None,
    vectors_db_url: str | None = None,
    embedding_url: str = "http://127.0.0.1:8081",
) -> list[dict[str, Any]]:
    """Find mappings that produce zero retrieval hits."""
    import retrieval_hub.retrieval.api as _retrieval_api
    from retrieval_hub.adapters.base import SourceAdapter
    from retrieval_hub.retrieval.api import ExpansionResult
    from retrieval_hub.retrieval.api import query as retrieval_query

    orig_resolve = getattr(_retrieval_api, "_resolve_embedding_endpoint", None)
    orig_expand = _retrieval_api.expand_doc_section_via_registry
    orig_adapter_expand = SourceAdapter._expand_doc_section

    _retrieval_api._resolve_embedding_endpoint = lambda *_a, **_kw: embedding_url
    _retrieval_api.expand_doc_section_via_registry = (
        lambda _s, _sl, ds, **_kw: ExpansionResult(
            doc_section=ds, query_terms=[],
        )
    )
    SourceAdapter._expand_doc_section = lambda _self, ds: ds

    query = session.query(OntologyMapping)
    if source_slug is not None:
        query = query.filter(OntologyMapping.source_slug == source_slug)

    findings: list[dict[str, Any]] = []
    try:
        for mapping in query.all():
            try:
                results = retrieval_query(
                    source_slug=mapping.source_slug,
                    query_text=mapping.local_name,
                    session=session,
                    top_k=1,
                    vectors_db_url=vectors_db_url,
                    doc_section=[mapping.local_name],
                )
                hit_count = len(results)
            except Exception as exc:
                logger.warning(
                    "Dead-mapping check for %s/%s failed: %s",
                    mapping.source_slug, mapping.local_name, exc,
                )
                hit_count = -1

            if hit_count == 0:
                findings.append({
                    "check": "dead_mappings",
                    "source_slug": mapping.source_slug,
                    "canonical_name": mapping.canonical_name,
                    "local_name": mapping.local_name,
                    "severity": "WARN",
                    "hit_count": 0,
                })
    finally:
        _retrieval_api.expand_doc_section_via_registry = orig_expand
        SourceAdapter._expand_doc_section = orig_adapter_expand
        if orig_resolve is not None:
            _retrieval_api._resolve_embedding_endpoint = orig_resolve

    return findings
