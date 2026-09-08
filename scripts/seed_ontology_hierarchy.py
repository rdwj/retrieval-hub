#!/usr/bin/env python3
"""Seed parent/child (IS-A) edges into the ontology_concept table.

Reads IS_A relationships from Memgraph and sets parent_name on matching
ontology_concept rows.  When Memgraph is unavailable, use --synthetic to
seed a reasonable biomedical hierarchy for testing.

Usage:
    python scripts/seed_ontology_hierarchy.py [--db-url URL] [--dry-run]
    python scripts/seed_ontology_hierarchy.py --synthetic [--db-url URL] [--dry-run]
    python scripts/seed_ontology_hierarchy.py --memgraph-host HOST --memgraph-port PORT [--db-url URL]
"""

from __future__ import annotations

import argparse
import logging

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"

SYNTHETIC_HIERARCHY: list[tuple[str, str]] = [
    # (child, parent) — child IS_A parent
    ("Hypertension", "Condition"),
    ("PTSD", "Condition"),
    ("MDD", "Condition"),
    ("COPD", "Condition"),
    ("Obesity", "Condition"),
    ("Type 2 Diabetes Mellitus", "Condition"),
    ("Insomnia", "Condition"),
    ("Chronic Low Back Pain", "Condition"),
    ("Mild Traumatic Brain Injury", "Condition"),
    ("Alcohol Use Disorder", "Substance Use Disorder"),
    ("Opioid Use Disorder", "Substance Use Disorder"),
    ("Substance Use Disorder", "Condition"),
    ("Metformin", "Compound"),
    ("ACE Inhibitors", "Compound"),
    ("SSRIs", "Compound"),
    ("Statins", "Compound"),
    ("CBT", "Procedure"),
    ("EMDR", "Procedure"),
    ("PE", "Procedure"),
    ("PHQ-9", "Finding"),
    ("GAD-7", "Finding"),
    ("PCL-5", "Finding"),
    ("AUDIT-C", "Finding"),
    ("C-SSRS", "Finding"),
    ("Morphologic Abnormality", "Finding"),
]


def load_hierarchy_from_memgraph(
    host: str, port: int
) -> list[tuple[str, str]]:
    """Read IS_A edges from Memgraph and return (child, parent) pairs."""
    import mgclient

    conn = mgclient.connect(host=host, port=port)
    cursor = conn.cursor()
    cursor.execute(
        "MATCH (child)-[:IS_A]->(parent) "
        "RETURN child.name, parent.name"
    )
    edges = [(row[0], row[1]) for row in cursor.fetchall()]
    conn.close()
    logger.info("Loaded %d IS_A edges from Memgraph", len(edges))
    return edges


def get_existing_concepts(conn: psycopg.Connection) -> set[str]:
    """Return the set of concept names in ontology_concept."""
    cur = conn.execute("SELECT name FROM ontology_concept")
    return {row[0] for row in cur.fetchall()}


def apply_hierarchy(
    conn: psycopg.Connection,
    edges: list[tuple[str, str]],
    dry_run: bool,
) -> int:
    """Set parent_name on ontology_concept rows. Returns count updated."""
    existing = get_existing_concepts(conn)
    updated = 0

    for child, parent in edges:
        if child not in existing:
            logger.debug("Skipping %r — not in ontology_concept", child)
            continue
        if parent not in existing:
            logger.debug("Skipping %r IS_A %r — parent not in ontology_concept", child, parent)
            continue

        if dry_run:
            logger.info("[DRY RUN] %s IS_A %s", child, parent)
            updated += 1
            continue

        cur = conn.execute(
            "UPDATE ontology_concept SET parent_name = %s "
            "WHERE name = %s AND (parent_name IS NULL OR parent_name != %s)",
            (parent, child, parent),
        )
        if cur.rowcount:
            logger.info("Set %s IS_A %s", child, parent)
            updated += cur.rowcount

    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--synthetic", action="store_true",
                        help="Use hardcoded biomedical hierarchy instead of Memgraph")
    parser.add_argument("--memgraph-host", default="127.0.0.1")
    parser.add_argument("--memgraph-port", type=int, default=7687)
    args = parser.parse_args()

    if args.synthetic:
        edges = SYNTHETIC_HIERARCHY
        logger.info("Using synthetic hierarchy (%d edges)", len(edges))
    else:
        edges = load_hierarchy_from_memgraph(args.memgraph_host, args.memgraph_port)
        if not edges:
            logger.warning("No IS_A edges found in Memgraph; use --synthetic for testing")
            return

    with psycopg.connect(args.db_url) as conn:
        updated = apply_hierarchy(conn, edges, args.dry_run)

        if not args.dry_run:
            conn.commit()
            logger.info("Updated %d ontology_concept rows with parent edges", updated)
        else:
            logger.info("[DRY RUN] Would update %d rows", updated)


if __name__ == "__main__":
    main()
