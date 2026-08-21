"""Chunking parameter sweep for the aircraft maintenance corpus.

Loops over 6 chunking configurations (token-fixed only), re-ingests the
Piper Cherokee and Saratoga service bulletin collections per config into
a dedicated sweep table, evaluates retrieval against a 20-question QA
dataset (5 cross-dataset questions excluded), and checkpoints results as JSON.

No catalog registration -- imports chunking/embedding/write functions
directly. The production table idx_aircraft_maintenance_v1 is never touched.

Usage:
    python scripts/sweep_aircraft_chunking.py --embedding-endpoint URL
    python scripts/sweep_aircraft_chunking.py --local-embedding
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

from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.embed import ChunkEmbedder, QueryEmbedder
from retrieval_hub.ingestion.normalize import NormalizedDocument, normalize_document
from retrieval_hub.ingestion.parse import ParsedDocument, ParsedSection
from retrieval_hub.ingestion.write import count_rows, ensure_pgvector_schema, write_chunks

logger = logging.getLogger("sweep_aircraft_chunking")

SWEEP_TABLE = "idx_aircraft_maintenance_sweep"
EMBEDDING_MODEL = "Snowflake/snowflake-arctic-embed-m-v1.5"
EMBEDDING_DIMENSION = 768
DOCUMENT_PREFIX = ""
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

DEFAULT_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "aircraft-maintenance"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)
QA_DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "eval" / "aircraft_maintenance" / "qa_dataset.json"
)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "eval" / "aircraft_maintenance"

# Aircraft families to ingest, keyed by subdirectory name.
AIRCRAFT_FAMILIES: dict[str, str] = {
    "piper-cherokee": "Cherokee",
    "piper-saratoga": "Saratoga",
}

# Files to skip -- reference/index documents, not individual bulletins.
SKIP_STEMS: set[str] = {
    "Customer-Service-Info",
    "Service-Bulletin-Letter-Index",
    "Owner-Publications-Catalog",
    "urls",
}

SWEEP_CONFIGS = [
    {"config_id": "TF-512-64", "chunk_tokens": 512, "overlap_tokens": 64},
    {"config_id": "TF-512-0", "chunk_tokens": 512, "overlap_tokens": 0},
    {"config_id": "TF-256-0", "chunk_tokens": 256, "overlap_tokens": 0},
    {"config_id": "TF-256-64", "chunk_tokens": 256, "overlap_tokens": 64},
    {"config_id": "TF-1024-0", "chunk_tokens": 1024, "overlap_tokens": 0},
    {"config_id": "TF-1024-128", "chunk_tokens": 1024, "overlap_tokens": 128},
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Document loading (adapted from ingest_aircraft_maintenance.py)
# ---------------------------------------------------------------------------


def _make_doc_url(family_key: str, stem: str) -> str:
    aircraft = family_key.split("-", 1)[1] if "-" in family_key else family_key
    return f"piper://{aircraft}/{stem}"


def _make_doc_title(stem: str, family_label: str) -> str:
    return f"{stem} ({family_label})"


def _extract_sections_from_markdown(text: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    for match in _HEADING_RE.finditer(text):
        sections.append(
            ParsedSection(
                heading=match.group(2).strip(),
                level=len(match.group(1)),
                char_offset=match.start(),
            )
        )
    return sections


def _load_documents(data_dir: Path) -> list[NormalizedDocument]:
    """Load and normalize all aircraft maintenance documents."""
    documents: list[NormalizedDocument] = []
    skipped_short = 0

    for family_key, family_label in AIRCRAFT_FAMILIES.items():
        extracted_dir = data_dir / family_key / "extracted"
        manifest_path = extracted_dir / "manifest.json"

        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest not found at {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        logger.info(
            "loaded manifest for %s with %d entries from %s",
            family_label, len(manifest), manifest_path,
        )

        for entry in manifest:
            stem = Path(entry["source_path"]).stem
            if stem in SKIP_STEMS:
                continue

            md_path = extracted_dir / f"{stem}.md"
            if not md_path.exists():
                logger.warning("markdown not found for %s at %s; skipping", stem, md_path)
                continue

            raw_text = md_path.read_text(encoding="utf-8")
            doc_title = _make_doc_title(stem, family_label)
            doc_url = _make_doc_url(family_key, stem)

            sections = _extract_sections_from_markdown(raw_text)
            parsed = ParsedDocument(
                url=doc_url,
                title=doc_title,
                text=raw_text,
                content_type="text/markdown",
                sections=sections,
                metadata={"parser": "docling", "family": family_label},
            )

            normalized = normalize_document(parsed)
            if normalized is None:
                logger.debug("skipping short document: %s (%d chars)", doc_title, len(raw_text))
                skipped_short += 1
                continue

            documents.append(normalized)

    logger.info(
        "loaded %d documents (%d skipped as too short) across all families",
        len(documents), skipped_short,
    )
    if not documents:
        raise ValueError("no documents found in data directory")

    return documents


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_documents(
    documents: list[NormalizedDocument],
    config: dict,
) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for doc in documents:
        chunks = chunk_document(
            doc,
            chunk_tokens=config["chunk_tokens"],
            overlap_tokens=config["overlap_tokens"],
        )
        all_chunks.extend(chunks)
    return all_chunks


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _evaluate(
    vectors_db_url: str,
    qa_questions: list[dict],
    query_embedder: QueryEmbedder,
) -> dict:
    """Evaluate retrieval quality against the QA dataset."""
    dsn = vectors_db_url.replace("postgresql+psycopg://", "postgresql://")
    results_per_question: list[dict] = []

    with psycopg.connect(dsn) as conn:
        register_vector(conn)

        for q in qa_questions:
            query_text = q["question"]
            expected_title = q["expected_doc_title"]
            if expected_title is None:
                continue

            query_vec = np.array(query_embedder.embed(query_text), dtype=np.float32)

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


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------


def _run_sweep(
    data_dir: Path,
    embedding_endpoint: str | None,
    vectors_db_url: str,
) -> int:
    sweep_start = time.monotonic()

    documents = _load_documents(data_dir)
    logger.info("loaded %d documents from %s", len(documents), data_dir)

    qa_data = json.loads(QA_DATASET_PATH.read_text(encoding="utf-8"))
    qa_questions = [q for q in qa_data["questions"] if q.get("query_type") != "cross_dataset"]
    logger.info("loaded %d single-source eval questions", len(qa_questions))

    backend_label = f"remote ({embedding_endpoint})" if embedding_endpoint else "local (sentence-transformers)"
    logger.info("initializing embedding: model=%s backend=%s", EMBEDDING_MODEL, backend_label)
    chunk_embedder = ChunkEmbedder(
        model_name=EMBEDDING_MODEL,
        endpoint=embedding_endpoint,
        document_prefix=DOCUMENT_PREFIX,
    )
    query_embedder = QueryEmbedder(
        model_name=EMBEDDING_MODEL,
        endpoint=embedding_endpoint,
        query_prefix=QUERY_PREFIX,
    )
    actual_dim = chunk_embedder.dimension

    ensure_pgvector_schema(vectors_db_url, SWEEP_TABLE, actual_dim)

    checkpoint_dir = OUTPUT_DIR / "sweep_configs"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[dict] = []

    for i, config in enumerate(SWEEP_CONFIGS, 1):
        cid = config["config_id"]
        logger.info("[%d/%d] starting config %s", i, len(SWEEP_CONFIGS), cid)
        config_start = time.monotonic()

        try:
            chunks = _chunk_documents(documents, config)
            logger.info("config %s: %d chunks", cid, len(chunks))

            embeddings = chunk_embedder.embed_chunks(chunks)
            write_chunks(vectors_db_url, SWEEP_TABLE, chunks, embeddings, replace=True)
            row_count = count_rows(vectors_db_url, SWEEP_TABLE)
            logger.info("config %s: %d rows in sweep table", cid, row_count)

            eval_result = _evaluate(vectors_db_url, qa_questions, query_embedder)
            config_elapsed = time.monotonic() - config_start

            result = {
                "config_id": cid,
                **config,
                "chunk_count": len(chunks),
                "row_count": row_count,
                **eval_result,
                "elapsed_s": round(config_elapsed, 1),
            }
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
        "embedding_endpoint": embedding_endpoint or "local",
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chunking parameter sweep for aircraft maintenance corpus."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Path to aircraft-maintenance data directory. Default: {DEFAULT_DATA_DIR}",
    )
    parser.add_argument(
        "--embedding-endpoint",
        default=None,
        help="Base URL of an OpenAI-compatible embedding endpoint (e.g. https://vllm-host:8000).",
    )
    parser.add_argument(
        "--local-embedding",
        action="store_true",
        help="Use local sentence-transformers instead of a remote endpoint.",
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

    if not args.embedding_endpoint and not args.local_embedding:
        parser.error("provide --embedding-endpoint or --local-embedding")

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    endpoint = None if args.local_embedding else args.embedding_endpoint
    return _run_sweep(
        data_dir=args.data_dir,
        embedding_endpoint=endpoint,
        vectors_db_url=args.vectors_db_url,
    )


if __name__ == "__main__":
    sys.exit(main())
