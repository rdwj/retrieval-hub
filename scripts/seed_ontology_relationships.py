#!/usr/bin/env python3
"""Seed cross-concept relationships into the ontology_relationship table.

Reads edge types from Memgraph and maps them to (source_concept, verb,
target_concept) triples.  When Memgraph is unavailable, use --synthetic to
seed from known Hetionet and FHIR edge types.

Usage:
    python scripts/seed_ontology_relationships.py [--db-url URL] [--dry-run]
    python scripts/seed_ontology_relationships.py --synthetic [--db-url URL] [--dry-run]
    python scripts/seed_ontology_relationships.py \\
        --memgraph-host HOST --memgraph-port PORT [--db-url URL]
"""

from __future__ import annotations

import argparse
import logging

import psycopg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = (
    "postgresql://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)

# (source_concept, relationship, target_concept, source_slug | None)
SYNTHETIC_RELATIONSHIPS: list[tuple[str, str, str, str | None]] = [
    # -- Hetionet-style (canonical, no source) -------------------------
    ("Compound", "treats", "Disease", None),
    ("Compound", "palliates", "Disease", None),
    ("Compound", "causes", "Side Effect", None),
    ("Compound", "binds", "Gene", None),
    ("Compound", "resembles", "Compound", None),
    ("Disease", "associates", "Gene", None),
    ("Disease", "presents", "Symptom", None),
    ("Disease", "localizes", "Anatomy", None),
    ("Disease", "resembles", "Disease", None),
    ("Gene", "participates", "Biological Process", None),
    ("Gene", "interacts", "Gene", None),
    ("Gene", "covaries", "Gene", None),
    ("Anatomy", "expresses", "Gene", None),
    ("Anatomy", "downregulates", "Gene", None),
    ("Anatomy", "upregulates", "Gene", None),
    ("Pharmacologic Class", "includes", "Compound", None),
    # -- FHIR-style (source-specific) ----------------------------------
    ("Patient", "diagnosed_with", "Condition", "fhir"),
    ("Encounter", "has_subject", "Patient", "fhir"),
    ("Observation", "part_of", "Encounter", "fhir"),
    ("Procedure", "performed_on", "Patient", "fhir"),
    ("Condition", "evidenced_by", "Observation", "fhir"),
]


def load_relationships_from_memgraph(
    host: str, port: int
) -> list[tuple[str, str, str]]:
    """Read edge types from Memgraph, parse XXX___verb___YYY triples."""
    import mgclient

    conn = mgclient.connect(host=host, port=port)
    cursor = conn.cursor()
    cursor.execute(
        "MATCH ()-[r]->() "
        "RETURN DISTINCT type(r) AS edge_type"
    )
    rows = cursor.fetchall()
    conn.close()

    triples: list[tuple[str, str, str]] = []
    for (edge_type,) in rows:
        parts = edge_type.split("___")
        if len(parts) != 3:
            logger.debug(
                "Skipping edge type %r — does not match "
                "XXX___verb___YYY pattern",
                edge_type,
            )
            continue
        src, verb, tgt = parts
        verb = verb.replace("_", " ").lower()
        triples.append((src, verb, tgt))

    logger.info(
        "Loaded %d relationship types from Memgraph", len(triples)
    )
    return triples


def get_existing_concepts(conn: psycopg.Connection) -> set[str]:
    """Return the set of concept names in ontology_concept."""
    cur = conn.execute("SELECT name FROM ontology_concept")
    return {row[0] for row in cur.fetchall()}


def insert_relationships(
    conn: psycopg.Connection,
    relationships: list[tuple[str, str, str, str | None]],
    dry_run: bool,
) -> int:
    """Insert relationship rows. Returns count of rows inserted."""
    existing = get_existing_concepts(conn)
    inserted = 0

    for src, verb, tgt, source_slug in relationships:
        if src not in existing:
            logger.debug(
                "Skipping %r -> %r -> %r — source concept "
                "not in ontology_concept",
                src, verb, tgt,
            )
            continue
        if tgt not in existing:
            logger.debug(
                "Skipping %r -> %r -> %r — target concept "
                "not in ontology_concept",
                src, verb, tgt,
            )
            continue

        if dry_run:
            logger.info(
                "[DRY RUN] %s -[%s]-> %s (source=%s)",
                src, verb, tgt, source_slug,
            )
            inserted += 1
            continue

        if source_slug is None:
            cur = conn.execute(
                "INSERT INTO ontology_relationship "
                "    (source_concept, relationship,"
                "     target_concept, source_slug, created_at)"
                " VALUES (%s, %s, %s, NULL, NOW()) "
                "ON CONFLICT "
                "    (source_concept, relationship,"
                "     target_concept) "
                "    WHERE source_slug IS NULL "
                "DO NOTHING",
                (src, verb, tgt),
            )
        else:
            cur = conn.execute(
                "INSERT INTO ontology_relationship "
                "    (source_concept, relationship,"
                "     target_concept, source_slug, created_at)"
                " VALUES (%s, %s, %s, %s, NOW()) "
                "ON CONFLICT ON CONSTRAINT "
                "    uq_ontology_rel_src_rel_tgt_slug "
                "DO NOTHING",
                (src, verb, tgt, source_slug),
            )
        if cur.rowcount:
            logger.info(
                "Inserted %s -[%s]-> %s (source=%s)",
                src, verb, tgt, source_slug,
            )
            inserted += cur.rowcount

    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use hardcoded Hetionet/FHIR relationships "
        "instead of Memgraph",
    )
    parser.add_argument("--memgraph-host", default="127.0.0.1")
    parser.add_argument(
        "--memgraph-port", type=int, default=7687
    )
    args = parser.parse_args()

    if args.synthetic:
        rels = SYNTHETIC_RELATIONSHIPS
        logger.info(
            "Using synthetic relationships (%d edges)", len(rels)
        )
    else:
        triples = load_relationships_from_memgraph(
            args.memgraph_host, args.memgraph_port
        )
        if not triples:
            logger.warning(
                "No relationship edges found in Memgraph; "
                "use --synthetic for testing"
            )
            return
        # Memgraph triples have no source_slug
        rels = [(s, v, t, None) for s, v, t in triples]

    with psycopg.connect(args.db_url) as conn:
        count = insert_relationships(conn, rels, args.dry_run)

        if not args.dry_run:
            conn.commit()
            logger.info(
                "Inserted %d ontology_relationship rows", count
            )
        else:
            logger.info(
                "[DRY RUN] Would insert %d rows", count
            )


if __name__ == "__main__":
    main()
