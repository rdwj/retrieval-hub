"""Query monitoring for ontology mappings."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.query_metrics import OntologyQueryMetric
from retrieval_hub.retrieval.api import ConceptSourceMapping, RetrievalResult

logger = logging.getLogger(__name__)


def record_query_metrics(
    session: Session,
    concept: str,
    mappings_dict: dict[str, ConceptSourceMapping],
    per_source_results: dict[str, list[RetrievalResult]],
) -> int:
    """Record per-mapping metrics from a concept query.

    For each source mapping that was exercised, looks up the mapping rows
    in the DB to get mapping IDs, counts the results, and writes one
    OntologyQueryMetric row per mapping.

    Returns the number of metric rows written.
    """
    if not mappings_dict:
        return 0

    # Look up all mapping rows for the exercised sources + concept
    source_slugs = list(mappings_dict.keys())
    mapping_rows = (
        session.execute(
            select(OntologyMapping).where(
                OntologyMapping.source_slug.in_(source_slugs),
                func.lower(OntologyMapping.canonical_name) == concept.lower(),
            )
        )
        .scalars()
        .all()
    )

    # Also look up mappings for descendant concepts that were part of the expansion
    # Group rows by source_slug for matching
    rows_by_source: dict[str, list[OntologyMapping]] = {}
    for row in mapping_rows:
        rows_by_source.setdefault(row.source_slug, []).append(row)

    now = datetime.now(UTC)
    count = 0

    for slug, csm in mappings_dict.items():
        results = per_source_results.get(slug, [])
        hit_count = len(results)
        top_score = max((r.score for r in results), default=None)

        rows = rows_by_source.get(slug, [])
        if not rows:
            # No matching mapping rows in DB — can happen if mappings were
            # deleted between concept resolution and here. Log and skip.
            logger.debug(
                "No mapping rows for %s/%s, skipping metric recording",
                concept, slug,
            )
            continue

        for row in rows:
            metric = OntologyQueryMetric(
                mapping_id=row.id,
                source_slug=slug,
                canonical_name=row.canonical_name,
                hit_count=hit_count,
                top_score=top_score,
                query_timestamp=now,
            )
            session.add(metric)
            count += 1

    session.flush()
    logger.debug("Recorded %d query metrics for concept=%s", count, concept)
    return count


def get_mapping_hit_rates(
    session: Session,
    *,
    days: int = 7,
    source_slug: str | None = None,
) -> list[dict]:
    """Compute rolling hit rates per mapping over the last N days.

    Returns a list of dicts with:
    - mapping_id
    - source_slug
    - canonical_name
    - total_queries: number of times the mapping was exercised
    - hit_queries: number of times hit_count > 0
    - hit_rate: hit_queries / total_queries
    - avg_top_score: average of non-null top_score values
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    stmt = (
        select(
            OntologyQueryMetric.mapping_id,
            OntologyQueryMetric.source_slug,
            OntologyQueryMetric.canonical_name,
            func.count().label("total_queries"),
            func.sum(
                case((OntologyQueryMetric.hit_count > 0, 1), else_=0)
            ).label("hit_queries"),
            func.avg(OntologyQueryMetric.top_score).label("avg_top_score"),
        )
        .where(OntologyQueryMetric.query_timestamp >= cutoff)
        .group_by(
            OntologyQueryMetric.mapping_id,
            OntologyQueryMetric.source_slug,
            OntologyQueryMetric.canonical_name,
        )
    )

    if source_slug is not None:
        stmt = stmt.where(OntologyQueryMetric.source_slug == source_slug)

    rows = session.execute(stmt).all()

    results = []
    for row in rows:
        total = row.total_queries or 0
        hits = row.hit_queries or 0
        results.append({
            "mapping_id": row.mapping_id,
            "source_slug": row.source_slug,
            "canonical_name": row.canonical_name,
            "total_queries": total,
            "hit_queries": hits,
            "hit_rate": round(hits / total, 3) if total > 0 else 0.0,
            "avg_top_score": round(float(row.avg_top_score), 3) if row.avg_top_score is not None else None,
        })

    return results
