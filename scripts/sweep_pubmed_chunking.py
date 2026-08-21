"""Chunking parameter sweep for the PubMed hypertension corpus.

Loops over 9 chunking configurations, re-ingests 10 PubMed articles per
config into a dedicated sweep table, evaluates retrieval against a
20-question QA dataset, and checkpoints results as JSON.

No catalog registration -- imports chunking/embedding/write functions
directly. The production table idx_pubmed_hypertension_v1 is never touched.

Usage:
    python scripts/sweep_pubmed_chunking.py
    python scripts/sweep_pubmed_chunking.py --data-dir /path/to/data
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from retrieval_hub.ingestion.chunking.bioc_section import chunk_bioc_document
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.embed import ChunkEmbedder
from retrieval_hub.ingestion.normalize import NormalizedDocument
from retrieval_hub.ingestion.parse import ParsedSection
from retrieval_hub.ingestion.write import count_rows, ensure_pgvector_schema, write_chunks

logger = logging.getLogger("sweep_pubmed_chunking")

SWEEP_TABLE = "idx_pubmed_hypertension_sweep"
EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"
EMBEDDING_DIMENSION = 768
DOCUMENT_PREFIX = ""
QUERY_PREFIX = ""
SKIP_SECTIONS = frozenset({"AUTH_CONT", "SUPPL", "REF", "COMP_INT"})

DEFAULT_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "pubmed-hypertension"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
)
QA_DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "eval" / "pubmed_hypertension" / "qa_dataset.json"
)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "eval" / "pubmed_hypertension"

SWEEP_CONFIGS = [
    {
        "config_id": "SA-512-0",
        "chunker": "bioc_section",
        "chunk_tokens": 512,
        "overlap_tokens": 0,
        "respect_section_boundaries": True,
    },
    {
        "config_id": "SA-512-0-NB",
        "chunker": "bioc_section",
        "chunk_tokens": 512,
        "overlap_tokens": 0,
        "respect_section_boundaries": False,
    },
    {
        "config_id": "SA-256-0",
        "chunker": "bioc_section",
        "chunk_tokens": 256,
        "overlap_tokens": 0,
        "respect_section_boundaries": True,
    },
    {
        "config_id": "SA-1024-0",
        "chunker": "bioc_section",
        "chunk_tokens": 1024,
        "overlap_tokens": 0,
        "respect_section_boundaries": True,
    },
    {
        "config_id": "SA-512-64",
        "chunker": "bioc_section",
        "chunk_tokens": 512,
        "overlap_tokens": 64,
        "respect_section_boundaries": True,
    },
    {
        "config_id": "SA-256-64",
        "chunker": "bioc_section",
        "chunk_tokens": 256,
        "overlap_tokens": 64,
        "respect_section_boundaries": True,
    },
    {"config_id": "TF-512-0", "chunker": "token_fixed", "chunk_tokens": 512, "overlap_tokens": 0},
    {"config_id": "TF-512-64", "chunker": "token_fixed", "chunk_tokens": 512, "overlap_tokens": 64},
    {"config_id": "TF-1024-0", "chunker": "token_fixed", "chunk_tokens": 1024, "overlap_tokens": 0},
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _load_articles(data_dir: Path) -> list[dict]:
    manifest_path = data_dir / "articles.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    articles = manifest.get("articles", [])
    if not articles:
        raise ValueError("no articles in manifest")
    return articles


def _build_slug_to_title(articles: list[dict]) -> dict[str, str]:
    return {f"{a['category']}/{a['slug']}": a["title"] for a in articles}


def _chunk_bioc(articles: list[dict], data_dir: Path, config: dict) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for article in articles:
        bioc_path = data_dir / "sources" / article["category"] / article["slug"] / "article.json"
        if not bioc_path.exists():
            logger.warning("BioC JSON not found for %s; skipping", article["slug"])
            continue
        bioc_data = json.loads(bioc_path.read_text(encoding="utf-8"))
        chunks = chunk_bioc_document(
            bioc_data,
            doc_url=article["pmc_url"],
            doc_title=article["title"],
            chunk_tokens=config["chunk_tokens"],
            overlap_tokens=config["overlap_tokens"],
            respect_section_boundaries=config.get("respect_section_boundaries", True),
            skip_sections=SKIP_SECTIONS,
        )
        all_chunks.extend(chunks)
    return all_chunks


def _chunk_token_fixed(articles: list[dict], data_dir: Path, config: dict) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for article in articles:
        md_path = data_dir / "extracted" / article["category"] / article["slug"] / "article.md"
        if not md_path.exists():
            logger.warning("markdown not found for %s; skipping", article["slug"])
            continue
        text = md_path.read_text(encoding="utf-8")

        sections: list[ParsedSection] = []
        for match in _HEADING_RE.finditer(text):
            sections.append(
                ParsedSection(
                    heading=match.group(2).strip(),
                    level=len(match.group(1)),
                    char_offset=match.start(),
                )
            )

        doc = NormalizedDocument(
            url=article["pmc_url"],
            title=article["title"],
            text=text,
            sections=sections,
        )
        chunks = chunk_document(
            doc,
            chunk_tokens=config["chunk_tokens"],
            overlap_tokens=config["overlap_tokens"],
        )
        all_chunks.extend(chunks)
    return all_chunks


def _embed_chunks(chunks: list[Chunk], embedder: ChunkEmbedder) -> list[list[float]]:
    return embedder.embed_chunks(chunks)


def _psycopg_dsn(vectors_db_url: str) -> str:
    return vectors_db_url.replace("postgresql+psycopg://", "postgresql://")


def _evaluate(
    vectors_db_url: str,
    qa_questions: list[dict],
    slug_to_title: dict[str, str],
    embedder: ChunkEmbedder,
) -> dict:
    dsn = _psycopg_dsn(vectors_db_url)
    results_per_question: list[dict] = []

    with psycopg.connect(dsn) as conn:
        register_vector(conn)

        for q in qa_questions:
            query_text = q["question"]
            expected_title = slug_to_title.get(q["source_doc"])
            if expected_title is None:
                continue

            query_vec = embedder._model.encode(
                [query_text],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]
            query_vec = np.array(query_vec, dtype=np.float32)

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT doc_title,
                           1 - (embedding <=> %s::vector) AS score
                    FROM {SWEEP_TABLE}
                    ORDER BY embedding <=> %s::vector
                    LIMIT 5
                    """,
                    (query_vec, query_vec),
                )
                rows = cur.fetchall()

            hit = False
            reciprocal_rank = 0.0
            top_score = rows[0][1] if rows else 0.0

            for rank, (doc_title, _score) in enumerate(rows, 1):
                if doc_title == expected_title:
                    hit = True
                    reciprocal_rank = 1.0 / rank
                    break

            results_per_question.append(
                {
                    "id": q["id"],
                    "question": query_text,
                    "expected_doc": expected_title[:80],
                    "hit": hit,
                    "reciprocal_rank": reciprocal_rank,
                    "top_score": float(top_score),
                }
            )

    n = len(results_per_question)
    if n == 0:
        return {"hit_rate_at_5": 0.0, "mrr_at_5": 0.0, "mean_score": 0.0, "per_question": []}

    hit_rate = sum(1 for r in results_per_question if r["hit"]) / n
    mrr = sum(r["reciprocal_rank"] for r in results_per_question) / n
    mean_score = sum(r["top_score"] for r in results_per_question) / n

    return {
        "hit_rate_at_5": round(hit_rate, 4),
        "mrr_at_5": round(mrr, 4),
        "mean_score": round(mean_score, 4),
        "per_question": results_per_question,
    }


def _print_summary_table(results: list[dict]) -> None:
    header = f"{'Config':<14} {'Chunks':>6} {'hit_rate@5':>10} {'MRR@5':>7} {'mean_score':>10}"
    sep = f"{'─' * 14} {'─' * 6} {'─' * 10} {'─' * 7} {'─' * 10}"
    print()
    print(header)
    print(sep)

    best = None
    best_hr = -1.0
    for r in results:
        if r.get("error"):
            print(f"{r['config_id']:<14} {'FAILED':>6} {'—':>10} {'—':>7} {'—':>10}")
            continue
        hr = r["hit_rate_at_5"]
        print(
            f"{r['config_id']:<14} {r['chunk_count']:>6} "
            f"{hr:>10.3f} {r['mrr_at_5']:>7.3f} {r['mean_score']:>10.3f}"
        )
        if hr > best_hr:
            best_hr = hr
            best = r["config_id"]

    print(sep)
    if best:
        print(f"Winner: {best} (hit_rate@5={best_hr:.3f})")
    print()


def _run_sweep(data_dir: Path, vectors_db_url: str) -> int:
    sweep_start = time.monotonic()

    articles = _load_articles(data_dir)
    logger.info("loaded %d articles from %s", len(articles), data_dir)

    slug_to_title = _build_slug_to_title(articles)

    qa_data = json.loads(QA_DATASET_PATH.read_text(encoding="utf-8"))
    # Filter to single-source questions only (exclude cross-dataset)
    qa_questions = [q for q in qa_data["questions"] if q.get("source_doc") != "cross-dataset"]
    logger.info("loaded %d single-source eval questions", len(qa_questions))

    logger.info("loading embedding model %s", EMBEDDING_MODEL)
    embedder = ChunkEmbedder(
        model_name=EMBEDDING_MODEL,
        document_prefix=DOCUMENT_PREFIX,
    )
    actual_dim = embedder.dimension

    ensure_pgvector_schema(vectors_db_url, SWEEP_TABLE, actual_dim)

    checkpoint_dir = OUTPUT_DIR / "sweep_configs"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[dict] = []

    for i, config in enumerate(SWEEP_CONFIGS, 1):
        cid = config["config_id"]
        logger.info("[%d/%d] starting config %s", i, len(SWEEP_CONFIGS), cid)
        config_start = time.monotonic()

        try:
            if config["chunker"] == "bioc_section":
                chunks = _chunk_bioc(articles, data_dir, config)
            else:
                chunks = _chunk_token_fixed(articles, data_dir, config)

            logger.info("config %s: %d chunks", cid, len(chunks))

            embeddings = _embed_chunks(chunks, embedder)
            write_chunks(vectors_db_url, SWEEP_TABLE, chunks, embeddings, replace=True)
            row_count = count_rows(vectors_db_url, SWEEP_TABLE)
            logger.info("config %s: %d rows in sweep table", cid, row_count)

            eval_result = _evaluate(vectors_db_url, qa_questions, slug_to_title, embedder)
            config_elapsed = time.monotonic() - config_start

            result = {
                "config_id": cid,
                **config,
                "chunk_count": len(chunks),
                "row_count": row_count,
                **eval_result,
                "elapsed_s": round(config_elapsed, 1),
            }
            # Remove per_question from the top-level summary to keep it concise
            summary = {k: v for k, v in result.items() if k != "per_question"}

            logger.info(
                "config %s: hit_rate=%.3f mrr=%.3f mean_score=%.3f (%.1fs)",
                cid,
                eval_result["hit_rate_at_5"],
                eval_result["mrr_at_5"],
                eval_result["mean_score"],
                config_elapsed,
            )

        except Exception:
            config_elapsed = time.monotonic() - config_start
            logger.exception("config %s failed after %.1fs", cid, config_elapsed)
            result = {
                "config_id": cid,
                **config,
                "error": True,
                "elapsed_s": round(config_elapsed, 1),
            }
            summary = result

        all_results.append(summary)

        checkpoint_path = checkpoint_dir / f"{cid}.json"
        checkpoint_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    sweep_elapsed = time.monotonic() - sweep_start

    aggregate = {
        "sweep_elapsed_s": round(sweep_elapsed, 1),
        "embedding_model": EMBEDDING_MODEL,
        "sweep_table": SWEEP_TABLE,
        "configs_run": len(SWEEP_CONFIGS),
        "results": all_results,
    }
    aggregate_path = OUTPUT_DIR / "sweep_results.json"
    aggregate_path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    logger.info("wrote aggregate results to %s", aggregate_path)

    _print_summary_table(all_results)
    print(f"Total sweep time: {sweep_elapsed:.1f}s")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chunking parameter sweep for PubMed hypertension corpus."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Path to pubmed-hypertension data source. Default: {DEFAULT_DATA_DIR}",
    )
    parser.add_argument(
        "--vectors-db-url",
        default=DEFAULT_VECTORS_DB_URL,
        help=f"SQLAlchemy URL for vectors DB. Default: {DEFAULT_VECTORS_DB_URL}",
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

    return _run_sweep(data_dir=args.data_dir, vectors_db_url=args.vectors_db_url)


if __name__ == "__main__":
    sys.exit(main())
