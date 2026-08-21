"""End-to-end answer-quality eval for the VA CPG source.

Three-stage pipeline with per-stage caching:
  1. Retrieve — raw + rewritten retrieval (cached if config unchanged)
  2. Generate — produce answers from retrieved context (cached if retrieval unchanged)
  3. Score — Ragas context_precision, answer_relevancy, faithfulness (always runs)

Usage:

    # Full run (all three stages)
    python scripts/eval_answer_quality.py

    # Re-score only (skip retrieve + generate if cached)
    python scripts/eval_answer_quality.py

    # Force re-run all stages
    python scripts/eval_answer_quality.py --force

    # Use a specific run directory
    python scripts/eval_answer_quality.py --run-dir eval/rewrite_lift/runs/my-run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import random
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.models import Source
from retrieval_hub.retrieval.api import query
from retrieval_hub.rewriter.llm import LlmClient
from retrieval_hub.rewriter.service import RewriterService
from retrieval_hub.schemas.rewriter import RewriterMetadata
from retrieval_hub.schemas.semantic import SemanticContext

logger = logging.getLogger("eval_answer_quality")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
QA_DATASET_PATH = Path("eval/autorag/qa_dataset_draft.json")
DEFAULT_RUN_DIR = Path("eval/rewrite_lift/runs")

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)
DEFAULT_REWRITER_LLM_URL = (
    "https://gpt-oss-120b-direct-gpt-oss-120b-model"
    ".apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com"
    "/v1/chat/completions"
)
DEFAULT_REWRITER_LLM_MODEL = "/mnt/models"
DEFAULT_ANSWER_LLM_URL = "http://localhost:11434/v1/chat/completions"
DEFAULT_ANSWER_LLM_MODEL = "gpt-oss:20b"
DEFAULT_SCORING_LLM_URL = (
    "https://gpt-oss-120b-direct-gpt-oss-120b-model"
    ".apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1"
)
DEFAULT_SCORING_LLM_MODEL = "/mnt/models"

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

ANSWER_SYSTEM_PROMPT = (
    "You are a clinical reference assistant with access to VA/DoD Clinical "
    "Practice Guidelines. Answer the user's question using ONLY the provided "
    "context. If the context does not contain enough information to answer "
    "fully, say so. Cite the guideline name when possible. Be concise."
)


def _load_eval_queries(qa_path: Path) -> list[dict]:
    data = json.loads(qa_path.read_text(encoding="utf-8"))
    questions = data["questions"]
    lay = [q for q in questions if q["language_register"] == "lay"]
    clinical = [q for q in questions if q["language_register"] == "clinical"]
    rng = random.Random(EVAL_SEED)
    clinical_needed = max(0, TARGET_QUERY_COUNT - len(lay))
    clinical_sample = rng.sample(clinical, min(clinical_needed, len(clinical)))
    selected = lay + clinical_sample
    rng.shuffle(selected)
    return selected


def _chunk_matches_source(doc_title: str, cpg_slug: str) -> bool:
    keywords = SLUG_TO_KEYWORDS.get(cpg_slug)
    if not keywords:
        return False
    title_lower = doc_title.lower()
    return any(kw in title_lower for kw in keywords)


def _config_fingerprint(
    rewriter_metadata: dict,
    semantic_context: dict | None,
    rewriter_llm_model: str,
    answer_llm_model: str,
) -> str:
    blob = json.dumps(
        {
            "rewriter_metadata_hash": hashlib.sha256(
                json.dumps(rewriter_metadata, sort_keys=True).encode()
            ).hexdigest()[:12],
            "semantic_context_hash": hashlib.sha256(
                json.dumps(semantic_context or {}, sort_keys=True).encode()
            ).hexdigest()[:12],
            "rewriter_llm": rewriter_llm_model,
            "answer_llm": answer_llm_model,
            "top_k": TOP_K,
            "eval_seed": EVAL_SEED,
            "query_count": TARGET_QUERY_COUNT,
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _deduplicate_results(results: list) -> list:
    seen: dict[str, object] = {}
    for r in results:
        existing = seen.get(r.text)
        if existing is None or r.score > existing.score:
            seen[r.text] = r
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)


# ── Stage 1: Retrieve ────────────────────────────────────────────────────


async def _stage_retrieve(
    eval_queries: list[dict],
    *,
    session_factory,
    rewriter: RewriterService,
    metadata: RewriterMetadata,
    semantic_context: SemanticContext | None,
    vectors_db_url: str,
) -> list[dict]:
    results = []
    for i, q in enumerate(eval_queries):
        logger.info("[%d/%d] retrieve %s", i + 1, len(eval_queries), q["id"])

        with session_factory() as session:
            raw_hits = query(
                SOURCE_SLUG, q["question"],
                session=session, top_k=TOP_K, vectors_db_url=vectors_db_url,
            )

            rewrite_result = await rewriter.rewrite(
                q["question"], metadata, semantic_context=semantic_context,
            )

            all_rewrite_hits = []
            for rq in rewrite_result.queries:
                hits = query(
                    SOURCE_SLUG, rq.text,
                    session=session, top_k=TOP_K, vectors_db_url=vectors_db_url,
                )
                all_rewrite_hits.extend(hits)

        deduped = _deduplicate_results(all_rewrite_hits)[:TOP_K]

        def _serialize_hits(hits):
            return [
                {
                    "text": h.text,
                    "score": h.score,
                    "doc_title": h.doc_title,
                    "doc_url": h.doc_url,
                    "doc_section": h.doc_section,
                }
                for h in hits
            ]

        raw_hit = any(
            _chunk_matches_source(h.doc_title, q["cpg_slug"]) for h in raw_hits
        )
        rewrite_hit = any(
            _chunk_matches_source(h.doc_title, q["cpg_slug"]) for h in deduped
        )

        results.append({
            "query_id": q["id"],
            "question": q["question"],
            "language_register": q["language_register"],
            "cpg_slug": q["cpg_slug"],
            "reference_answer": q["answer"],
            "raw_hits": _serialize_hits(raw_hits),
            "raw_hit_rate": raw_hit,
            "rewrite_hits": _serialize_hits(deduped),
            "rewrite_hit_rate": rewrite_hit,
            "rewrites": [rq.text for rq in rewrite_result.queries],
        })

    return results


# ── Stage 2: Generate answers ────────────────────────────────────────────


async def _stage_generate(
    retrieval_data: list[dict],
    *,
    answer_llm: LlmClient,
) -> list[dict]:
    results = []
    for i, item in enumerate(retrieval_data):
        logger.info("[%d/%d] generate %s", i + 1, len(retrieval_data), item["query_id"])

        raw_context = "\n\n".join(h["text"] for h in item["raw_hits"])
        raw_answer = await answer_llm.chat(
            [
                {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Context:\n{raw_context}\n\n"
                    f"Question: {item['question']}"
                )},
            ],
            temperature=0.0,
            max_tokens=1024,
        )

        rewrite_context = "\n\n".join(h["text"] for h in item["rewrite_hits"])
        rewrite_answer = await answer_llm.chat(
            [
                {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Context:\n{rewrite_context}\n\n"
                    f"Question: {item['question']}"
                )},
            ],
            temperature=0.0,
            max_tokens=1024,
        )

        results.append({
            **item,
            "raw_answer": raw_answer,
            "rewrite_answer": rewrite_answer,
        })

    return results


# ── Stage 3: Score with Ragas ────────────────────────────────────────────


def _stub_vertexai():
    """Stub the missing langchain_community.chat_models.vertexai module."""
    try:
        import langchain_community.chat_models as cm  # noqa: F401
    except ImportError:
        return
    mod = types.ModuleType("langchain_community.chat_models.vertexai")
    mod.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = mod


def _stage_score(
    answer_data: list[dict],
    *,
    scoring_llm_url: str,
    scoring_llm_model: str,
    run_dir: Path,
    max_workers: int = 2,
) -> dict:
    """Score with Ragas, checkpointing each condition to disk.

    Scores the raw and rewrite conditions independently.  Each condition's
    results are saved to ``{run_dir}/scores_{condition}.json`` as soon as
    they complete, so a killed run preserves the finished condition.
    """
    _stub_vertexai()

    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    from langchain_community.embeddings import HuggingFaceEmbeddings
    from openai import OpenAI
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.llms import llm_factory
    from ragas.metrics._answer_relevance import AnswerRelevancy
    from ragas.metrics._context_precision import ContextPrecision
    from ragas.metrics._faithfulness import Faithfulness
    from ragas.run_config import RunConfig

    client = OpenAI(api_key="local", base_url=scoring_llm_url)

    if "gpt-oss-120b" in scoring_llm_url or scoring_llm_model == "/mnt/models":
        original_create = client.chat.completions.create
        def _patched_create(*args, **kwargs):
            extra_body = kwargs.get("extra_body", {}) or {}
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}
            kwargs["extra_body"] = extra_body
            return original_create(*args, **kwargs)
        client.chat.completions.create = _patched_create

    llm = llm_factory(scoring_llm_model, client=client, max_tokens=8192)
    embeddings = HuggingFaceEmbeddings(
        model_name="NeuML/pubmedbert-base-embeddings",
        cache_folder=".model_cache",
    )
    ragas_run_config = RunConfig(max_workers=max_workers, timeout=600)

    def _build_samples(condition: str) -> list[SingleTurnSample]:
        hits_key = f"{condition}_hits"
        answer_key = f"{condition}_answer"
        return [
            SingleTurnSample(
                user_input=item["question"],
                retrieved_contexts=[h["text"] for h in item[hits_key]],
                response=item[answer_key],
                reference=item["reference_answer"],
            )
            for item in answer_data
        ]

    metrics = [ContextPrecision(), AnswerRelevancy(), Faithfulness()]
    results = {}

    for condition in ("raw", "rewrite"):
        checkpoint_path = run_dir / f"scores_{condition}.json"

        if checkpoint_path.exists():
            logger.info(
                "scoring %s condition: using checkpoint %s",
                condition, checkpoint_path,
            )
            results[condition] = json.loads(checkpoint_path.read_text())
            continue

        logger.info("scoring %s condition (%d workers)...", condition, max_workers)
        samples = _build_samples(condition)
        dataset = EvaluationDataset(samples=samples)
        ragas_result = evaluate(
            dataset=dataset, metrics=metrics,
            llm=llm, embeddings=embeddings,
            run_config=ragas_run_config,
        )
        df = ragas_result.to_pandas()

        metric_names = [m.name for m in metrics]
        per_query = []
        for idx, item in enumerate(answer_data):
            row = {
                "query_id": item["query_id"],
                "language_register": item["language_register"],
                "cpg_slug": item["cpg_slug"],
            }
            for mn in metric_names:
                row[mn] = float(df.iloc[idx][mn])
            per_query.append(row)

        agg = {mn: float(df[mn].mean()) for mn in metric_names}
        condition_result = {"aggregate": agg, "per_query": per_query}

        checkpoint_path.write_text(json.dumps(condition_result, indent=2) + "\n")
        logger.info("scoring %s condition complete, checkpoint saved", condition)

        results[condition] = condition_result

    return results


# ── Orchestrator ─────────────────────────────────────────────────────────


def _print_summary(scores: dict, retrieval_data: list[dict], wall_time: float) -> None:
    print()
    print("=" * 72)
    print("Answer-Quality Evaluation Results")
    print("=" * 72)

    raw_agg = scores["raw"]["aggregate"]
    rw_agg = scores["rewrite"]["aggregate"]
    metric_names = list(raw_agg.keys())

    for condition in ("raw", "rewrite"):
        agg = scores[condition]["aggregate"]
        print(f"\n  {condition.upper()} retrieval:")
        for mn in metric_names:
            print(f"    {mn:<22} {agg[mn]:.3f}")

    print("\n  Delta (rewrite - raw):")
    for mn in metric_names:
        delta = rw_agg[mn] - raw_agg[mn]
        print(f"    {mn:<22} {delta:>+.3f}")

    by_register: dict[str, dict] = {}
    for condition in ("raw", "rewrite"):
        for pq in scores[condition]["per_query"]:
            reg = pq["language_register"]
            key = f"{condition}_{reg}"
            by_register.setdefault(key, []).append(pq)

    for reg in ("lay", "clinical"):
        raw_items = by_register.get(f"raw_{reg}", [])
        rw_items = by_register.get(f"rewrite_{reg}", [])
        if not raw_items:
            continue
        n = len(raw_items)
        print(f"\n  {reg.upper()} register (n={n}):")
        for mn in metric_names:
            raw_mean = sum(i[mn] for i in raw_items) / n
            rw_mean = sum(i[mn] for i in rw_items) / n
            delta = rw_mean - raw_mean
            print(f"    {mn:<22} raw={raw_mean:.3f}  rw={rw_mean:.3f}  delta={delta:>+.3f}")

    n_total = len(retrieval_data)
    raw_hits = sum(1 for d in retrieval_data if d["raw_hit_rate"])
    rw_hits = sum(1 for d in retrieval_data if d["rewrite_hit_rate"])
    print(f"\n  Retrieval hit_rate@5: raw={raw_hits}/{n_total}  rewrite={rw_hits}/{n_total}")
    print(f"\n  Wall time: {wall_time:.1f}s")
    print("=" * 72)


async def _run(args: argparse.Namespace) -> int:
    wall_start = time.monotonic()

    eval_queries = _load_eval_queries(QA_DATASET_PATH)
    logger.info("loaded %d eval queries", len(eval_queries))

    session_factory = make_session_factory(create_db_engine(args.db_url))

    with session_factory() as session:
        source = session.query(Source).filter(Source.slug == SOURCE_SLUG).one_or_none()
        if source is None:
            logger.error("Source %r not found", SOURCE_SLUG)
            return 1
        raw_rw = source.rewriter_metadata
        raw_sc = source.semantic_context

    metadata = RewriterMetadata.model_validate(raw_rw)
    semantic = SemanticContext.model_validate(raw_sc) if raw_sc else None

    fingerprint = _config_fingerprint(
        raw_rw, raw_sc, args.rewriter_llm_model, args.answer_llm_model,
    )

    run_dir = Path(args.run_dir) if args.run_dir else DEFAULT_RUN_DIR / fingerprint
    run_dir.mkdir(parents=True, exist_ok=True)

    config_path = run_dir / "config.json"
    retrieval_path = run_dir / "retrieval.json"
    answers_path = run_dir / "answers.json"
    scores_path = run_dir / "scores.json"
    summary_path = run_dir / "summary.json"

    run_config = {
        "fingerprint": fingerprint,
        "source_slug": SOURCE_SLUG,
        "rewriter_llm": args.rewriter_llm_model,
        "answer_llm": args.answer_llm_model,
        "scoring_llm": args.scoring_llm_model,
        "top_k": TOP_K,
        "eval_seed": EVAL_SEED,
        "query_count": len(eval_queries),
    }
    config_path.write_text(json.dumps(run_config, indent=2) + "\n")

    # Stage 1: Retrieve
    if retrieval_path.exists() and not args.force:
        logger.info("stage 1 (retrieve): using cached %s", retrieval_path)
        retrieval_data = json.loads(retrieval_path.read_text())
    else:
        logger.info("stage 1 (retrieve): running...")
        async with LlmClient(
            base_url=args.rewriter_llm_url, model=args.rewriter_llm_model,
        ) as rewriter_llm:
            rewriter = RewriterService(rewriter_llm)
            retrieval_data = await _stage_retrieve(
                eval_queries,
                session_factory=session_factory,
                rewriter=rewriter,
                metadata=metadata,
                semantic_context=semantic,
                vectors_db_url=args.vectors_db_url,
            )
        retrieval_path.write_text(json.dumps(retrieval_data, indent=2) + "\n")
        logger.info("stage 1 complete, wrote %s", retrieval_path)

    # Stage 2: Generate answers
    if answers_path.exists() and not args.force:
        logger.info("stage 2 (generate): using cached %s", answers_path)
        answer_data = json.loads(answers_path.read_text())
    else:
        logger.info("stage 2 (generate): running...")
        async with LlmClient(
            base_url=args.answer_llm_url, model=args.answer_llm_model,
        ) as answer_llm:
            answer_data = await _stage_generate(retrieval_data, answer_llm=answer_llm)
        answers_path.write_text(json.dumps(answer_data, indent=2) + "\n")
        logger.info("stage 2 complete, wrote %s", answers_path)

    # Stage 3: Score (checkpoints per condition)
    logger.info("stage 3 (score): running Ragas metrics...")
    scores = _stage_score(
        answer_data,
        scoring_llm_url=args.scoring_llm_url,
        scoring_llm_model=args.scoring_llm_model,
        run_dir=run_dir,
        max_workers=args.max_workers,
    )
    scores_path.write_text(json.dumps(scores, indent=2) + "\n")
    logger.info("stage 3 complete, wrote %s", scores_path)

    wall_time = time.monotonic() - wall_start

    summary = {
        "config": run_config,
        "date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wall_time_seconds": round(wall_time, 1),
        "raw": scores["raw"]["aggregate"],
        "rewrite": scores["rewrite"]["aggregate"],
        "delta": {
            mn: round(
                scores["rewrite"]["aggregate"][mn]
                - scores["raw"]["aggregate"][mn], 4,
            )
            for mn in scores["raw"]["aggregate"]
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    _print_summary(scores, retrieval_data, wall_time)
    print(f"\n  Run directory: {run_dir}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL,
                        help=f"Catalog DB URL. Default: {DEFAULT_DB_URL}")
    parser.add_argument("--vectors-db-url", default=DEFAULT_VECTORS_DB_URL,
                        help=f"Vectors DB URL. Default: {DEFAULT_VECTORS_DB_URL}")
    parser.add_argument("--rewriter-llm-url", default=DEFAULT_REWRITER_LLM_URL,
                        help="Rewriter LLM endpoint URL.")
    parser.add_argument("--rewriter-llm-model", default=DEFAULT_REWRITER_LLM_MODEL,
                        help=f"Rewriter LLM model. Default: {DEFAULT_REWRITER_LLM_MODEL}")
    parser.add_argument("--answer-llm-url", default=DEFAULT_ANSWER_LLM_URL,
                        help=f"Answer generation LLM URL. Default: {DEFAULT_ANSWER_LLM_URL}")
    parser.add_argument("--answer-llm-model", default=DEFAULT_ANSWER_LLM_MODEL,
                        help=f"Answer generation model. Default: {DEFAULT_ANSWER_LLM_MODEL}")
    parser.add_argument("--scoring-llm-url", default=DEFAULT_SCORING_LLM_URL,
                        help=f"Ragas scoring LLM URL. Default: {DEFAULT_SCORING_LLM_URL}")
    parser.add_argument("--scoring-llm-model", default=DEFAULT_SCORING_LLM_MODEL,
                        help=f"Ragas scoring model. Default: {DEFAULT_SCORING_LLM_MODEL}")
    parser.add_argument("--run-dir", default=None,
                        help="Explicit run directory. Default: auto-generated from config hash.")
    parser.add_argument("--max-workers", type=int, default=2,
                        help="Parallel workers for Ragas scoring. Default: 2")
    parser.add_argument("--force", action="store_true",
                        help="Force re-run all stages (ignore cache).")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
