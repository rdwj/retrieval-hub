"""Chunking parameter sweep for the VA CPG corpus with Nomic v1.5.

Retrieval-only evaluation: embeds queries with Nomic v1.5 and runs vector
similarity search against pre-built index tables. Reports hit_rate@5,
MRR@5, and mean cosine similarity for each configuration.

Prerequisite: run ingest_va_cpg_alt_embedding.py with different --chunk-tokens
and --overlap-tokens to create the index tables first.

Usage:
    python scripts/sweep_va_cpg_chunking.py
    python scripts/sweep_va_cpg_chunking.py --configs 256_0 512_64
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from retrieval_hub.ingestion.embed import ChunkEmbedder

logger = logging.getLogger("sweep_va_cpg_chunking")

EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "

QA_DATASET_PATH = Path("eval/autorag/qa_dataset_draft.json")
OUTPUT_DIR = Path("eval/va_cpg_chunking_sweep")

DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)

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

ALL_CONFIGS = {
    "256_0": {"table": "idx_va_cpg_nomic_256_0", "chunk_tokens": 256, "overlap": 0},
    "512_0": {"table": "idx_va_cpg_nomic_v1", "chunk_tokens": 512, "overlap": 0},
    "512_64": {"table": "idx_va_cpg_nomic_512_64", "chunk_tokens": 512, "overlap": 64},
    "1024_0": {"table": "idx_va_cpg_nomic_1024_0", "chunk_tokens": 1024, "overlap": 0},
}


def _psycopg_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _load_eval_queries() -> list[dict]:
    import random
    data = json.loads(QA_DATASET_PATH.read_text(encoding="utf-8"))
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
    return any(kw in doc_title.lower() for kw in keywords)


def _retrieve(
    table: str,
    query_vec: np.ndarray,
    vectors_db_url: str,
    top_k: int = 5,
) -> list[dict]:
    dsn = _psycopg_dsn(vectors_db_url)
    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT chunk_text, doc_title, doc_section,
                       1 - (embedding <=> %s::vector) AS score
                FROM {table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, query_vec, top_k),
            )
            return [
                {"text": row[0], "doc_title": row[1], "doc_section": row[2], "score": float(row[3])}
                for row in cur.fetchall()
            ]


def _table_exists(table: str, vectors_db_url: str) -> bool:
    dsn = _psycopg_dsn(vectors_db_url)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                (table,),
            )
            return cur.fetchone()[0]


def _count_rows(table: str, vectors_db_url: str) -> int:
    dsn = _psycopg_dsn(vectors_db_url)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]


def _run(args: argparse.Namespace) -> int:
    wall_start = time.monotonic()

    configs_to_run = args.configs if args.configs else list(ALL_CONFIGS.keys())
    configs = {k: ALL_CONFIGS[k] for k in configs_to_run if k in ALL_CONFIGS}

    if not configs:
        logger.error("no valid configs specified; available: %s", list(ALL_CONFIGS.keys()))
        return 1

    for config_id, cfg in list(configs.items()):
        if not _table_exists(cfg["table"], args.vectors_db_url):
            logger.warning("table %s does not exist; skipping config %s", cfg["table"], config_id)
            del configs[config_id]

    if not configs:
        logger.error("no tables found; run ingestion first")
        return 1

    queries = _load_eval_queries()
    logger.info("loaded %d eval queries", len(queries))

    logger.info("loading embedding model %s", EMBEDDING_MODEL)
    embedder = ChunkEmbedder(model_name=EMBEDDING_MODEL, document_prefix=DOCUMENT_PREFIX)

    query_vecs = []
    for q in queries:
        vec = embedder._model.encode(
            [QUERY_PREFIX + q["question"]],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        query_vecs.append(np.array(vec, dtype=np.float32))
    logger.info("embedded %d queries", len(query_vecs))

    results = {}
    for config_id, cfg in configs.items():
        chunk_count = _count_rows(cfg["table"], args.vectors_db_url)
        logger.info(
            "evaluating config %s (table=%s, chunks=%d)",
            config_id, cfg["table"], chunk_count,
        )

        hits_at_k = 0
        reciprocal_ranks = []
        scores_all = []

        for i, (q, qvec) in enumerate(zip(queries, query_vecs)):
            hits = _retrieve(cfg["table"], qvec, args.vectors_db_url, TOP_K)
            scores_all.extend(h["score"] for h in hits)

            hit_found = False
            for rank, h in enumerate(hits, 1):
                if _chunk_matches_source(h["doc_title"], q["cpg_slug"]):
                    if not hit_found:
                        reciprocal_ranks.append(1.0 / rank)
                        hit_found = True
                    hits_at_k += 1
                    break

            if not hit_found:
                reciprocal_ranks.append(0.0)

        n = len(queries)
        hit_rate = hits_at_k / n
        mrr = sum(reciprocal_ranks) / n
        mean_score = sum(scores_all) / len(scores_all) if scores_all else 0.0

        results[config_id] = {
            "table": cfg["table"],
            "chunk_tokens": cfg["chunk_tokens"],
            "overlap": cfg["overlap"],
            "chunk_count": chunk_count,
            "hit_rate_at_5": round(hit_rate, 4),
            "mrr_at_5": round(mrr, 4),
            "mean_cosine_sim": round(mean_score, 4),
        }
        logger.info(
            "  %s: hit_rate=%.3f  mrr=%.3f  mean_sim=%.3f  chunks=%d",
            config_id, hit_rate, mrr, mean_score, chunk_count,
        )

    wall_time = time.monotonic() - wall_start

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {"date": time.strftime("%Y-%m-%d"), "results": results}
    output_path = OUTPUT_DIR / "sweep_results.json"
    output_path.write_text(json.dumps(output, indent=2) + "\n")

    print()
    print("=" * 72)
    print("VA CPG Chunking Sweep Results (Nomic v1.5)")
    print("=" * 72)
    print(f"  {'Config':<12} {'Chunks':>8} {'Hit@5':>8} {'MRR@5':>8} {'MeanSim':>8}")
    print("-" * 72)
    for config_id, r in results.items():
        print(
            f"  {config_id:<12} {r['chunk_count']:>8} "
            f"{r['hit_rate_at_5']:>8.3f} {r['mrr_at_5']:>8.3f} "
            f"{r['mean_cosine_sim']:>8.3f}"
        )
    print("=" * 72)
    print(f"  Wall time: {wall_time:.1f}s")
    print(f"  Output:    {output_path}")
    print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--configs", nargs="*", default=None,
        help=f"Config IDs to evaluate. Default: all ({list(ALL_CONFIGS.keys())})",
    )
    parser.add_argument(
        "--vectors-db-url", default=DEFAULT_VECTORS_DB_URL,
        help=f"Vectors DB URL. Default: {DEFAULT_VECTORS_DB_URL}",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
