"""Compare reranking strategies (cosine_dedup / rrf / cross_encoder).

Four-stage pipeline with per-stage caching:
  1. Expanded retrieval — per-rewrite ranked lists (cached)
  2. Reranking — apply strategies (pure functions, no caching needed)
  3. Generate — produce answers from each strategy's top-5 (cached per strategy)
  4. Score — Ragas context_precision + answer_relevancy (checkpointed per strategy)

Usage:
    python scripts/eval_rerank_strategies.py
    python scripts/eval_rerank_strategies.py --strategies cosine_dedup,rrf
    python scripts/eval_rerank_strategies.py --force
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.rewriter.llm import LlmClient

logger = logging.getLogger("eval_rerank_strategies")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
QA_DATASET_PATH = Path("eval/autorag/qa_dataset_draft.json")
DEFAULT_RUN_DIR = Path("eval/rewrite_lift/runs/rerank-comparison")
DEFAULT_PRIOR_RETRIEVAL_PATH = Path(
    "eval/rewrite_lift/runs/9084a31205273246/retrieval.json"
)

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
)
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

STRATEGIES = [
    "cosine_dedup", "rrf", "cross_encoder", "cosine_original", "llm_rerank",
    "cross_encoder_register_aware",
    "hybrid_alpha_03", "hybrid_alpha_05", "hybrid_alpha_07",
]

ANSWER_SYSTEM_PROMPT = (
    "You are a clinical reference assistant with access to VA/DoD Clinical "
    "Practice Guidelines. Answer the user's question using ONLY the provided "
    "context. If the context does not contain enough information to answer "
    "fully, say so. Cite the guideline name when possible. Be concise."
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _chunk_matches_source(doc_title: str, cpg_slug: str) -> bool:
    keywords = SLUG_TO_KEYWORDS.get(cpg_slug)
    if not keywords:
        return False
    title_lower = doc_title.lower()
    return any(kw in title_lower for kw in keywords)


def _minmax_normalize(scores):
    """Min-max normalize a list of scores to [0, 1]."""
    import numpy as np

    arr = np.array(scores, dtype=float)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return np.ones_like(arr) * 0.5
    return (arr - lo) / (hi - lo)


def _compute_hit_mrr(hits: list[dict], cpg_slug: str) -> tuple[bool, float]:
    for i, h in enumerate(hits):
        if _chunk_matches_source(h["doc_title"], cpg_slug):
            return True, 1.0 / (i + 1)
    return False, 0.0


def _serialize_hits(hits) -> list[dict]:
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


# ── Stage 1: Expanded retrieval ─────────────────────────────────────────


def _stage_expand_retrieval(
    prior_data: list[dict], *, session_factory, vectors_db_url: str,
) -> list[dict]:
    """Re-retrieve per-rewrite to get individual ranked lists."""
    from retrieval_hub.retrieval.api import query

    results = []
    for i, item in enumerate(prior_data):
        logger.info("[%d/%d] expand %s", i + 1, len(prior_data), item["query_id"])
        rewrite_hits: dict[str, list[dict]] = {}
        with session_factory() as session:
            for idx, rewrite_text in enumerate(item["rewrites"]):
                hits = query(
                    SOURCE_SLUG, rewrite_text,
                    session=session, top_k=TOP_K, vectors_db_url=vectors_db_url,
                )
                rewrite_hits[str(idx)] = _serialize_hits(hits)
        results.append({
            "query_id": item["query_id"],
            "question": item["question"],
            "language_register": item["language_register"],
            "cpg_slug": item["cpg_slug"],
            "reference_answer": item["reference_answer"],
            "original_hits": item["raw_hits"],
            "rewrite_hits": rewrite_hits,
            "rewrites": item["rewrites"],
        })
    return results


# ── Stage 2: Reranking strategies ───────────────────────────────────────


def _rerank_cosine_dedup(item: dict) -> list[dict]:
    """Return top-5 hits using cosine dedup of rewrite results."""
    seen: dict[str, dict] = {}
    for _idx, hits in item["rewrite_hits"].items():
        for h in hits:
            existing = seen.get(h["text"])
            if existing is None or h["score"] > existing["score"]:
                seen[h["text"]] = h
    ranked = sorted(seen.values(), key=lambda h: h["score"], reverse=True)
    return ranked[:TOP_K]


def _rerank_rrf(item: dict, k: int = 60) -> list[dict]:
    """Return top-5 hits using reciprocal rank fusion of original + rewrites."""
    ranked_lists = [item["original_hits"]] + [
        item["rewrite_hits"][idx] for idx in sorted(item["rewrite_hits"], key=int)
    ]
    chunk_scores: dict[str, float] = {}
    chunk_data: dict[str, dict] = {}
    for rlist in ranked_lists:
        for rank, h in enumerate(rlist):
            chunk_scores[h["text"]] = chunk_scores.get(h["text"], 0.0) + 1.0 / (k + rank)
            if h["text"] not in chunk_data:
                chunk_data[h["text"]] = h
    ranked = sorted(chunk_data.values(), key=lambda h: chunk_scores[h["text"]], reverse=True)
    return ranked[:TOP_K]


def _rerank_cross_encoder(item: dict, model) -> list[dict]:
    """Return top-5 hits rescored by cross-encoder against original query."""
    seen: dict[str, dict] = {}
    for h in item["original_hits"]:
        if h["text"] not in seen:
            seen[h["text"]] = h
    for _idx, hits in item["rewrite_hits"].items():
        for h in hits:
            if h["text"] not in seen:
                seen[h["text"]] = h

    candidates = list(seen.values())
    if not candidates:
        return []

    pairs = [(item["question"], c["text"]) for c in candidates]
    scores = model.predict(pairs)

    scored = list(zip(candidates, scores, strict=True))
    scored.sort(key=lambda x: float(x[1]), reverse=True)
    return [c for c, _s in scored[:TOP_K]]


def _rerank_cross_encoder_register_aware(item: dict, model) -> list[dict]:
    """Cross-encoder reranking, but skip rewrite pool for clinical queries."""
    seen: dict[str, dict] = {}
    for h in item["original_hits"]:
        if h["text"] not in seen:
            seen[h["text"]] = h
    if item["language_register"] != "clinical":
        for _idx, hits in item["rewrite_hits"].items():
            for h in hits:
                if h["text"] not in seen:
                    seen[h["text"]] = h

    candidates = list(seen.values())
    if not candidates:
        return []

    pairs = [(item["question"], c["text"]) for c in candidates]
    scores = model.predict(pairs)

    scored = list(zip(candidates, scores, strict=True))
    scored.sort(key=lambda x: float(x[1]), reverse=True)
    return [c for c, _s in scored[:TOP_K]]


def _rerank_hybrid(item: dict, model, alpha: float) -> list[dict]:
    """Blend cross-encoder and cosine scores with tunable alpha."""
    seen: dict[str, tuple[dict, float]] = {}
    for h in item["original_hits"]:
        if h["text"] not in seen or h["score"] > seen[h["text"]][1]:
            seen[h["text"]] = (h, h["score"])
    for _idx, hits in item["rewrite_hits"].items():
        for h in hits:
            if h["text"] not in seen or h["score"] > seen[h["text"]][1]:
                seen[h["text"]] = (h, h["score"])

    candidates = [v[0] for v in seen.values()]
    cosine_scores = [v[1] for v in seen.values()]
    if not candidates:
        return []

    pairs = [(item["question"], c["text"]) for c in candidates]
    ce_scores = model.predict(pairs)

    ce_norm = _minmax_normalize(ce_scores)
    cos_norm = _minmax_normalize(cosine_scores)

    final = alpha * ce_norm + (1 - alpha) * cos_norm
    scored = list(zip(candidates, final, strict=True))
    scored.sort(key=lambda x: float(x[1]), reverse=True)
    return [c for c, _s in scored[:TOP_K]]


def _rerank_cosine_original(item: dict, embedder) -> list[dict]:
    """Return top-5 hits rescored by cosine similarity to the original query."""
    seen: dict[str, dict] = {}
    for h in item["original_hits"]:
        if h["text"] not in seen:
            seen[h["text"]] = h
    for _idx, hits in item["rewrite_hits"].items():
        for h in hits:
            if h["text"] not in seen:
                seen[h["text"]] = h

    candidates = list(seen.values())
    if not candidates:
        return []

    import numpy as np

    query_emb = embedder.encode([item["question"]])[0]
    chunk_embs = embedder.encode([c["text"] for c in candidates])
    sims = np.dot(chunk_embs, query_emb) / (
        np.linalg.norm(chunk_embs, axis=1) * np.linalg.norm(query_emb)
    )

    scored = list(zip(candidates, sims, strict=True))
    scored.sort(key=lambda x: float(x[1]), reverse=True)
    return [c for c, _s in scored[:TOP_K]]


async def _rerank_llm(item: dict, llm: LlmClient) -> list[dict]:
    """Return top-5 hits reranked by LLM judgment against the original query."""
    seen: dict[str, dict] = {}
    for h in item["original_hits"]:
        if h["text"] not in seen:
            seen[h["text"]] = h
    for _idx, hits in item["rewrite_hits"].items():
        for h in hits:
            if h["text"] not in seen:
                seen[h["text"]] = h

    candidates = list(seen.values())
    if not candidates:
        return []

    numbered = "\n\n".join(
        f"[{i}] {c['text'][:500]}" for i, c in enumerate(candidates)
    )
    prompt = (
        f"Question: {item['question']}\n\n"
        f"Below are {len(candidates)} text passages. Rank the top 5 most "
        f"relevant passages for answering the question. Return ONLY a JSON "
        f"array of the passage numbers (0-indexed), most relevant first. "
        f"Example: [3, 0, 7, 2, 5]\n\n{numbered}"
    )

    import json as _json

    raw = await llm.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=256,
    )

    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        indices = _json.loads(text)
        result = []
        for idx in indices[:TOP_K]:
            if 0 <= idx < len(candidates):
                result.append(candidates[idx])
        return result if result else candidates[:TOP_K]
    except Exception:
        logger.warning("LLM rerank parse failed, falling back to original order")
        return candidates[:TOP_K]


async def _apply_strategy(
    expanded_data: list[dict],
    strategy: str,
    *,
    cross_encoder_model=None,
    embedder=None,
    llm: LlmClient | None = None,
) -> dict[str, list[dict]]:
    """Apply a reranking strategy to all queries. Returns query_id -> top-5."""
    results = {}
    for item in expanded_data:
        if strategy == "cosine_dedup":
            results[item["query_id"]] = _rerank_cosine_dedup(item)
        elif strategy == "rrf":
            results[item["query_id"]] = _rerank_rrf(item)
        elif strategy == "cross_encoder":
            results[item["query_id"]] = _rerank_cross_encoder(item, cross_encoder_model)
        elif strategy == "cosine_original":
            results[item["query_id"]] = _rerank_cosine_original(item, embedder)
        elif strategy == "cross_encoder_register_aware":
            results[item["query_id"]] = _rerank_cross_encoder_register_aware(
                item, cross_encoder_model,
            )
        elif strategy.startswith("hybrid_alpha_"):
            alpha = int(strategy.split("_")[-1]) / 10.0
            results[item["query_id"]] = _rerank_hybrid(
                item, cross_encoder_model, alpha,
            )
        elif strategy == "llm_rerank":
            results[item["query_id"]] = await _rerank_llm(item, llm)
        else:
            msg = f"Unknown strategy: {strategy}"
            raise ValueError(msg)
    return results


# ── Stage 3: Generate answers ───────────────────────────────────────────


async def _stage_generate(
    expanded_data: list[dict], strategy_hits: dict[str, list[dict]],
    *, answer_llm: LlmClient, strategy_name: str,
) -> list[dict]:
    results = []
    for i, item in enumerate(expanded_data):
        logger.info("[%d/%d] generate (%s) %s",
                    i + 1, len(expanded_data), strategy_name, item["query_id"])
        hits = strategy_hits[item["query_id"]]
        context = "\n\n".join(h["text"] for h in hits)
        answer = await answer_llm.chat(
            [{"role": "system", "content": ANSWER_SYSTEM_PROMPT},
             {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {item['question']}"}],
            temperature=0.0, max_tokens=1024,
        )
        results.append({
            "query_id": item["query_id"], "question": item["question"],
            "language_register": item["language_register"],
            "cpg_slug": item["cpg_slug"],
            "reference_answer": item["reference_answer"],
            "hits": hits, "answer": answer,
        })
    return results


# ── Stage 4: Score with Ragas ───────────────────────────────────────────


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
    answer_data: list[dict], *, scoring_llm_url: str, scoring_llm_model: str,
    strategy_name: str, run_dir: Path, max_workers: int = 2,
) -> dict:
    """Score a single strategy with Ragas, checkpointing to disk."""
    checkpoint_path = run_dir / f"scores_{strategy_name}.json"
    if checkpoint_path.exists():
        logger.info("scoring %s: using checkpoint %s", strategy_name, checkpoint_path)
        return json.loads(checkpoint_path.read_text())

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
        model_name="NeuML/pubmedbert-base-embeddings", cache_folder=".model_cache",
    )
    samples = [
        SingleTurnSample(
            user_input=item["question"],
            retrieved_contexts=[h["text"] for h in item["hits"]],
            response=item["answer"], reference=item["reference_answer"],
        )
        for item in answer_data
    ]
    metrics = [ContextPrecision(), AnswerRelevancy(), Faithfulness()]
    logger.info("scoring %s (%d workers)...", strategy_name, max_workers)
    dataset = EvaluationDataset(samples=samples)
    ragas_result = evaluate(
        dataset=dataset, metrics=metrics, llm=llm, embeddings=embeddings,
        run_config=RunConfig(max_workers=max_workers, timeout=600),
    )
    df = ragas_result.to_pandas()
    metric_names = [m.name for m in metrics]
    per_query = []
    for idx, item in enumerate(answer_data):
        row = {"query_id": item["query_id"],
               "language_register": item["language_register"],
               "cpg_slug": item["cpg_slug"]}
        for mn in metric_names:
            row[mn] = float(df.iloc[idx][mn])
        per_query.append(row)

    agg = {mn: float(df[mn].mean()) for mn in metric_names}
    result = {"aggregate": agg, "per_query": per_query}
    checkpoint_path.write_text(json.dumps(result, indent=2) + "\n")
    logger.info("scoring %s complete, checkpoint saved", strategy_name)
    return result


# ── Scoreboard ──────────────────────────────────────────────────────────


def _agg_hit_mrr(
    items: list[dict], hits_map: dict[str, list[dict]],
) -> tuple[float, float]:
    """Compute hit_rate and MRR over a set of expanded items."""
    n = len(items)
    if not n:
        return 0.0, 0.0
    total_hit, total_mrr = 0, 0.0
    for item in items:
        hit, mrr = _compute_hit_mrr(
            hits_map[item["query_id"]], item["cpg_slug"],
        )
        total_hit += int(hit)
        total_mrr += mrr
    return round(total_hit / n, 4), round(total_mrr / n, 4)


def _build_scoreboard(
    all_scores: dict[str, dict],
    all_strategy_hits: dict[str, dict[str, list[dict]]],
    expanded_data: list[dict],
) -> dict:
    """Build the final comparison scoreboard."""
    strategies_summary = {}
    for strat, scores in all_scores.items():
        hr, mrr = _agg_hit_mrr(expanded_data, all_strategy_hits[strat])
        strategies_summary[strat] = {
            **scores["aggregate"], "hit_rate": hr, "mrr": mrr,
        }

    by_register: dict[str, dict[str, dict]] = {}
    for reg in ("lay", "clinical"):
        by_register[reg] = {}
        reg_items = [
            d for d in expanded_data if d["language_register"] == reg
        ]
        if not reg_items:
            continue
        reg_ids = {d["query_id"] for d in reg_items}
        for strat, scores in all_scores.items():
            pq = [q for q in scores["per_query"] if q["query_id"] in reg_ids]
            agg = {}
            for mn in scores["aggregate"]:
                vals = [q[mn] for q in pq if mn in q]
                agg[mn] = round(sum(vals) / len(vals), 4) if vals else 0
            agg["hit_rate"], agg["mrr"] = _agg_hit_mrr(
                reg_items, all_strategy_hits[strat],
            )
            by_register[reg][strat] = agg

    return {
        "date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategies": strategies_summary,
        "by_register": by_register,
    }


def _print_scoreboard(scoreboard: dict, wall_time: float) -> None:
    print("\n" + "=" * 72)
    print("Reranking Strategy Comparison")
    print("=" * 72)
    strats = scoreboard["strategies"]
    names = list(strats)
    metric_names = list(next(iter(strats.values())).keys())

    print(f"\n  {'metric':<24}" + "".join(f" {s:>14}" for s in names))
    print(f"  {'-' * 24}" + f" {'-' * 14}" * len(names))
    for mn in metric_names:
        print(f"  {mn:<24}" + "".join(f" {strats[s][mn]:>14.4f}" for s in names))

    for reg in ("lay", "clinical"):
        reg_data = scoreboard.get("by_register", {}).get(reg, {})
        if not reg_data:
            continue
        print(f"\n  {reg.upper()} register:")
        for mn in next(iter(reg_data.values())):
            print(f"    {mn:<22}" + "".join(f" {reg_data[s][mn]:>14.4f}" for s in reg_data))

    print(f"\n  Wall time: {wall_time:.1f}s")
    print("=" * 72)


# ── Orchestrator ────────────────────────────────────────────────────────


async def _run(args: argparse.Namespace) -> int:
    wall_start = time.monotonic()

    # Load prior retrieval data (has rewrites + raw_hits)
    prior_path = Path(args.prior_retrieval)
    if not prior_path.exists():
        logger.error("Prior retrieval cache not found: %s", prior_path)
        return 1
    prior_data = json.loads(prior_path.read_text())
    if args.subset:
        prior_data = prior_data[:args.subset]
    logger.info("loaded %d queries from prior retrieval cache", len(prior_data))

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    strategies = [s.strip() for s in args.strategies.split(",")]
    for s in strategies:
        if s not in STRATEGIES:
            logger.error("Unknown strategy %r (valid: %s)", s, STRATEGIES)
            return 1

    expanded_path = run_dir / "retrieval_expanded.json"

    # Stage 1: Expanded retrieval
    if expanded_path.exists() and not args.force:
        logger.info("stage 1 (expand): using cached %s", expanded_path)
        expanded_data = json.loads(expanded_path.read_text())
    else:
        logger.info("stage 1 (expand): retrieving per-rewrite hits...")
        sf = make_session_factory(create_db_engine(args.db_url))
        expanded_data = _stage_expand_retrieval(
            prior_data, session_factory=sf, vectors_db_url=args.vectors_db_url,
        )
        expanded_path.write_text(json.dumps(expanded_data, indent=2) + "\n")
        logger.info("stage 1 complete, wrote %s", expanded_path)

    # Stage 2: Apply reranking strategies
    logger.info("stage 2 (rerank): applying strategies...")
    cross_encoder_model = None
    _needs_cross_encoder = any(
        s == "cross_encoder" or s == "cross_encoder_register_aware"
        or s.startswith("hybrid_alpha_")
        for s in strategies
    )
    if _needs_cross_encoder:
        from sentence_transformers import CrossEncoder
        logger.info("loading cross-encoder model...")
        cross_encoder_model = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            cache_folder=".model_cache",
        )

    embedder = None
    if "cosine_original" in strategies:
        from sentence_transformers import SentenceTransformer
        logger.info("loading embedding model for cosine_original...")
        embedder = SentenceTransformer(
            "NeuML/pubmedbert-base-embeddings",
            cache_folder=".model_cache",
        )

    rerank_llm = None
    if "llm_rerank" in strategies:
        rerank_llm = LlmClient(
            base_url=args.answer_llm_url, model=args.answer_llm_model,
        )

    all_strategy_hits: dict[str, dict[str, list[dict]]] = {}
    for strat in strategies:
        logger.info("  applying strategy: %s", strat)
        all_strategy_hits[strat] = await _apply_strategy(
            expanded_data, strat,
            cross_encoder_model=cross_encoder_model,
            embedder=embedder,
            llm=rerank_llm,
        )

    if rerank_llm is not None:
        await rerank_llm.close()

    # Stage 3: Generate answers per strategy
    all_answer_data: dict[str, list[dict]] = {}
    async with LlmClient(
        base_url=args.answer_llm_url, model=args.answer_llm_model,
    ) as answer_llm:
        for strat in strategies:
            answers_path = run_dir / f"answers_{strat}.json"
            if answers_path.exists() and not args.force:
                logger.info(
                    "stage 3 (generate %s): using cached %s", strat, answers_path,
                )
                all_answer_data[strat] = json.loads(answers_path.read_text())
            else:
                logger.info("stage 3 (generate %s): running...", strat)
                answer_data = await _stage_generate(
                    expanded_data,
                    all_strategy_hits[strat],
                    answer_llm=answer_llm,
                    strategy_name=strat,
                )
                answers_path.write_text(
                    json.dumps(answer_data, indent=2) + "\n",
                )
                logger.info("stage 3 (%s) complete, wrote %s", strat, answers_path)
                all_answer_data[strat] = answer_data

    # Stage 4: Score with Ragas per strategy
    logger.info("stage 4 (score): running Ragas metrics...")
    all_scores: dict[str, dict] = {}
    for strat in strategies:
        all_scores[strat] = _stage_score(
            all_answer_data[strat],
            scoring_llm_url=args.scoring_llm_url,
            scoring_llm_model=args.scoring_llm_model,
            strategy_name=strat,
            run_dir=run_dir,
            max_workers=args.max_workers,
        )

    # Build and save scoreboard
    scoreboard = _build_scoreboard(
        all_scores, all_strategy_hits, expanded_data,
    )
    scoreboard_path = run_dir / "scoreboard.json"
    scoreboard_path.write_text(json.dumps(scoreboard, indent=2) + "\n")
    logger.info("wrote %s", scoreboard_path)

    wall_time = time.monotonic() - wall_start
    _print_scoreboard(scoreboard, wall_time)
    print(f"\n  Run directory: {run_dir}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prior-retrieval", default=str(DEFAULT_PRIOR_RETRIEVAL_PATH),
                   help="Path to prior retrieval.json (has rewrites + raw_hits).")
    p.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    p.add_argument("--db-url", default=DEFAULT_DB_URL)
    p.add_argument("--vectors-db-url", default=DEFAULT_VECTORS_DB_URL)
    p.add_argument("--answer-llm-url", default=DEFAULT_ANSWER_LLM_URL)
    p.add_argument("--answer-llm-model", default=DEFAULT_ANSWER_LLM_MODEL)
    p.add_argument("--scoring-llm-url", default=DEFAULT_SCORING_LLM_URL)
    p.add_argument("--scoring-llm-model", default=DEFAULT_SCORING_LLM_MODEL)
    p.add_argument("--max-workers", type=int, default=2)
    p.add_argument("--strategies", default=",".join(STRATEGIES))
    p.add_argument("--subset", type=int, default=None,
                   help="Run on first N queries only (for smoke testing).")
    p.add_argument("--force", action="store_true")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
