"""Ingest the PubMed Hypertension literature collection.

Ingests a curated set of open-access PubMed Central review articles on
hypertension management into the retrieval-hub catalog and a local pgvector
physical index. The collection covers management guidelines, pharmacotherapy,
lifestyle and adherence, and comorbidities.

The script expects BioC JSON article files in a sibling repository
(retrieval-hub-data-sources/pubmed-hypertension) organized by clinical
category. Use ``--data-dir`` to override that default.

Usage:

    # 1. Start local dependencies (Ansible playbooks)
    ansible-playbook -i deploy/ansible/inventory/local \\
      deploy/ansible/playbooks/local_all_up.yml

    # 2. Apply catalog migrations (one time)
    make migrate

    # 3. Run ingestion
    python scripts/ingest_pubmed_hypertension.py

    # 4. Or point at a different data directory
    python scripts/ingest_pubmed_hypertension.py --data-dir /path/to/pubmed-hypertension

The script reports a summary at the end: article/chunk counts, section
distribution, Source UUID, pgvector table name, and the exact command to
query it next.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.bioc_section import chunk_bioc_document
from retrieval_hub.ingestion.chunking.token_fixed import Chunk
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger("ingest_pubmed_hypertension")

SOURCE_SLUG = "pubmed-hypertension"
SOURCE_NAME = "PubMed Hypertension Literature"
DESCRIPTION_SHORT = (
    "10 open-access review articles from PubMed Central on hypertension "
    "management, spanning management guidelines, pharmacotherapy, lifestyle "
    "and adherence, and comorbidities."
)
DESCRIPTION_LONG = (
    "A curated collection of 10 peer-reviewed, open-access review articles "
    "from PubMed Central covering hypertension management. Articles span "
    "four categories: management guidelines (international guideline "
    "comparisons, Saudi Heart Association guidelines, treatment updates), "
    "pharmacotherapy (standardized treatment protocols, GLP-1 therapies for "
    "resistant hypertension), lifestyle and adherence (ISH position paper on "
    "lifestyle management, medication adherence barriers, adherence and "
    "mortality), and comorbidities (hypertension-diabetes connection, "
    "resistant hypertension in kidney disease). Designed to complement the "
    "VA/DoD Clinical Practice Guidelines source for cross-dataset clinical "
    "reasoning. Ingested from structured BioC JSON using a section-aware "
    "chunker that preserves passage boundaries and section type metadata, "
    "with PubMedBERT embeddings."
)
SOURCE_OWNER_TEAM = "ai-americas"
SOURCE_OWNER_CONTACTS = ["ai-americas@example.com"]

PGVECTOR_TABLE = "idx_pubmed_hypertension_v1"
EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"
EMBEDDING_DIMENSION = 768
CHUNK_TOKENS = 256
OVERLAP_TOKENS = 0
DOCUMENT_PREFIX = ""
QUERY_PREFIX = ""

DEFAULT_DATA_SOURCE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "pubmed-hypertension"
)

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)

SAMPLE_PROMPTS: list[tuple[str, str]] = [
    (
        "claude-*",
        (
            "You are a clinical research assistant with access to peer-reviewed "
            "hypertension literature from PubMed Central. When answering questions:\n"
            "1. Retrieve relevant evidence using the retrieve tool.\n"
            "2. Cite the article title, journal, year, and PMC URL for every claim.\n"
            "3. Note the study type (meta-analysis, systematic review, position paper) "
            "and its implications for evidence strength.\n"
            "4. Distinguish between clinical guidelines and research evidence.\n"
            "5. Note the article's Creative Commons license when sharing content."
        ),
    ),
]

USAGE_RULES: dict = {
    "citation": (
        "Always cite the PMC URL (provided in doc_url) along with the article "
        "title, journal name, publication year, and Creative Commons license. "
        "Per-article licenses vary: CC BY, CC BY-NC, CC BY-NC-SA, CC BY-NC-ND."
    ),
    "scope_disclaimer": (
        "These are peer-reviewed journal articles representing published research "
        "evidence. They are not clinical practice guidelines and do not represent "
        "institutional treatment recommendations. Research findings should be "
        "contextualized within the study's scope and limitations."
    ),
    "handling": (
        "Content is research evidence to inform clinical decision-making, not "
        "direct patient care guidance. When presenting findings, note the study "
        "design, sample size, and confidence intervals where available."
    ),
    "custom_rules": [
        "When citing meta-analyses, include the number of studies and total participants.",
        "Distinguish between findings from randomized controlled trials and observational studies.",
        "When multiple articles address the same topic, synthesize across sources rather than citing only one.",
    ],
}

DATA_FRESHNESS: dict = {
    "source_name": "PubMed Central Open Access",
    "source_url": "https://pmc.ncbi.nlm.nih.gov/",
    "last_refreshed": "2026-08-20",
    "refresh_cadence": "on_demand",
    "staleness_note": (
        "Articles are from 2023-2025 peer-reviewed literature. New articles "
        "may be added to this collection periodically. Check PMC for the most "
        "current versions of individual articles."
    ),
}


def _recipe_content() -> dict:
    """Return the recipe content dict that will be stored on RecipeVersion."""
    return {
        "parser": {"kind": "bioc_json"},
        "chunker": {
            "kind": "bioc_section",
            "chunk_size_tokens": CHUNK_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
            "encoding": "cl100k_base",
            "respect_section_boundaries": True,
            "skip_sections": ["AUTH_CONT", "SUPPL", "REF", "COMP_INT"],
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


def _run_ingestion(data_dir: Path, db_url: str, vectors_db_url: str) -> int:
    """Execute the full ingestion pipeline end-to-end."""
    wall_start = time.monotonic()

    # Stage 1: fetch (load manifest and BioC JSON files).
    manifest_path = data_dir / "articles.json"
    if not manifest_path.exists():
        logger.error("manifest not found at %s; aborting", manifest_path)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    articles = manifest.get("articles", [])
    logger.info("loaded manifest with %d articles from %s", len(articles), manifest_path)

    if not articles:
        logger.error("no articles in manifest; aborting")
        return 1

    # Stages 2 + 3: skipped (BioC JSON is already structured).

    # Stage 4: chunk.
    all_chunks: list[Chunk] = []
    section_counter: Counter[str] = Counter()
    articles_processed = 0

    for article in articles:
        slug = article["slug"]
        category = article["category"]
        bioc_path = data_dir / "sources" / category / slug / "article.json"

        if not bioc_path.exists():
            logger.warning("BioC JSON not found for %s at %s; skipping", slug, bioc_path)
            continue

        bioc_data = json.loads(bioc_path.read_text(encoding="utf-8"))

        chunks = chunk_bioc_document(
            bioc_data,
            doc_url=article["pmc_url"],
            doc_title=article["title"],
            chunk_tokens=CHUNK_TOKENS,
            overlap_tokens=OVERLAP_TOKENS,
        )

        for chunk in chunks:
            section_type = chunk.doc_section or "unknown"
            section_counter[section_type] += 1

        all_chunks.extend(chunks)
        articles_processed += 1
        logger.info(
            "chunked article %s [%s]: %d chunks",
            slug,
            article["title"][:60],
            len(chunks),
        )

    logger.info(
        "produced %d chunks from %d articles",
        len(all_chunks),
        articles_processed,
    )

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
            document_count=articles_processed,
            chunk_count=len(all_chunks),
            sample_prompts=SAMPLE_PROMPTS,
            usage_rules={**USAGE_RULES, "data_freshness": DATA_FRESHNESS},
            triggered_by="script:ingest_pubmed_hypertension",
            family=SourceFamily.CLINICAL_DOCUMENT,
        )

    wall_elapsed = time.monotonic() - wall_start

    # Final summary.
    print()
    print("=" * 72)
    print("PubMed Hypertension ingestion complete")
    print("=" * 72)
    print(f"  Data dir             : {data_dir}")
    print(f"  Articles             : {articles_processed}")
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
    print("  Section distribution:")
    for section_type, count in section_counter.most_common():
        print(f"    {section_type:20s} : {count}")
    print()
    print(f"  Total wall time      : {wall_elapsed:.1f}s")
    print()
    print("Next: query the source with")
    print(
        '  python scripts/query_pubmed_demo.py "what does the literature say about '
        'medication adherence in hypertension"'
    )
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_SOURCE_DIR,
        help=(f"Path to the pubmed-hypertension data directory. Default: {DEFAULT_DATA_SOURCE_DIR}"),
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=(f"SQLAlchemy URL for the catalog database. Default: {DEFAULT_DB_URL}"),
    )
    parser.add_argument(
        "--vectors-db-url",
        default=DEFAULT_VECTORS_DB_URL,
        help=(f"SQLAlchemy URL for the vectors database. Default: {DEFAULT_VECTORS_DB_URL}"),
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
        data_dir=args.data_dir,
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
    )


if __name__ == "__main__":
    sys.exit(main())
