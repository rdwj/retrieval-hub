"""Query the VA CPG ingested source and print the top hits.

Runs the high-level ``retrieval_hub.retrieval.api.query`` function against the
catalog entry created by ``ingest_va_cpg.py``. This is the same code path a
future MCP tool will call -- the CLI is a thin wrapper.

Usage:

    python scripts/query_va_cpg_demo.py "what does the VA CPG recommend for PTSD treatment"
    python scripts/query_va_cpg_demo.py "opioid prescribing guidelines" --top-k 3
    python scripts/query_va_cpg_demo.py "diabetes management in veterans" --top-k 10
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.retrieval.api import (
    SourceNotFoundError,
    SourceNotQueryableError,
    UnsupportedFamilyError,
    query,
)

SOURCE_SLUG = "va-cpg-clinical-guidelines"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query_text", help="Query string to run against the VA CPG source")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--source",
        default=SOURCE_SLUG,
        help=f"Source slug to query (default: {SOURCE_SLUG})",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=(f"SQLAlchemy URL for the catalog database. Default: {DEFAULT_DB_URL}"),
    )
    parser.add_argument(
        "--vectors-db-url",
        default=DEFAULT_VECTORS_DB_URL,
        help=(f"SQLAlchemy URL for the vectors database. Default: {DEFAULT_VECTORS_DB_URL}"),
    )
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    session_factory = make_session_factory(create_db_engine(args.db_url))

    started = time.monotonic()
    with session_factory() as session:
        try:
            results = query(
                args.source,
                args.query_text,
                session=session,
                top_k=args.top_k,
                vectors_db_url=args.vectors_db_url,
            )
        except SourceNotFoundError:
            print(
                f"ERROR: no source with slug {args.source!r} in the catalog.\n"
                f"Did you run scripts/ingest_va_cpg.py first?",
                file=sys.stderr,
            )
            return 2
        except SourceNotQueryableError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        except UnsupportedFamilyError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    elapsed = time.monotonic() - started

    print()
    print("=" * 72)
    print(f"Query: {args.query_text}")
    print(f"Source: {args.source}  |  top_k={args.top_k}  |  {elapsed * 1000:.0f}ms")
    print("=" * 72)

    if not results:
        print("  (no results)")
        return 0

    for rank, hit in enumerate(results, start=1):
        snippet = hit.text.strip().replace("\n", " ")
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        section = f"  {hit.doc_section}" if hit.doc_section else ""
        print(f"\n[{rank}] score={hit.score:.3f}")
        print(f"    {hit.doc_title}{section}")
        print(f"    {hit.doc_url}")
        print(f"    {snippet}")
        print(
            f"    lineage: pidx={hit.physical_index_id} recipe_v={hit.recipe_version} "
            f"req={hit.request_id}"
        )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
