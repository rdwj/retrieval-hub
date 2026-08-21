"""Ingest the Project Gutenberg edition of A Tale of Two Cities.

Ingests the HTML file of Charles Dickens's *A Tale of Two Cities* into the
retrieval-hub catalog and a local pgvector physical index. The HTML is parsed
via Docling, chunked at 512 tokens with no overlap, and embedded with
nomic-embed-text-v1.5 for general-purpose vector search.

The script expects the HTML file in a sibling repository
(retrieval-hub-data-sources/tale-of-two-cities/). Use ``--html-file`` to
override that default.

Usage:

    # 1. Start local dependencies (Ansible playbooks)
    ansible-playbook -i deploy/ansible/inventory/local \\
      deploy/ansible/playbooks/local_all_up.yml

    # 2. Apply catalog migrations (one time)
    make migrate

    # 3. Run ingestion
    python scripts/ingest_tale_of_two_cities.py

    # 4. Or point at a different HTML file
    python scripts/ingest_tale_of_two_cities.py \\
      --html-file /path/to/98-h.htm

The script reports a summary at the end: doc/chunk counts, Source UUID,
pgvector table name, and the exact command to seed semantic context next.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.fetch import FetchedDocument
from retrieval_hub.ingestion.normalize import normalize_document
from retrieval_hub.ingestion.parse import parse_document
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger("ingest_tale_of_two_cities")

SOURCE_SLUG = "tale-of-two-cities"
SOURCE_NAME = "A Tale of Two Cities"
DESCRIPTION_SHORT = (
    "Charles Dickens's A Tale of Two Cities (1859), a novel of the French "
    "Revolution spanning 3 books and 45 chapters. Project Gutenberg edition."
)
DESCRIPTION_LONG = (
    "A Tale of Two Cities by Charles Dickens, published in 1859, set against "
    "the backdrop of the French Revolution. The novel follows characters "
    "across London and Paris — Sydney Carton, Charles Darnay, Lucie Manette, "
    "Doctor Manette, and Madame Defarge — through themes of sacrifice, "
    "resurrection, and revolution. Ingested from the Project Gutenberg HTML "
    "edition using Docling for HTML parsing, token-fixed chunking at 512/0, "
    "and nomic-embed-text-v1.5 for general-purpose embeddings stored in pgvector."
)
SOURCE_OWNER_TEAM = "ai-americas"
SOURCE_OWNER_CONTACTS = ["ai-americas@example.com"]

PGVECTOR_TABLE = "idx_tale_two_cities_v1"
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIMENSION = 768
CHUNK_TOKENS = 512
OVERLAP_TOKENS = 0
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

DEFAULT_HTML_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "tale-of-two-cities"
    / "A Tale of Two Cities _ Project Gutenberg.html"
)

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)

SAMPLE_PROMPTS: list[tuple[str, str]] = [
    (
        "claude-*",
        (
            "You are a literary analysis assistant with access to A Tale of Two Cities. "
            "When answering questions:\n"
            "1. Retrieve relevant passages using the retrieve tool.\n"
            "2. Cite the book and chapter number for every reference.\n"
            "3. Use the refine tool with entity_arc strategy to trace character arcs.\n"
            "4. Consider the historical context of the French Revolution when interpreting themes.\n"
            "5. If the retrieved content doesn't address the question, say so explicitly."
        ),
    ),
]

USAGE_RULES: dict = {
    "citation": (
        "Always cite the book number and chapter (e.g., 'Book the Second, "
        "Chapter 3') when referencing content from this source."
    ),
    "scope_disclaimer": (
        "This is the Project Gutenberg edition of A Tale of Two Cities. "
        "Text may differ from other published editions."
    ),
    "handling": (
        "This is a public domain literary work. Content may be freely quoted "
        "and discussed without restriction."
    ),
    "custom_rules": [],
}

DATA_FRESHNESS: dict = {
    "source_name": "Project Gutenberg",
    "source_url": "https://www.gutenberg.org/ebooks/98",
    "last_refreshed": "2026-08-20",
    "refresh_cadence": "static",
    "staleness_note": (
        "Public domain work. Content is static and will not change."
    ),
}


def _recipe_content() -> dict:
    """Return the recipe content dict that will be stored on RecipeVersion."""
    return {
        "parser": {"kind": "html_docling"},
        "chunker": {
            "kind": "token_fixed",
            "chunk_size_tokens": CHUNK_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
            "encoding": "cl100k_base",
        },
        "embedding": {
            "model": EMBEDDING_MODEL,
            "dimension": EMBEDDING_DIMENSION,
            "normalize": True,
            "document_prefix": DOCUMENT_PREFIX,
            "query_prefix": QUERY_PREFIX,
        },
        "backend": {
            "kind": "pgvector",
            "table": PGVECTOR_TABLE,
        },
        "retrieval": {
            "default_pattern": "vector_ann",
            "supported_patterns": ["vector_ann"],
            "parameters": {
                "vector_ann": {"top_k_default": 10, "top_k_max": 50},
            },
        },
    }


def _run_ingestion(html_file: Path, db_url: str, vectors_db_url: str) -> int:
    """Execute the full ingestion pipeline end-to-end."""
    wall_start = time.monotonic()

    # Stage 1: fetch (load from local HTML file).
    html_path = Path(html_file)
    if not html_path.exists():
        logger.error("HTML file not found: %s", html_path)
        return 1

    raw_bytes = html_path.read_bytes()
    raw_doc = FetchedDocument(
        url="https://www.gutenberg.org/files/98/98-h/98-h.htm",
        title="A Tale of Two Cities",
        content="",
        content_type="text/html",
        raw_bytes=raw_bytes,
        metadata={"source": "project_gutenberg", "author": "Charles Dickens"},
    )
    raw_docs = [raw_doc]
    logger.info("loaded HTML file from %s (%d bytes)", html_path, len(raw_bytes))

    # Stages 2 + 3: parse, normalize.
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

    # Stage 4: chunk.
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

    # Stage 5: embed.
    from retrieval_hub.ingestion.embed import ChunkEmbedder

    embed_start = time.monotonic()
    embedder = ChunkEmbedder(
        model_name=EMBEDDING_MODEL,
        document_prefix=DOCUMENT_PREFIX,
    )
    actual_dim = embedder.dimension
    if actual_dim != EMBEDDING_DIMENSION:
        logger.warning(
            "embedding model %s reported dimension=%d, recipe expected %d",
            EMBEDDING_MODEL,
            actual_dim,
            EMBEDDING_DIMENSION,
        )
    embeddings = embedder.embed_chunks(all_chunks)
    embed_elapsed = time.monotonic() - embed_start
    logger.info(
        "embedded %d chunks in %.1fs (%.1f chunks/s)",
        len(embeddings),
        embed_elapsed,
        (len(embeddings) / embed_elapsed) if embed_elapsed > 0 else 0.0,
    )

    # Stage 6: write to pgvector.
    ensure_pgvector_schema(vectors_db_url, PGVECTOR_TABLE, actual_dim)
    write_stats = write_chunks(
        vectors_db_url,
        PGVECTOR_TABLE,
        all_chunks,
        embeddings,
    )
    logger.info(
        "wrote %d rows to %s (%d tokens)",
        write_stats.rows_written,
        write_stats.table,
        write_stats.total_tokens,
    )

    # Stage 7: register source + recipe + physical index in the catalog.
    session_factory = make_session_factory(create_db_engine(db_url))
    with session_factory() as session:
        result = register_document_source(
            session,
            slug=SOURCE_SLUG,
            name=SOURCE_NAME,
            description_short=DESCRIPTION_SHORT,
            description_long=DESCRIPTION_LONG,
            owner_team=SOURCE_OWNER_TEAM,
            owner_contacts=SOURCE_OWNER_CONTACTS,
            recipe_content=_recipe_content(),
            physical_index_location=PGVECTOR_TABLE,
            document_count=len(normalized),
            chunk_count=len(all_chunks),
            sample_prompts=SAMPLE_PROMPTS,
            usage_rules={**USAGE_RULES, "data_freshness": DATA_FRESHNESS},
            triggered_by="script:ingest_tale_of_two_cities",
            family=SourceFamily.DOCUMENT,
        )

    wall_elapsed = time.monotonic() - wall_start

    # Final summary.
    print()
    print("=" * 72)
    print("A Tale of Two Cities ingestion complete")
    print("=" * 72)
    print(f"  HTML file            : {html_path}")
    print(f"  Documents            : {len(normalized)}")
    print(f"  Chunks               : {len(all_chunks)}")
    print(f"  Tokens embedded      : {write_stats.total_tokens}")
    print(f"  Embedding model      : {EMBEDDING_MODEL}")
    print(f"  Embedding dimension  : {actual_dim}")
    print(f"  pgvector table       : {PGVECTOR_TABLE}")
    print()
    print(f"  Source slug          : {result.source_slug}")
    print(f"  Source UUID          : {result.source_id}")
    print(f"  Recipe version       : v{result.recipe_version_number}")
    print(f"  Physical index       : {result.physical_index_id}")
    print()
    print(f"  Total wall time      : {wall_elapsed:.1f}s")
    print()
    print("Next: seed semantic context with")
    print(
        "  python scripts/seed_semantic_context.py --source tale-of-two-cities"
    )
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--html-file",
        type=Path,
        default=DEFAULT_HTML_FILE,
        help=f"Path to the Gutenberg HTML file. Default: {DEFAULT_HTML_FILE}",
    )
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
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    return _run_ingestion(
        html_file=args.html_file,
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
    )


if __name__ == "__main__":
    sys.exit(main())
