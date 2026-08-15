#!/usr/bin/env python
"""Evaluate retrieval quality for each chunked corpus.

For each of the 12 chunking configurations produced by the chunking
sweep, this script:
  1. Embeds all chunks with PubMedBERT
  2. For each QA question, embeds the query and finds top-k chunks
  3. Checks whether any retrieved chunk comes from the ground-truth
     document (retrieval_gt)
  4. Computes context_recall, MRR, and hit_rate per config

This avoids AutoRAG's built-in Evaluator (which requires vectordb setup)
and directly measures what matters: does the chunking strategy help find
the right document content?
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger("eval_retrieval")


def _load_model(model_name: str):
    """Load sentence-transformers model."""
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", ".model_cache")
    os.environ.setdefault("HF_HOME", ".model_cache")
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name, trust_remote_code=True)


def _embed_texts(model, texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Embed a list of texts, return normalized numpy array."""
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vectors


def _cosine_search(query_vec: np.ndarray, corpus_vecs: np.ndarray, top_k: int) -> list[tuple[int, float]]:
    """Return top-k (index, score) pairs by cosine similarity."""
    scores = corpus_vecs @ query_vec
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(int(idx), float(scores[idx])) for idx in top_indices]


def evaluate_config(
    chunk_df: pd.DataFrame,
    qa_df: pd.DataFrame,
    model,
    top_k: int = 5,
) -> dict:
    """Evaluate a single chunking configuration.

    Returns dict with metrics: hit_rate, mrr, avg_score, chunk_count.
    """
    chunk_texts = chunk_df["contents"].tolist()
    # AutoRAG generates UUID doc_ids; the original document identity is in 'path'
    chunk_paths = [
        p.removesuffix(".md") if isinstance(p, str) else ""
        for p in chunk_df["path"].tolist()
    ]

    logger.info("  Embedding %d chunks...", len(chunk_texts))
    t0 = time.monotonic()
    corpus_vecs = _embed_texts(model, chunk_texts)
    embed_time = time.monotonic() - t0
    logger.info("  Embedded in %.1fs", embed_time)

    hits = 0
    reciprocal_ranks = []
    avg_scores = []

    for _, row in qa_df.iterrows():
        query = row["query"]
        gt_doc_ids = row["retrieval_gt"]
        if isinstance(gt_doc_ids, str):
            gt_doc_ids = ast.literal_eval(gt_doc_ids)
        # Flatten: [[id1, id2]] -> {id1, id2}
        gt_set = set()
        for gt_list in gt_doc_ids:
            if isinstance(gt_list, (list, np.ndarray)):
                gt_set.update(str(x) for x in gt_list)
            else:
                gt_set.add(str(gt_list))

        query_vec = _embed_texts(model, [query])[0]
        results = _cosine_search(query_vec, corpus_vecs, top_k)

        hit = False
        rr = 0.0
        for rank, (idx, score) in enumerate(results, 1):
            retrieved_path = chunk_paths[idx]
            if retrieved_path in gt_set:
                if not hit:
                    hit = True
                    rr = 1.0 / rank
                break

        hits += int(hit)
        reciprocal_ranks.append(rr)
        avg_scores.append(results[0][1] if results else 0.0)

    n = len(qa_df)
    return {
        "hit_rate": hits / n,
        "mrr": sum(reciprocal_ranks) / n,
        "avg_top1_score": sum(avg_scores) / n,
        "chunk_count": len(chunk_texts),
        "embed_time_s": embed_time,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality per chunking config")
    parser.add_argument("--chunk-dir", type=Path, default=Path("eval/autorag/results/chunk"))
    parser.add_argument("--qa-path", type=Path, default=Path("eval/autorag/data/qa.parquet"))
    parser.add_argument("--model", default="NeuML/pubmedbert-base-embeddings")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("eval/autorag/results/retrieval_eval.csv"))
    args = parser.parse_args()

    qa_df = pd.read_parquet(args.qa_path)
    logger.info("Loaded %d QA pairs", len(qa_df))

    summary = pd.read_csv(args.chunk_dir / "summary.csv")
    logger.info("Found %d chunking configurations", len(summary))

    logger.info("Loading embedding model: %s", args.model)
    model = _load_model(args.model)

    results = []
    for _, row in summary.iterrows():
        params = eval(row["module_params"])
        method = params["chunk_method"]
        size = params["chunk_size"]
        overlap = params["chunk_overlap"]
        label = f"{method}-{size}-{overlap}"

        logger.info("Evaluating %s ...", label)
        chunk_path = args.chunk_dir / row["filename"]
        chunk_df = pd.read_parquet(chunk_path)

        metrics = evaluate_config(chunk_df, qa_df, model, top_k=args.top_k)
        results.append({
            "config": label,
            "method": method,
            "chunk_size": size,
            "overlap": overlap,
            **metrics,
        })

        logger.info(
            "  %s: hit_rate=%.3f mrr=%.3f chunks=%d",
            label, metrics["hit_rate"], metrics["mrr"], metrics["chunk_count"],
        )

    results_df = pd.DataFrame(results).sort_values("hit_rate", ascending=False)
    results_df.to_csv(args.output, index=False)

    print("\n" + "=" * 80)
    print("RETRIEVAL EVALUATION RESULTS (sorted by hit_rate)")
    print("=" * 80)
    print(results_df.to_string(index=False))
    print(f"\nResults saved to: {args.output}")

    best = results_df.iloc[0]
    print(f"\nBest config: {best['config']} (hit_rate={best['hit_rate']:.3f}, mrr={best['mrr']:.3f}, chunks={best['chunk_count']})")


if __name__ == "__main__":
    main()
