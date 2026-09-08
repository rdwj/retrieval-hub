"""Authority scoring for ontology mappings."""

from __future__ import annotations

import logging
from collections import Counter

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


def _agreement_bonus(num_sources: int) -> float:
    return min(1.0 + AGREEMENT_BONUS_PER_SOURCE * (num_sources - 1), MAX_AGREEMENT_BONUS)


def compute_authority_scores(session: Session) -> list[tuple[int, float]]:
    """Compute authority scores for all ontology mappings.

    Returns ``[(mapping_id, score), ...]`` where score is a composite of
    source status weight, source family weight, and cross-source agreement.
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

    concept_source_counts: Counter[str] = Counter()
    for m in mappings:
        concept_source_counts[m.canonical_name] += 1
    concept_distinct_sources: dict[str, int] = {}
    for m in mappings:
        concept_distinct_sources.setdefault(m.canonical_name, set()).add(m.source_slug)
    concept_source_count = {k: len(v) for k, v in concept_distinct_sources.items()}

    results: list[tuple[int, float]] = []
    for m in mappings:
        src = source_by_slug.get(m.source_slug)

        status = getattr(src, "status", None) or ""
        status_w = STATUS_WEIGHTS.get(str(status), DEFAULT_STATUS_WEIGHT)

        sc = getattr(src, "semantic_context", None) or {}
        explicit_weight = None
        if isinstance(sc, dict):
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

        num_sources = concept_source_count.get(m.canonical_name, 1)
        agreement = _agreement_bonus(num_sources)

        score = round(status_w * family_w * agreement, 3)
        results.append((m.id, score))

    return results
