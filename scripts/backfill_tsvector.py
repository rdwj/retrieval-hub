"""Backfill tsvector column on all pgvector index tables.

Adds the ``chunk_tsvector`` column, populates it from ``chunk_text``,
and creates a GIN index. All operations are idempotent -- safe to re-run.

Usage::

    python scripts/backfill_tsvector.py [--db-url URL]

Defaults to the cluster vectors DB via port-forward at 127.0.0.1:5433.
"""

from __future__ import annotations

import argparse
import logging
import sys

import psycopg

logger = logging.getLogger(__name__)

DEFAULT_DB_URL = (
    "postgresql://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)


def _discover_index_tables(conn: psycopg.Connection) -> list[str]:
    """Return all ``idx_*`` table names in the public schema."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename LIKE 'idx_%' "
            "ORDER BY tablename"
        )
        return [row[0] for row in cur.fetchall()]


def _backfill_table(conn: psycopg.Connection, table: str) -> int:
    """Add tsvector column, populate, and create GIN index. Returns rows updated."""
    with conn.cursor() as cur:
        cur.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN IF NOT EXISTS chunk_tsvector TSVECTOR"
        )

        cur.execute(
            f"UPDATE {table} "
            f"SET chunk_tsvector = to_tsvector('english', chunk_text) "
            f"WHERE chunk_tsvector IS NULL"
        )
        rows_updated = cur.rowcount

        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_tsvector_idx "
            f"ON {table} USING GIN (chunk_tsvector)"
        )

    conn.commit()
    return rows_updated


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help="PostgreSQL connection URL (default: local port-forward)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List tables that would be backfilled without making changes",
    )
    args = parser.parse_args()

    with psycopg.connect(args.db_url) as conn:
        tables = _discover_index_tables(conn)
        logger.info("Found %d index tables", len(tables))

        if args.dry_run:
            for t in tables:
                print(f"  {t}")
            print(f"\nDry run: {len(tables)} tables would be backfilled.")
            sys.exit(0)

        total_rows = 0
        for table in tables:
            rows = _backfill_table(conn, table)
            logger.info("  %s: %d rows updated", table, rows)
            total_rows += rows

        logger.info(
            "Backfill complete: %d tables, %d total rows updated",
            len(tables),
            total_rows,
        )


if __name__ == "__main__":
    main()
