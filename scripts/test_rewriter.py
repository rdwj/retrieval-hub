"""Smoke-test the query rewriter against a live LLM endpoint.

Exercises the full RewriterService pipeline -- template loading, metadata
formatting, LLM call, structured-response parsing -- using hardcoded VA CPG
metadata so no database is required.

Usage:

    python scripts/test_rewriter.py
    python scripts/test_rewriter.py --query "chest pain when exercising"
    python scripts/test_rewriter.py --max-rewrites 3 --log-level DEBUG
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from retrieval_hub.rewriter import LlmClient, LlmError, RewriterService
from retrieval_hub.schemas.rewriter import (
    RewriterMetadata,
    SampleQueryExample,
    VocabularyMapping,
)

DEFAULT_URL = (
    "https://gpt-oss-120b-direct-gpt-oss-120b-model"
    ".apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1/chat/completions"
)
DEFAULT_MODEL = "/mnt/models"
DEFAULT_QUERY = "high blood sugar after a meal"
DEFAULT_MAX_REWRITES = 5

SEPARATOR = "═" * 65

logger = logging.getLogger("test_rewriter")


def _build_metadata(*, max_rewrites: int) -> RewriterMetadata:
    """Hardcoded VA CPG metadata subset for smoke-testing."""
    return RewriterMetadata(
        enabled=True,
        max_rewrites=max_rewrites,
        domain_notes=(
            "VA Clinical Practice Guidelines (CPGs) are evidence-based "
            "recommendations for management of clinical conditions common in "
            "the veteran population. Content is structured around clinical "
            "questions and recommendation statements with evidence grades."
        ),
        vocabulary_mappings=[
            VocabularyMapping(lay_term="high blood sugar", canonical_term="hyperglycemia"),
            VocabularyMapping(
                lay_term="low blood sugar", canonical_term="hypoglycemia"
            ),
            VocabularyMapping(
                lay_term="sugar diabetes", canonical_term="type 2 diabetes mellitus"
            ),
            VocabularyMapping(
                lay_term="blood sugar test", canonical_term="hemoglobin A1c measurement"
            ),
            VocabularyMapping(
                lay_term="high blood sugar after eating",
                canonical_term="postprandial hyperglycemia",
            ),
            VocabularyMapping(
                lay_term="high blood pressure", canonical_term="hypertension"
            ),
            VocabularyMapping(
                lay_term="blood pressure medicine",
                canonical_term="antihypertensive therapy",
            ),
            VocabularyMapping(
                lay_term="heart attack", canonical_term="myocardial infarction"
            ),
            VocabularyMapping(lay_term="chest pain", canonical_term="angina pectoris"),
            VocabularyMapping(lay_term="PTSD", canonical_term="post-traumatic stress disorder"),
            VocabularyMapping(
                lay_term="depression", canonical_term="major depressive disorder"
            ),
            VocabularyMapping(lay_term="chronic pain", canonical_term="chronic pain syndrome"),
            VocabularyMapping(lay_term="back pain", canonical_term="chronic low back pain"),
        ],
        sample_queries=[
            SampleQueryExample(
                raw="high blood sugar after a meal",
                good_rewrites=[
                    "postprandial hyperglycemia management guidelines",
                    "glycemic control recommendations following meals VA CPG",
                ],
            ),
            SampleQueryExample(
                raw="what blood pressure medicine should I take",
                good_rewrites=[
                    "antihypertensive therapy selection recommendations",
                    "first-line pharmacotherapy for hypertension VA CPG",
                ],
            ),
            SampleQueryExample(
                raw="back pain that won't go away",
                good_rewrites=[
                    "chronic low back pain management algorithm",
                    "non-pharmacological treatment chronic low back pain VA CPG",
                ],
            ),
        ],
    )


async def _run(
    query: str,
    url: str,
    model: str,
    max_rewrites: int,
) -> int:
    metadata = _build_metadata(max_rewrites=max_rewrites)

    async with LlmClient(base_url=url, model=model) as llm:
        service = RewriterService(llm)

        try:
            result = await service.rewrite(
                query, metadata, max_rewrites=max_rewrites
            )
        except LlmError as exc:
            print(f"\nERROR: LLM call failed: {exc}", file=sys.stderr)
            return 1

    print()
    print(SEPARATOR)
    print("Query Rewriter Smoke Test")
    print(SEPARATOR)
    print(f"Raw query     : {result.raw_query}")
    print(f"LLM endpoint  : {url}")
    print(f"Model         : {model}")
    print(f"Max rewrites  : {max_rewrites}")
    print(f"Template ver  : {result.template_version}")
    print(f"Request ID    : {result.request_id}")
    print(SEPARATOR)

    for i, rq in enumerate(result.queries, 1):
        print(f"\nRewrite {i} (confidence: {rq.confidence:.2f}):")
        print(f"  Text      : {rq.text}")
        print(f"  Intent    : {rq.intent}")
        print(f"  Rationale : {rq.rationale}")

    print()
    print(SEPARATOR)
    count = len(result.queries)
    print(f"{count} rewrite{'s' if count != 1 else ''} generated successfully")
    print(SEPARATOR)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the query rewriter against a live LLM endpoint.",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"Raw query to rewrite (default: {DEFAULT_QUERY!r})",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="LLM endpoint URL",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--max-rewrites",
        type=int,
        default=DEFAULT_MAX_REWRITES,
        help=f"Maximum rewrites to request (default: {DEFAULT_MAX_REWRITES})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    try:
        return asyncio.run(_run(args.query, args.url, args.model, args.max_rewrites))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
