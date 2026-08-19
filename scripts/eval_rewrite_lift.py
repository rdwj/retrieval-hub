"""Evaluate whether query rewriting improves retrieval on the VA CPG source.

Compares raw vs. rewritten retrieval using ground-truth metrics (hit_rate,
MRR, mean_score) against the Q/A evaluation dataset.

Usage:

    python scripts/eval_rewrite_lift.py

    # Override LLM endpoint or database URLs:
    python scripts/eval_rewrite_lift.py \
        --llm-url https://my-llm/v1/chat/completions \
        --db-url postgresql+psycopg://... \
        --vectors-db-url postgresql+psycopg://...
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.models import Source
from retrieval_hub.retrieval.api import RetrievalResult, query
from retrieval_hub.rewriter.llm import LlmClient
from retrieval_hub.rewriter.service import RewriterService
from retrieval_hub.schemas.rewriter import RewriterMetadata
from retrieval_hub.schemas.semantic import SemanticContext

logger = logging.getLogger("eval_rewrite_lift")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
QA_DATASET_PATH = Path("eval/autorag/qa_dataset_draft.json")
OUTPUT_DIR = Path("eval/rewrite_lift")

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
)
DEFAULT_LLM_URL = (
    "https://gpt-oss-120b-direct-gpt-oss-120b-model"
    ".apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com"
    "/v1/chat/completions"
)
DEFAULT_LLM_MODEL = "/mnt/models"

TOP_K = 5
EVAL_SEED = 42
TARGET_QUERY_COUNT = 30

SLUG_TO_KEYWORDS: dict[str, list[str]] = {
    "copd": ["obstructive pulmonary"],
    "diabetes": ["diabetes"],
    "headache": ["headache"],
    "hypertension": ["hypertension"],
    "insomnia-osa": ["insomnia", "sleep apnea"],
    "lower-back-pain": ["back pain"],
    "mdd": ["depressive disorder"],
    "mtbi": ["brain injury"],
    "obesity": ["obesity", "overweight"],
    "opioids": ["opioid"],
    "osteoarthritis": ["osteoarthritis"],
    "pregnancy": ["pregnancy"],
    "ptsd": ["ptsd"],
    "stroke": ["stroke"],
    "sud": ["substance use"],
    "suicide-risk": ["suicide"],
    "tobacco": ["tobacco"],
}


@dataclass
class QueryMetrics:
    query_id: str
    question: str
    language_register: str
    cpg_slug: str
    raw_hit: bool = False
    raw_mrr: float = 0.0
    raw_mean_score: float = 0.0
    rewrite_hit: bool = False
    rewrite_mrr: float = 0.0
    rewrite_mean_score: float = 0.0
    rewrites_used: int = 0
    rewrite_texts: list[str] = field(default_factory=list)


def _chunk_matches_source(result: RetrievalResult, cpg_slug: str) -> bool:
    """Check if a retrieved chunk comes from the expected CPG."""
    keywords = SLUG_TO_KEYWORDS.get(cpg_slug)
    if not keywords:
        return False
    title_lower = result.doc_title.lower()
    return any(kw in title_lower for kw in keywords)


def _compute_hit_mrr(
    results: list[RetrievalResult], cpg_slug: str
) -> tuple[bool, float]:
    """Return (hit@k, mrr@k) for a set of retrieval results."""
    for i, r in enumerate(results):
        if _chunk_matches_source(r, cpg_slug):
            return True, 1.0 / (i + 1)
    return False, 0.0


def _mean_score(results: list[RetrievalResult]) -> float:
    if not results:
        return 0.0
    return sum(r.score for r in results) / len(results)


def _deduplicate_results(
    all_results: list[RetrievalResult],
) -> list[RetrievalResult]:
    """Deduplicate by text content, keep highest-scoring version."""
    seen: dict[str, RetrievalResult] = {}
    for r in all_results:
        existing = seen.get(r.text)
        if existing is None or r.score > existing.score:
            seen[r.text] = r
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)


def _load_eval_queries(qa_path: Path) -> list[dict]:
    """Load and select the evaluation query set."""
    data = json.loads(qa_path.read_text(encoding="utf-8"))
    questions = data["questions"]

    lay = [q for q in questions if q["language_register"] == "lay"]
    clinical = [q for q in questions if q["language_register"] == "clinical"]

    rng = random.Random(EVAL_SEED)
    clinical_needed = max(0, TARGET_QUERY_COUNT - len(lay))
    clinical_sample = rng.sample(clinical, min(clinical_needed, len(clinical)))

    selected = lay + clinical_sample
    rng.shuffle(selected)

    unknown_slugs = {q["cpg_slug"] for q in selected} - set(SLUG_TO_KEYWORDS)
    if unknown_slugs:
        logger.warning(
            "cpg_slugs not in SLUG_TO_KEYWORDS (will never match): %s",
            unknown_slugs,
        )

    logger.info(
        "eval query set: %d total (%d lay, %d clinical)",
        len(selected),
        len(lay),
        len(clinical_sample),
    )
    return selected


async def _evaluate_single_query(
    q: dict,
    *,
    session: Session,
    rewriter: RewriterService,
    metadata: RewriterMetadata,
    vectors_db_url: str | None,
    semantic_context: SemanticContext | None = None,
) -> QueryMetrics:
    """Run raw and rewritten retrieval for a single query, compute metrics."""
    metrics = QueryMetrics(
        query_id=q["id"],
        question=q["question"],
        language_register=q["language_register"],
        cpg_slug=q["cpg_slug"],
    )

    raw_results = query(
        SOURCE_SLUG,
        q["question"],
        session=session,
        top_k=TOP_K,
        vectors_db_url=vectors_db_url,
    )
    metrics.raw_hit, metrics.raw_mrr = _compute_hit_mrr(raw_results, q["cpg_slug"])
    metrics.raw_mean_score = _mean_score(raw_results)

    rewrite_result = await rewriter.rewrite(
        q["question"], metadata, semantic_context=semantic_context
    )
    metrics.rewrites_used = len(rewrite_result.queries)
    metrics.rewrite_texts = [rq.text for rq in rewrite_result.queries]

    all_rewrite_hits: list[RetrievalResult] = []
    for rq in rewrite_result.queries:
        hits = query(
            SOURCE_SLUG,
            rq.text,
            session=session,
            top_k=TOP_K,
            vectors_db_url=vectors_db_url,
        )
        all_rewrite_hits.extend(hits)

    deduped = _deduplicate_results(all_rewrite_hits)[:TOP_K]
    metrics.rewrite_hit, metrics.rewrite_mrr = _compute_hit_mrr(
        deduped, q["cpg_slug"]
    )
    metrics.rewrite_mean_score = _mean_score(deduped)

    return metrics


def _write_csv(results: list[QueryMetrics], path: Path) -> None:
    fieldnames = [
        "query_id",
        "language_register",
        "cpg_slug",
        "question",
        "raw_hit",
        "raw_mrr",
        "raw_mean_score",
        "rewrite_hit",
        "rewrite_mrr",
        "rewrite_mean_score",
        "rewrites_used",
        "rewrite_texts",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in results:
            writer.writerow(
                {
                    "query_id": m.query_id,
                    "language_register": m.language_register,
                    "cpg_slug": m.cpg_slug,
                    "question": m.question,
                    "raw_hit": int(m.raw_hit),
                    "raw_mrr": f"{m.raw_mrr:.4f}",
                    "raw_mean_score": f"{m.raw_mean_score:.4f}",
                    "rewrite_hit": int(m.rewrite_hit),
                    "rewrite_mrr": f"{m.rewrite_mrr:.4f}",
                    "rewrite_mean_score": f"{m.rewrite_mean_score:.4f}",
                    "rewrites_used": m.rewrites_used,
                    "rewrite_texts": json.dumps(m.rewrite_texts),
                }
            )


def _compute_summary(results: list[QueryMetrics]) -> dict:
    """Compute aggregate metrics and deltas."""

    def _agg(items: list[QueryMetrics]) -> dict:
        n = len(items)
        if n == 0:
            return {}
        return {
            "n": n,
            "raw_hit_rate": sum(m.raw_hit for m in items) / n,
            "rewrite_hit_rate": sum(m.rewrite_hit for m in items) / n,
            "raw_mrr": sum(m.raw_mrr for m in items) / n,
            "rewrite_mrr": sum(m.rewrite_mrr for m in items) / n,
            "raw_mean_score": sum(m.raw_mean_score for m in items) / n,
            "rewrite_mean_score": sum(m.rewrite_mean_score for m in items) / n,
            "hit_rate_delta": (
                sum(m.rewrite_hit for m in items) / n
                - sum(m.raw_hit for m in items) / n
            ),
            "mrr_delta": (
                sum(m.rewrite_mrr for m in items) / n
                - sum(m.raw_mrr for m in items) / n
            ),
            "mean_score_delta": (
                sum(m.rewrite_mean_score for m in items) / n
                - sum(m.raw_mean_score for m in items) / n
            ),
        }

    lay = [m for m in results if m.language_register == "lay"]
    clinical = [m for m in results if m.language_register == "clinical"]

    improved = [m for m in results if m.rewrite_hit and not m.raw_hit]
    regressed = [m for m in results if m.raw_hit and not m.rewrite_hit]

    return {
        "overall": _agg(results),
        "by_register": {
            "lay": _agg(lay),
            "clinical": _agg(clinical),
        },
        "improved_queries": [m.query_id for m in improved],
        "regressed_queries": [m.query_id for m in regressed],
    }


def _print_summary(summary: dict, wall_time: float) -> None:
    print()
    print("=" * 72)
    print("Rewrite Lift Evaluation Results")
    print("=" * 72)

    for label, data in [
        ("Overall", summary["overall"]),
        ("Lay register", summary["by_register"]["lay"]),
        ("Clinical register", summary["by_register"]["clinical"]),
    ]:
        if not data:
            continue
        print(f"\n  {label} (n={data['n']}):")
        print(f"    {'Metric':<20} {'Raw':>8} {'Rewrite':>8} {'Delta':>8}")
        print(f"    {'-'*20} {'-'*8} {'-'*8} {'-'*8}")
        print(
            f"    {'hit_rate@5':<20} {data['raw_hit_rate']:>8.3f} "
            f"{data['rewrite_hit_rate']:>8.3f} {data['hit_rate_delta']:>+8.3f}"
        )
        print(
            f"    {'MRR@5':<20} {data['raw_mrr']:>8.3f} "
            f"{data['rewrite_mrr']:>8.3f} {data['mrr_delta']:>+8.3f}"
        )
        print(
            f"    {'mean_score':<20} {data['raw_mean_score']:>8.3f} "
            f"{data['rewrite_mean_score']:>8.3f} {data['mean_score_delta']:>+8.3f}"
        )

    improved = summary.get("improved_queries", [])
    regressed = summary.get("regressed_queries", [])
    if improved:
        print(f"\n  Improved (gained hit): {', '.join(improved)}")
    if regressed:
        print(f"  Regressed (lost hit):  {', '.join(regressed)}")

    print(f"\n  Wall time: {wall_time:.1f}s")
    print("=" * 72)


async def _run_eval(
    db_url: str,
    vectors_db_url: str,
    llm_url: str,
    llm_model: str,
) -> int:
    wall_start = time.monotonic()

    eval_queries = _load_eval_queries(QA_DATASET_PATH)

    session_factory = make_session_factory(create_db_engine(db_url))

    with session_factory() as session:
        source = (
            session.query(Source).filter(Source.slug == SOURCE_SLUG).one_or_none()
        )
        if source is None:
            logger.error("Source %r not found in catalog", SOURCE_SLUG)
            return 1
        if source.rewriter_metadata is None:
            logger.error("Source %r has no rewriter metadata", SOURCE_SLUG)
            return 1
        metadata = RewriterMetadata.model_validate(source.rewriter_metadata)

        semantic = None
        if source.semantic_context:
            semantic = SemanticContext.model_validate(source.semantic_context)

    if not metadata.enabled:
        logger.error("Rewriter is disabled for source %r", SOURCE_SLUG)
        return 1

    logger.info(
        "rewriter metadata: %d vocab mappings, %d sample queries, max_rewrites=%d",
        len(metadata.vocabulary_mappings),
        len(metadata.sample_queries),
        metadata.max_rewrites,
    )

    async with LlmClient(base_url=llm_url, model=llm_model) as llm:
        rewriter = RewriterService(llm)
        all_metrics: list[QueryMetrics] = []

        for i, q in enumerate(eval_queries):
            logger.info(
                "[%d/%d] %s (%s, %s)",
                i + 1,
                len(eval_queries),
                q["id"],
                q["language_register"],
                q["cpg_slug"],
            )

            try:
                with session_factory() as session:
                    m = await _evaluate_single_query(
                        q,
                        session=session,
                        rewriter=rewriter,
                        metadata=metadata,
                        vectors_db_url=vectors_db_url,
                        semantic_context=semantic,
                    )
                all_metrics.append(m)

                status = ""
                if m.rewrite_hit and not m.raw_hit:
                    status = " [IMPROVED]"
                elif m.raw_hit and not m.rewrite_hit:
                    status = " [REGRESSED]"
                logger.info(
                    "  raw_hit=%s mrr=%.3f | rewrite_hit=%s mrr=%.3f | "
                    "rewrites=%d%s",
                    m.raw_hit,
                    m.raw_mrr,
                    m.rewrite_hit,
                    m.rewrite_mrr,
                    m.rewrites_used,
                    status,
                )
            except Exception:
                logger.exception("failed on query %s", q["id"])
                continue

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "results.csv"
    _write_csv(all_metrics, csv_path)
    logger.info("wrote %s", csv_path)

    summary = _compute_summary(all_metrics)
    summary["metadata"] = {
        "date": time.strftime("%Y-%m-%d"),
        "source_slug": SOURCE_SLUG,
        "llm_model": llm_model,
        "llm_url": llm_url,
        "top_k": TOP_K,
        "eval_seed": EVAL_SEED,
        "query_count": len(all_metrics),
    }

    summary_path = OUTPUT_DIR / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("wrote %s", summary_path)

    wall_time = time.monotonic() - wall_start
    _print_summary(summary, wall_time)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy URL for the catalog database. Default: {DEFAULT_DB_URL}",
    )
    parser.add_argument(
        "--vectors-db-url",
        default=DEFAULT_VECTORS_DB_URL,
        help=f"SQLAlchemy URL for the vectors database. Default: {DEFAULT_VECTORS_DB_URL}",
    )
    parser.add_argument(
        "--llm-url",
        default=DEFAULT_LLM_URL,
        help="OpenAI-compatible LLM endpoint URL for query rewriting.",
    )
    parser.add_argument(
        "--llm-model",
        default=DEFAULT_LLM_MODEL,
        help=f"Model identifier for the LLM. Default: {DEFAULT_LLM_MODEL}",
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

    return asyncio.run(
        _run_eval(args.db_url, args.vectors_db_url, args.llm_url, args.llm_model)
    )


if __name__ == "__main__":
    sys.exit(main())
