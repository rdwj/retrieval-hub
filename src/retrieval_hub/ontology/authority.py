"""Authority scoring for ontology mappings."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from retrieval_hub.models import Source
from retrieval_hub.models.ontology import OntologyMapping

logger = logging.getLogger(__name__)

STATUS_WEIGHTS: dict[str, float] = {
    "published": 1.0,
    "curated": 0.8,
    "draft": 0.5,
}
DEFAULT_STATUS_WEIGHT = 0.8

FAMILY_WEIGHTS: dict[str, float] = {
    "graph": 1.3,
    "clinical_document": 1.2,
    "tabular": 1.1,
    "technical_document": 1.0,
    "document": 0.9,
}
DEFAULT_FAMILY_WEIGHT = 1.0

AGREEMENT_BONUS_PER_SOURCE = 0.1
MAX_AGREEMENT_BONUS = 1.3

FORMAL_TERMINOLOGY_BOOST = 1.2

COVERAGE_LOG_SCALE = 0.05

FRESHNESS_THRESHOLDS: list[tuple[int, float]] = [
    (30, 1.1),
    (90, 1.05),
]
FRESHNESS_DEFAULT = 1.0

NORMALIZED_FLOOR = 0.3
NORMALIZED_CEILING = 1.0


def _agreement_bonus(num_sources: int) -> float:
    return min(1.0 + AGREEMENT_BONUS_PER_SOURCE * (num_sources - 1), MAX_AGREEMENT_BONUS)


def _terminology_weight(sc: dict) -> float:
    if sc.get("formal_terminology"):
        return FORMAL_TERMINOLOGY_BOOST
    return 1.0


def _coverage_weight(sc: dict) -> float:
    entities = sc.get("entities", [])
    count = len(entities) if isinstance(entities, list) else 0
    if count <= 1:
        return 1.0
    return 1.0 + COVERAGE_LOG_SCALE * math.log2(count)


def _freshness_weight(src: Source | None, now: datetime) -> float:
    refresh = getattr(src, "last_refresh_at", None)
    if refresh is None:
        return FRESHNESS_DEFAULT
    age_days = (now - refresh).days
    for threshold_days, boost in FRESHNESS_THRESHOLDS:
        if age_days <= threshold_days:
            return boost
    return FRESHNESS_DEFAULT


def compute_authority_scores(session: Session) -> list[tuple[int, float]]:
    """Compute authority scores for all ontology mappings.

    Returns ``[(mapping_id, score), ...]`` where score is a composite of
    source status, family, cross-source agreement, formal terminology,
    entity coverage, and data freshness.

    Raw scores are normalized to ``[NORMALIZED_FLOOR, NORMALIZED_CEILING]``
    using min-max scaling to preserve relative ordering while ensuring
    compatibility with downstream score clamping.
    """
    mappings = session.query(OntologyMapping).all()
    if not mappings:
        return []

    source_slugs = {m.source_slug for m in mappings}
    sources = (
        session.query(Source)
        .filter(Source.slug.in_(source_slugs))
        .all()
    )
    source_by_slug: dict[str, Source] = {s.slug: s for s in sources}

    concept_distinct_sources: dict[str, set[str]] = {}
    for m in mappings:
        concept_distinct_sources.setdefault(m.canonical_name, set()).add(m.source_slug)
    concept_source_count = {k: len(v) for k, v in concept_distinct_sources.items()}

    now = datetime.now(UTC)
    results: list[tuple[int, float]] = []
    for m in mappings:
        src = source_by_slug.get(m.source_slug)

        status = getattr(src, "status", None) or ""
        status_w = STATUS_WEIGHTS.get(str(status), DEFAULT_STATUS_WEIGHT)

        sc = getattr(src, "semantic_context", None) or {}
        if not isinstance(sc, dict):
            sc = {}

        explicit_weight = None
        raw = sc.get("authority_weight")
        if raw is not None:
            try:
                explicit_weight = float(raw)
            except (TypeError, ValueError):
                pass

        if explicit_weight is not None:
            family_w = explicit_weight
        else:
            family = getattr(src, "family", None) or ""
            family_w = FAMILY_WEIGHTS.get(str(family), DEFAULT_FAMILY_WEIGHT)

        agreement = _agreement_bonus(
            concept_source_count.get(m.canonical_name, 1),
        )
        terminology = _terminology_weight(sc)
        coverage = _coverage_weight(sc)
        freshness = _freshness_weight(src, now)

        score = round(
            status_w * family_w * agreement * terminology * coverage * freshness,
            3,
        )
        results.append((m.id, score))

    # Normalize scores to [NORMALIZED_FLOOR, NORMALIZED_CEILING]
    if len(results) <= 1:
        # Single mapping: place at ceiling
        if results:
            results = [(results[0][0], NORMALIZED_CEILING)]
        return results

    raw_scores = [s for _, s in results]
    raw_min = min(raw_scores)
    raw_max = max(raw_scores)

    if raw_max == raw_min:
        # All scores identical: place at midpoint
        mid = round((NORMALIZED_FLOOR + NORMALIZED_CEILING) / 2, 3)
        return [(mapping_id, mid) for mapping_id, _ in results]

    span = raw_max - raw_min
    norm_span = NORMALIZED_CEILING - NORMALIZED_FLOOR
    results = [
        (mapping_id, round(NORMALIZED_FLOOR + (raw - raw_min) / span * norm_span, 3))
        for mapping_id, raw in results
    ]

    return results
