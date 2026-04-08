"""Query the step 4 ingested source and print the top hits.

Runs the high-level ``retrieval_hub.retrieval.api.query`` function against the
catalog entry created by ``step4_ingest_rh_aai_docs.py``. This is the same
code path a future MCP tool will call — the CLI is a thin wrapper.

Usage:

    python scripts/step4_query_demo.py "how do I enable OAuth on Llama Stack"
    python scripts/step4_query_demo.py "what metrics does Ragas compute" --top-k 3
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

SOURCE_SLUG = "rh-aai-llamastack-guide"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query_text", help="Query string to run against the source")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--source",
        default=SOURCE_SLUG,
        help=f"Source slug to query (default: {SOURCE_SLUG})",
    )
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    session_factory = make_session_factory(create_db_engine())

    started = time.monotonic()
    with session_factory() as session:
        try:
            results = query(
                args.source,
                args.query_text,
                session=session,
                top_k=args.top_k,
            )
        except SourceNotFoundError:
            print(
                f"ERROR: no source with slug {args.source!r} in the catalog.\n"
                f"Did you run scripts/step4_ingest_rh_aai_docs.py first?",
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
        section = f"§{hit.doc_section}" if hit.doc_section else ""
        print(f"\n[{rank}] score={hit.score:.3f}")
        print(f"    {hit.doc_title} {section}")
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
