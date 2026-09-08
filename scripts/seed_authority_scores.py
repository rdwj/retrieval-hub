#!/usr/bin/env python3
"""Compute and apply authority scores for all ontology_mapping rows.

Scores are derived from source status, source family, optional explicit
authority_weight in semantic_context, and cross-source agreement per
canonical concept.  Idempotent — re-running recalculates all scores.

Usage:
    python scripts/seed_authority_scores.py [--db-url URL] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"

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


def compute_scores(conn: psycopg.Connection) -> list[tuple[int, float]]:
    """Compute authority scores for all ontology_mapping rows."""

    rows = conn.execute(
        """
        SELECT om.id, om.canonical_name, om.source_slug,
               s.status, s.family, s.semantic_context
        FROM ontology_mapping om
        LEFT JOIN source s ON s.slug = om.source_slug
        ORDER BY om.id
        """
    ).fetchall()

    if not rows:
        return []

    concept_sources: dict[str, set[str]] = {}
    for _id, canon, slug, _status, _family, _sc in rows:
        concept_sources.setdefault(canon, set()).add(slug)

    results: list[tuple[int, float]] = []
    for mapping_id, canon, _slug, status, family, sc_raw in rows:
        status_w = STATUS_WEIGHTS.get(status or "", DEFAULT_STATUS_WEIGHT)

        explicit_weight = None
        if sc_raw is not None:
            sc = json.loads(sc_raw) if isinstance(sc_raw, str) else sc_raw
            raw = sc.get("authority_weight") if isinstance(sc, dict) else None
            if raw is not None:
                try:
                    explicit_weight = float(raw)
                except (TypeError, ValueError):
                    pass

        if explicit_weight is not None:
            family_w = explicit_weight
        else:
            family_w = FAMILY_WEIGHTS.get(family or "", DEFAULT_FAMILY_WEIGHT)

        num_sources = len(concept_sources.get(canon, set()))
        agreement = min(
            1.0 + AGREEMENT_BONUS_PER_SOURCE * (num_sources - 1),
            MAX_AGREEMENT_BONUS,
        )

        score = round(status_w * family_w * agreement, 3)
        results.append((mapping_id, score))

    return results


def apply_scores(
    conn: psycopg.Connection,
    scores: list[tuple[int, float]],
    dry_run: bool,
) -> int:
    """Update ontology_mapping.authority_score for each mapping."""
    updated = 0
    for mapping_id, score in scores:
        if dry_run:
            logger.info("[DRY RUN] mapping %d -> score %.3f", mapping_id, score)
            updated += 1
            continue
        conn.execute(
            "UPDATE ontology_mapping SET authority_score = %s WHERE id = %s",
            (score, mapping_id),
        )
        updated += 1
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with psycopg.connect(args.db_url) as conn:
        scores = compute_scores(conn)
        if not scores:
            logger.warning("No ontology_mapping rows found")
            return

        logger.info("Computed scores for %d mappings", len(scores))

        score_values = [s for _, s in scores]
        logger.info(
            "Score range: %.3f - %.3f (mean %.3f)",
            min(score_values),
            max(score_values),
            sum(score_values) / len(score_values),
        )

        updated = apply_scores(conn, scores, args.dry_run)

        if not args.dry_run:
            conn.commit()
            logger.info("Updated %d ontology_mapping rows", updated)
        else:
            logger.info("[DRY RUN] Would update %d rows", updated)


if __name__ == "__main__":
    main()
