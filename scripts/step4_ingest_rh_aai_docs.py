"""Hand-run ingestion script for step 4.

Ingests a small Red Hat AI / OpenShift AI documentation corpus into the
retrieval-hub catalog and a local pgvector physical index. Demonstrates the
full seven-stage pipeline from docs/ingestion.md running end-to-end against
real-ish content for the first time.

This is NOT a production ingestion runner. It is a one-shot hand-run script
that proves the data model, the adapter dispatch, and the retrieval path all
work together. Production ingestion runners come in a later step.

Usage:

    # 1. Start local dependencies (Ansible playbooks)
    ansible-playbook -i deploy/ansible/inventory/local \\
      deploy/ansible/playbooks/local_all_up.yml

    # 2. Apply catalog migrations (one time)
    make migrate

    # 3. Run ingestion (default: use the fallback corpus)
    python scripts/step4_ingest_rh_aai_docs.py

    # 4. Or try the real corpus first with fallback on failure
    python scripts/step4_ingest_rh_aai_docs.py --try-network

The script reports a summary at the end: doc/chunk counts, Source UUID,
pgvector table name, and the exact command to query it next.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.fetch import (
    FetchedDocument,
    FetchError,
    fetch_html_url,
    load_fallback_corpus,
)
from retrieval_hub.ingestion.normalize import normalize_document
from retrieval_hub.ingestion.parse import parse_document
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks

logger = logging.getLogger("step4_ingest")


PRIMARY_CORPUS_URL = (
    "https://docs.redhat.com/en/documentation/"
    "red_hat_openshift_ai_self-managed/3.0/html-single/"
    "working_with_llama_stack/index"
)

FALLBACK_CORPUS_DIR = Path(__file__).parent / "step4_fallback_corpus"

# The Source metadata that will land in the catalog.
SOURCE_SLUG = "rh-aai-llamastack-guide"
SOURCE_NAME = "Red Hat OpenShift AI 3 — Working with Llama Stack"
SOURCE_DESCRIPTION_SHORT = (
    "Red Hat OpenShift AI 3 documentation set covering Llama Stack, vLLM "
    "model serving, MCP servers, Ragas evaluation, and RHEL AI / InstructLab."
)
SOURCE_DESCRIPTION_LONG = (
    "A curated ingestion of the Red Hat OpenShift AI 3 documentation set "
    "focused on the AI application layer: Llama Stack, OAuth authentication, "
    "RAG evaluation with Ragas, vLLM model serving, MCP server development, "
    "OpenShift Pipelines for AI workflows, and the RHEL AI / InstructLab "
    "toolchain. The ingestion uses Docling (with a BS4 fallback) for parsing, "
    "a token-fixed chunker at 512/64 tokens for splitting, and "
    "sentence-transformers with nomic-embed-text-v1.5 for embeddings stored "
    "in pgvector."
)
SOURCE_OWNER_TEAM = "ai-americas"
SOURCE_OWNER_CONTACTS = ["ai-americas@example.com"]

PGVECTOR_TABLE = "idx_rh_aai_llamastack_v1"
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIMENSION = 768
CHUNK_TOKENS = 512
OVERLAP_TOKENS = 64

SAMPLE_PROMPTS: list[tuple[str, str]] = [
    (
        "granite-3.3-*",
        (
            "You are answering questions about Red Hat OpenShift AI 3 using "
            "retrieved documentation chunks. Always cite the document title "
            "and section you pulled each fact from. If the retrieved context "
            "does not contain the answer, say so explicitly rather than "
            "guessing."
        ),
    ),
    (
        "llama-3.3-*",
        (
            "Use the retrieved Red Hat OpenShift AI 3 documentation to answer "
            "the user's question. Cite sources by document title and section. "
            "If the retrieved context does not contain enough information to "
            "answer, say so and suggest what the user should look up next."
        ),
    ),
    (
        "gpt-4o",
        (
            "Answer questions about Red Hat OpenShift AI 3 using only the "
            "retrieved context. Cite document titles and sections. When the "
            "context is insufficient, say so plainly."
        ),
    ),
]


def _recipe_content() -> dict:
    """Return the recipe content dict that will be stored on RecipeVersion."""
    return {
        "parser": {"kind": "docling", "fallback": "bs4"},
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


def _fetch_corpus(try_network: bool) -> tuple[list[FetchedDocument], str]:
    """Return the corpus and a label describing which source it came from."""
    if try_network:
        try:
            logger.info("fetching primary corpus from %s", PRIMARY_CORPUS_URL)
            doc = fetch_html_url(PRIMARY_CORPUS_URL)
            return [doc], "network"
        except FetchError as exc:
            logger.warning("primary corpus fetch failed: %s — using fallback", exc)
    logger.info("loading fallback corpus from %s", FALLBACK_CORPUS_DIR)
    docs = load_fallback_corpus(FALLBACK_CORPUS_DIR)
    return docs, "fallback"


def _run_ingestion(try_network: bool) -> int:
    """Execute the full ingestion pipeline end-to-end."""
    wall_start = time.monotonic()

    # Stages 1 + 2 + 3: fetch, parse, normalize.
    raw_docs, corpus_label = _fetch_corpus(try_network)
    logger.info("fetched %d documents from corpus=%s", len(raw_docs), corpus_label)

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

    # Stage 5: embed. Lazy import so unit tests that mock this module don't
    # pay the sentence-transformers import cost.
    from retrieval_hub.ingestion.embed import ChunkEmbedder

    embed_start = time.monotonic()
    embedder = ChunkEmbedder(model_name=EMBEDDING_MODEL)
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
    from retrieval_hub.adapters.document import get_default_vectors_db_url

    vectors_db_url = get_default_vectors_db_url()
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
    session_factory = make_session_factory(create_db_engine())
    with session_factory() as session:
        result = register_document_source(
            session,
            slug=SOURCE_SLUG,
            name=SOURCE_NAME,
            description_short=SOURCE_DESCRIPTION_SHORT,
            description_long=SOURCE_DESCRIPTION_LONG,
            owner_team=SOURCE_OWNER_TEAM,
            owner_contacts=SOURCE_OWNER_CONTACTS,
            recipe_content=_recipe_content(),
            physical_index_location=PGVECTOR_TABLE,
            document_count=len(normalized),
            chunk_count=len(all_chunks),
            sample_prompts=SAMPLE_PROMPTS,
        )

    wall_elapsed = time.monotonic() - wall_start

    # Final summary.
    print()
    print("=" * 72)
    print("Step 4 ingestion complete")
    print("=" * 72)
    print(f"  Corpus               : {corpus_label}")
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
    print("Next: query the source with")
    print('  python scripts/step4_query_demo.py "how do I enable OAuth on Llama Stack"')
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--try-network",
        action="store_true",
        help=(
            "Try the real docs.redhat.com URL first. If it fails, falls back "
            "to the hand-written corpus in scripts/step4_fallback_corpus/."
        ),
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

    return _run_ingestion(try_network=args.try_network)


if __name__ == "__main__":
    sys.exit(main())
