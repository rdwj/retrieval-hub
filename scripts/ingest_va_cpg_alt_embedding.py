"""Re-ingest the VA CPG corpus with a different embedding model.

Parameterized variant of ingest_va_cpg.py for embedding model comparison
experiments. Same corpus, same chunking (512/0), different embedding model
and pgvector target table. Updates the source's active physical index pointer
so the eval pipeline picks up the new index automatically.

Usage:

    python scripts/ingest_va_cpg_alt_embedding.py \
      --embedding-model FremyCompany/BioLORD-2023 \
      --pgvector-table idx_va_cpg_biolord_v1

    python scripts/ingest_va_cpg_alt_embedding.py \
      --embedding-model nomic-ai/nomic-embed-text-v1.5 \
      --pgvector-table idx_va_cpg_nomic_v1 \
      --document-prefix "search_document: " \
      --query-prefix "search_query: "
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.fetch import FetchError, load_corpus_tree
from retrieval_hub.ingestion.normalize import normalize_document
from retrieval_hub.ingestion.parse import parse_document
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger("ingest_va_cpg_alt_embedding")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
SOURCE_NAME = "VA/DoD Clinical Practice Guidelines"
DESCRIPTION_SHORT = (
    "52 clinical practice guidelines from the VA/DoD covering chronic disease, "
    "mental health, pain management, rehabilitation, and women's health."
)
SOURCE_OWNER_TEAM = "ai-americas"
SOURCE_OWNER_CONTACTS = ["ai-americas@example.com"]

CHUNK_TOKENS = 512
OVERLAP_TOKENS = 0

DEFAULT_DATA_SOURCE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "va-cpg"
)
DEFAULT_CORPUS_DIR = DEFAULT_DATA_SOURCE_DIR / "extracted"
DEFAULT_PDF_URLS = DEFAULT_DATA_SOURCE_DIR / "pdf-urls.json"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
)

SAMPLE_PROMPTS: list[tuple[str, str]] = [
    (
        "claude-*",
        (
            "You are a clinical reference assistant with access to VA/DoD Clinical Practice Guidelines. "
            "When answering questions:\n"
            "1. Retrieve relevant guideline content using the retrieve tool.\n"
            "2. Cite the specific CPG title and section for every recommendation.\n"
            "3. Note the strength of each recommendation if provided in the source.\n"
            "4. Clarify that these are VA/DoD guidelines which may differ from other organizations'.\n"
            "5. If the retrieved content doesn't address the question, say so explicitly."
        ),
    ),
]

USAGE_RULES: dict = {
    "citation": (
        "Always cite the VA.gov source URL (provided in doc_url) along with "
        "the CPG title, section, and recommendation number when referencing "
        "clinical guidance from this source."
    ),
    "scope_disclaimer": (
        "These are VA/DoD Clinical Practice Guidelines developed jointly by "
        "the Department of Veterans Affairs and Department of Defense. "
        "Recommendations may differ from other organizations' guidelines "
        "(e.g., ACC/AHA, ESC, USPSTF). Always note this when presenting "
        "recommendations."
    ),
    "handling": (
        "Content is for clinical reference only and does not replace "
        "clinical judgment. Do not present guideline recommendations as "
        "direct medical advice."
    ),
    "custom_rules": [
        "When a recommendation includes a strength rating (Strong for, Weak for, etc.), always include it.",
        "If the retrieved content does not address the user's question, say so explicitly rather than extrapolating.",
        "When citing specific recommendations, use the recommendation number (e.g., 'Recommendation 7').",
    ],
}

DATA_FRESHNESS: dict = {
    "source_name": "VA/DoD Clinical Practice Guidelines",
    "source_url": "https://www.healthquality.va.gov/",
    "last_refreshed": "2026-08-13",
    "refresh_cadence": "on_demand",
    "staleness_note": (
        "Guidelines are updated periodically by VA/DoD working groups. "
        "Check healthquality.va.gov for the most current versions."
    ),
}


def _build_source_url_map(pdf_urls_path: Path) -> dict[str, str]:
    if not pdf_urls_path.exists():
        logger.warning("pdf-urls.json not found at %s; using file:// URLs", pdf_urls_path)
        return {}
    data = json.loads(pdf_urls_path.read_text(encoding="utf-8"))
    url_map: dict[str, str] = {}
    for cpg in data.get("cpgs", []):
        slug = cpg["slug"]
        if cpg.get("full_guideline_url"):
            url_map[f"{slug}/full-guideline"] = cpg["full_guideline_url"]
        if cpg.get("clinician_summary_url"):
            url_map[f"{slug}/clinician-summary"] = cpg["clinician_summary_url"]
        if cpg.get("index_url"):
            url_map[f"{slug}/index"] = cpg["index_url"]
    logger.info("built source URL map with %d entries from %s", len(url_map), pdf_urls_path)
    return url_map


def _recipe_content(
    embedding_model: str,
    embedding_dimension: int,
    document_prefix: str,
    query_prefix: str,
    pgvector_table: str,
) -> dict:
    return {
        "parser": {"kind": "markdown_passthrough"},
        "chunker": {
            "kind": "token_fixed",
            "chunk_size_tokens": CHUNK_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
            "encoding": "cl100k_base",
        },
        "embedding": {
            "model": embedding_model,
            "dimension": embedding_dimension,
            "normalize": True,
            "document_prefix": document_prefix,
            "query_prefix": query_prefix,
        },
        "backend": {
            "kind": "pgvector",
            "table": pgvector_table,
        },
        "retrieval": {
            "default_pattern": "vector_ann",
            "supported_patterns": ["vector_ann"],
            "parameters": {
                "vector_ann": {"top_k_default": 10, "top_k_max": 50},
            },
        },
    }


def _run_ingestion(args: argparse.Namespace) -> int:
    wall_start = time.monotonic()

    embedding_model = args.embedding_model
    pgvector_table = args.pgvector_table
    document_prefix = args.document_prefix
    query_prefix = args.query_prefix
    corpus_dir = args.corpus_dir

    description_long = (
        f"A curated ingestion of the VA/DoD Clinical Practice Guidelines corpus "
        f"covering five clinical categories. This variant uses {embedding_model} "
        f"for embeddings (eval comparison). Chunked at {CHUNK_TOKENS} tokens, "
        f"0 overlap, stored in pgvector table {pgvector_table}."
    )

    pdf_urls_path = corpus_dir.parent / "pdf-urls.json"
    url_map = _build_source_url_map(pdf_urls_path)

    logger.info("loading corpus tree from %s", corpus_dir)
    try:
        raw_docs = load_corpus_tree(corpus_dir, url_map=url_map)
    except FetchError as exc:
        logger.error("corpus load failed: %s", exc)
        return 1
    logger.info("fetched %d documents from corpus_tree", len(raw_docs))

    if not raw_docs:
        logger.error("no documents found in %s; aborting", corpus_dir)
        return 1

    normalized = []
    for raw in raw_docs:
        parsed = parse_document(raw)
        norm = normalize_document(parsed)
        if norm is None:
            logger.info("skipping empty/short document url=%s", raw.url)
            continue
        normalized.append(norm)
    logger.info("normalized %d documents", len(normalized))

    if not normalized:
        logger.error("no documents survived normalization; aborting")
        return 1

    all_chunks: list[Chunk] = []
    for norm in normalized:
        chunks = chunk_document(
            norm,
            chunk_tokens=CHUNK_TOKENS,
            overlap_tokens=OVERLAP_TOKENS,
        )
        all_chunks.extend(chunks)
    logger.info("produced %d chunks total", len(all_chunks))

    if not all_chunks:
        logger.error("no chunks produced; aborting")
        return 1

    from retrieval_hub.ingestion.embed import ChunkEmbedder

    embed_start = time.monotonic()
    embedder = ChunkEmbedder(
        model_name=embedding_model,
        document_prefix=document_prefix,
        batch_size=args.batch_size,
    )
    actual_dim = embedder.dimension
    logger.info("embedding model %s, dimension=%d", embedding_model, actual_dim)

    embeddings = embedder.embed_chunks(all_chunks)
    embed_elapsed = time.monotonic() - embed_start
    logger.info(
        "embedded %d chunks in %.1fs (%.1f chunks/s)",
        len(embeddings),
        embed_elapsed,
        (len(embeddings) / embed_elapsed) if embed_elapsed > 0 else 0.0,
    )

    ensure_pgvector_schema(args.vectors_db_url, pgvector_table, actual_dim)
    write_stats = write_chunks(
        args.vectors_db_url,
        pgvector_table,
        all_chunks,
        embeddings,
    )
    logger.info(
        "wrote %d rows to %s (%d tokens)",
        write_stats.rows_written,
        write_stats.table,
        write_stats.total_tokens,
    )

    recipe = _recipe_content(
        embedding_model, actual_dim, document_prefix, query_prefix, pgvector_table,
    )

    session_factory = make_session_factory(create_db_engine(args.db_url))
    with session_factory() as session:
        result = register_document_source(
            session,
            slug=SOURCE_SLUG,
            name=SOURCE_NAME,
            description_short=DESCRIPTION_SHORT,
            description_long=description_long,
            owner_team=SOURCE_OWNER_TEAM,
            owner_contacts=SOURCE_OWNER_CONTACTS,
            recipe_content=recipe,
            physical_index_location=pgvector_table,
            document_count=len(normalized),
            chunk_count=len(all_chunks),
            sample_prompts=SAMPLE_PROMPTS,
            usage_rules={**USAGE_RULES, "data_freshness": DATA_FRESHNESS},
            triggered_by=f"script:ingest_va_cpg_alt_embedding({embedding_model})",
            family=SourceFamily.CLINICAL_DOCUMENT,
        )

    wall_elapsed = time.monotonic() - wall_start

    print()
    print("=" * 72)
    print("VA CPG alt-embedding ingestion complete")
    print("=" * 72)
    print(f"  Embedding model      : {embedding_model}")
    print(f"  Embedding dimension  : {actual_dim}")
    print(f"  Document prefix      : {document_prefix!r}")
    print(f"  Query prefix         : {query_prefix!r}")
    print(f"  pgvector table       : {pgvector_table}")
    print(f"  Documents            : {len(normalized)}")
    print(f"  Chunks               : {len(all_chunks)}")
    print(f"  Tokens embedded      : {write_stats.total_tokens}")
    print()
    print(f"  Source slug          : {result.source_slug}")
    print(f"  Recipe version       : v{result.recipe_version_number}")
    print(f"  Physical index       : {result.physical_index_id}")
    print(f"  Active index updated : yes")
    print()
    print(f"  Total wall time      : {wall_elapsed:.1f}s")
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-ingest VA CPG corpus with a different embedding model.",
    )
    parser.add_argument(
        "--embedding-model", required=True,
        help="HuggingFace model name (e.g., FremyCompany/BioLORD-2023)",
    )
    parser.add_argument(
        "--pgvector-table", required=True,
        help="Target pgvector table name (e.g., idx_va_cpg_biolord_v1)",
    )
    parser.add_argument(
        "--document-prefix", default="",
        help='Prefix for document text during embedding (default: "" = none)',
    )
    parser.add_argument(
        "--query-prefix", default="",
        help='Prefix for queries at retrieval time (default: "" = none)',
    )
    parser.add_argument(
        "--batch-size", type=int, default=32,
        help="Embedding batch size (reduce for large models, default: 32)",
    )
    parser.add_argument(
        "--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR,
        help=f"Path to extracted VA CPG corpus. Default: {DEFAULT_CORPUS_DIR}",
    )
    parser.add_argument(
        "--db-url", default=DEFAULT_DB_URL,
        help=f"Catalog DB URL. Default: {DEFAULT_DB_URL}",
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

    return _run_ingestion(args)


if __name__ == "__main__":
    sys.exit(main())
