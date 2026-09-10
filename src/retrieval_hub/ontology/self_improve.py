"""Eval-driven authority score adjustment.

Evaluates mapping quality from benchmark data and adjusts authority scores
to reflect observed retrieval performance.  Static base scores from
``compute_authority_scores`` are multiplied by an eval factor derived from
per-mapping precision metrics, then clamped to ``[SCORE_FLOOR, SCORE_CEILING]``.

The pipeline is idempotent: each run recomputes from the static base, so
repeated runs with the same benchmark data produce identical results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.ontology.authority import compute_authority_scores

logger = logging.getLogger(__name__)

SCORE_FLOOR = 0.3
SCORE_CEILING = 1.0
HEALTHY_BOOST = 1.05
UNDERPERFORMING_DAMP = 0.9
DEAD_DAMP = 0.8
PRECISION_HEALTHY_THRESHOLD = 0.3
PRECISION_BOOST_THRESHOLD = 0.5


@dataclass
class MappingFinding:
    mapping_id: int
    canonical_name: str
    source_slug: str
    local_name: str
    category: str  # "healthy", "underperforming", "dead", "missing_coverage"
    authority_score: float  # current DB score
    metrics: dict[str, Any]


@dataclass
class ScoreAdjustment:
    mapping_id: int
    canonical_name: str
    source_slug: str
    old_score: float
    new_score: float
    reason: str


def evaluate_mapping_quality(
    session: Session,
    per_mapping_quality: dict[str, Any],
) -> list[MappingFinding]:
    """Classify each mapping's retrieval health from benchmark metrics.

    Parameters
    ----------
    session:
        SQLAlchemy session for reading ``OntologyMapping`` rows.
    per_mapping_quality:
        Dict keyed by ``"canonical_name||source_slug"``, each value containing
        ``canonical_name``, ``source_slug``, ``local_names``,
        ``queries_exercised``, ``total_hits``, ``total_in_top_k``,
        ``precision``, ``is_dead``, and ``mean_authority_score``.

    Returns
    -------
    list[MappingFinding]
        One finding per mapping row that appears in the benchmark data, plus
        ``missing_coverage`` findings for sources that have mappings for a
        concept but were not exercised by the benchmark.
    """
    mappings = session.query(OntologyMapping).all()
    if not mappings:
        return []

    # Build lookup: (canonical_name, source_slug) -> [mapping rows]
    mapping_lookup: dict[tuple[str, str], list[OntologyMapping]] = {}
    for m in mappings:
        mapping_lookup.setdefault((m.canonical_name, m.source_slug), []).append(m)

    # Track which concepts appear in the benchmark data and which
    # (concept, source) pairs were exercised.
    concepts_in_benchmark: set[str] = set()
    exercised_pairs: set[tuple[str, str]] = set()

    findings: list[MappingFinding] = []

    for _key, entry in per_mapping_quality.items():
        canonical = entry["canonical_name"]
        slug = entry["source_slug"]
        concepts_in_benchmark.add(canonical)
        exercised_pairs.add((canonical, slug))

        rows = mapping_lookup.get((canonical, slug), [])
        if not rows:
            logger.debug(
                "Benchmark entry %s||%s has no matching mapping rows",
                canonical,
                slug,
            )
            continue

        # Classify based on benchmark metrics.
        if entry.get("is_dead"):
            category = "dead"
        elif entry.get("total_hits", 0) > 0 and entry.get("precision", 0) < PRECISION_HEALTHY_THRESHOLD:
            category = "underperforming"
        elif entry.get("total_hits", 0) > 0:
            category = "healthy"
        else:
            # No hits at all but not flagged as dead (edge case).
            category = "dead"

        for row in rows:
            findings.append(MappingFinding(
                mapping_id=row.id,
                canonical_name=canonical,
                source_slug=slug,
                local_name=row.local_name,
                category=category,
                authority_score=row.authority_score,
                metrics=dict(entry),
            ))

    # Missing coverage: for each concept in the benchmark, find sources that
    # have mappings for that concept but were NOT exercised.
    concept_all_sources: dict[str, set[str]] = {}
    for m in mappings:
        concept_all_sources.setdefault(m.canonical_name, set()).add(m.source_slug)

    for concept in concepts_in_benchmark:
        all_sources = concept_all_sources.get(concept, set())
        exercised_sources = {
            slug for (cn, slug) in exercised_pairs if cn == concept
        }
        missing_sources = all_sources - exercised_sources

        for slug in sorted(missing_sources):
            rows = mapping_lookup.get((concept, slug), [])
            for row in rows:
                findings.append(MappingFinding(
                    mapping_id=row.id,
                    canonical_name=concept,
                    source_slug=slug,
                    local_name=row.local_name,
                    category="missing_coverage",
                    authority_score=row.authority_score,
                    metrics={},
                ))

    # Summary log.
    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    logger.info(
        "Mapping quality evaluation: %d findings (%s)",
        len(findings),
        ", ".join(f"{cat}={n}" for cat, n in sorted(by_category.items())),
    )

    return findings


def adjust_authority_scores(
    session: Session,
    findings: list[MappingFinding],
) -> list[ScoreAdjustment]:
    """Compute score adjustments by applying eval factors to static base scores.

    Static base scores come from ``compute_authority_scores()``.  Each finding's
    category determines a multiplicative factor.  The result is clamped to
    ``[SCORE_FLOOR, SCORE_CEILING]``.

    Only mappings whose new score differs from the current DB value produce
    an adjustment record.
    """
    base_scores = dict(compute_authority_scores(session))

    adjustments: list[ScoreAdjustment] = []
    for finding in findings:
        base = base_scores.get(finding.mapping_id)
        if base is None:
            logger.debug(
                "No base score for mapping %d (%s/%s), skipping",
                finding.mapping_id,
                finding.canonical_name,
                finding.source_slug,
            )
            continue

        if finding.category == "healthy":
            precision = finding.metrics.get("precision", 0)
            eval_factor = HEALTHY_BOOST if precision >= PRECISION_BOOST_THRESHOLD else 1.0
        elif finding.category == "underperforming":
            eval_factor = UNDERPERFORMING_DAMP
        elif finding.category == "dead":
            eval_factor = DEAD_DAMP
        else:
            # missing_coverage and any unknown category.
            eval_factor = 1.0

        raw = base * eval_factor
        new_score = round(min(max(raw, SCORE_FLOOR), SCORE_CEILING), 3)

        if new_score == finding.authority_score:
            continue

        reason = f"{finding.category} (factor={eval_factor}, base={base})"
        adjustments.append(ScoreAdjustment(
            mapping_id=finding.mapping_id,
            canonical_name=finding.canonical_name,
            source_slug=finding.source_slug,
            old_score=finding.authority_score,
            new_score=new_score,
            reason=reason,
        ))
        logger.debug(
            "Score adjustment: mapping %d (%s/%s) %.3f -> %.3f (%s)",
            finding.mapping_id,
            finding.canonical_name,
            finding.source_slug,
            finding.authority_score,
            new_score,
            reason,
        )

    logger.info(
        "Authority score adjustments: %d of %d findings produced changes",
        len(adjustments),
        len(findings),
    )
    return adjustments


def apply_adjustments(session: Session, adjustments: list[ScoreAdjustment]) -> None:
    """Write score adjustments to the database.

    Updates each ``OntologyMapping`` row's ``authority_score`` and commits
    the transaction.
    """
    for adj in adjustments:
        session.query(OntologyMapping).filter(
            OntologyMapping.id == adj.mapping_id,
        ).update({"authority_score": adj.new_score})

    session.commit()
    logger.info("Applied %d authority score adjustments", len(adjustments))
