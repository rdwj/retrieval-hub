"""Query a code source and print the top hits, or fetch a file live from GitHub.

Runs the high-level ``retrieval_hub.retrieval.api.query`` function against a
code source in the catalog.  This is the same code path the MCP ``retrieve``
tool uses.  The ``--file`` flag exercises the live GitHub file-fetch path
(bypasses vector search).

Usage:

    # Vector search
    python scripts/query_code_demo.py "how does the retrieval API work"
    python scripts/query_code_demo.py "AST chunking algorithm" --top-k 3

    # Live file fetch from GitHub
    python scripts/query_code_demo.py --file src/retrieval_hub/retrieval/api.py
    python scripts/query_code_demo.py --file README.md --ref v0.1.0
"""

from __future__ import annotations

import argparse
import base64
import logging
import sys
import time

import httpx

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
from retrieval_hub.retrieval.api import (
    SourceNotFoundError,
    SourceNotQueryableError,
    UnsupportedFamilyError,
    query,
)

SOURCE_SLUG = "retrieval-hub-code"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)


def _fetch_github_file(owner_repo: str, file_path: str, ref: str | None) -> str:
    """Fetch a file from GitHub's public REST API and return its content."""
    url = f"https://api.github.com/repos/{owner_repo}/contents/{file_path}"
    params: dict[str, str] = {}
    if ref:
        params["ref"] = ref

    resp = httpx.get(
        url, params=params, headers={"Accept": "application/vnd.github.v3+json"},
    )

    remaining = resp.headers.get("x-ratelimit-remaining")
    limit = resp.headers.get("x-ratelimit-limit")
    if remaining is not None:
        print(f"  GitHub rate limit: {remaining}/{limit} remaining")

    if resp.status_code == 404:
        print(
            f"ERROR: file {file_path!r} not found in {owner_repo}"
            + (f" at ref {ref!r}" if ref else ""),
            file=sys.stderr,
        )
        return ""
    if resp.status_code != 200:
        print(f"ERROR: GitHub API returned {resp.status_code}", file=sys.stderr)
        return ""

    data = resp.json()
    return base64.b64decode(data["content"]).decode("utf-8")


def _resolve_github_repo(source_slug: str, session) -> str | None:
    """Read github_repo from the source's active recipe via the physical index."""
    source = session.query(Source).filter(Source.slug == source_slug).one_or_none()
    if not source or not source.active_physical_index_id:
        return None
    pi = (
        session.query(PhysicalIndex)
        .filter(PhysicalIndex.id == source.active_physical_index_id)
        .one_or_none()
    )
    if not pi or not pi.recipe_version_id:
        return None
    rv = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.id == pi.recipe_version_id)
        .one_or_none()
    )
    if rv and rv.content:
        return rv.content.get("github_repo")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "query_text", nargs="?", default=None,
        help="Query string to run against the code source (omit when using --file)",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--source", default=SOURCE_SLUG,
        help=f"Source slug to query (default: {SOURCE_SLUG})",
    )
    parser.add_argument(
        "--file", dest="file_path", default=None,
        help="Fetch a specific file from GitHub instead of running vector search",
    )
    parser.add_argument(
        "--ref", default=None,
        help="Git ref (branch, tag, SHA) for --file fetch (default: repo default branch)",
    )
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--vectors-db-url", default=DEFAULT_VECTORS_DB_URL)
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()

    if not args.query_text and not args.file_path:
        parser.error("provide a query string or --file <path>")

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    session_factory = make_session_factory(create_db_engine(args.db_url))

    if args.file_path:
        return _run_file_fetch(args, session_factory)
    return _run_vector_query(args, session_factory)


def _run_file_fetch(args, session_factory) -> int:
    """Fetch a file from GitHub using the source's github_repo recipe field."""
    with session_factory() as session:
        github_repo = _resolve_github_repo(args.source, session)

    if not github_repo:
        print(
            f"ERROR: source {args.source!r} has no github_repo in its recipe.",
            file=sys.stderr,
        )
        return 2

    started = time.monotonic()
    content = _fetch_github_file(github_repo, args.file_path, args.ref)
    elapsed = time.monotonic() - started

    if not content:
        return 2

    print()
    print("=" * 72)
    print(f"File: {args.file_path}")
    ref_label = args.ref or "(default branch)"
    print(f"Repo: {github_repo}  |  ref={ref_label}  |  {elapsed * 1000:.0f}ms")
    print("=" * 72)
    print()
    print(content)
    return 0


def _run_vector_query(args, session_factory) -> int:
    """Run a vector search query against the code source."""
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
                f"Did you run scripts/ingest_code_repo.py first?",
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
