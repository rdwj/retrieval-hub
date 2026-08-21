"""Ingest the Piper Aircraft Service Bulletins collection.

Ingests Docling-extracted service bulletins for Piper Cherokee (PA-28) and
Saratoga (PA-32) aircraft families into the retrieval-hub catalog and a local
pgvector physical index.  The collection includes Service Bulletins (SB),
Service Letters (SL), Supplemental Service Letters (SSL), Vendor Service
Publications (VSP), and Customer Information Letters (CIL).

The script expects pre-extracted markdown files in a sibling repository
(retrieval-hub-data-sources/aircraft-maintenance) organized by aircraft
family.  Use ``--data-dir`` to override that default.

Usage:

    # 1. Start local dependencies (Ansible playbooks)
    ansible-playbook -i deploy/ansible/inventory/local \\
      deploy/ansible/playbooks/local_all_up.yml

    # 2. Apply catalog migrations (one time)
    make migrate

    # 3. Run ingestion (requires a remote embedding endpoint)
    python scripts/ingest_aircraft_maintenance.py \\
      --embedding-endpoint http://vllm-host:8000

The script reports a summary at the end: document/chunk counts, family and
doc-type distribution, Source UUID, pgvector table name, and wall time.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.normalize import NormalizedDocument, normalize_document
from retrieval_hub.ingestion.parse import ParsedDocument, ParsedSection
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger("ingest_aircraft_maintenance")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_SLUG = "aircraft-maintenance"
SOURCE_NAME = "Piper Aircraft Service Bulletins"
DESCRIPTION_SHORT = (
    "269 service bulletins, service letters, and vendor service publications "
    "for Piper Cherokee (PA-28) and Saratoga (PA-32) aircraft families."
)
DESCRIPTION_LONG = (
    "A collection of Piper Aircraft service documents spanning Cherokee "
    "(PA-28) and Saratoga (PA-32) families.  Includes Service Bulletins "
    "(SB), Service Letters (SL), Supplemental Service Letters (SSL), "
    "Vendor Service Publications (VSP), and Customer Information Letters "
    "(CIL).  Documents cover airworthiness directives, mandatory and "
    "recommended maintenance actions, component inspection intervals, and "
    "superseding bulletin chains.  Extracted from original PDF publications "
    "via Docling and chunked with a 512-token fixed-window chunker using "
    "Snowflake Arctic Embed M v1.5 embeddings."
)
SOURCE_OWNER_TEAM = "ai-americas"
SOURCE_OWNER_CONTACTS = ["ai-americas@example.com"]

PGVECTOR_TABLE = "idx_aircraft_maintenance_v1"
EMBEDDING_MODEL = "Snowflake/snowflake-arctic-embed-m-v1.5"
EMBEDDING_DIMENSION = 768
CHUNK_TOKENS = 512
OVERLAP_TOKENS = 64
DOCUMENT_PREFIX = ""  # snowflake-arctic-embed uses no document prefix
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

DEFAULT_DATA_SOURCE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "aircraft-maintenance"
)

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
)

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

# Regex to extract the document type prefix (SB, SL, SSL, VSP, CIL).
_DOC_TYPE_RE = re.compile(r"^(SB|SL|SSL|VSP|CIL)[_ ]", re.IGNORECASE)

SAMPLE_PROMPTS: list[tuple[str, str]] = [
    (
        "claude-*",
        (
            "You are an aircraft maintenance technical assistant with access to "
            "Piper Aircraft service bulletins for Cherokee (PA-28) and Saratoga "
            "(PA-32) families. When answering questions:\n"
            "1. Retrieve relevant service bulletins using the retrieve tool.\n"
            "2. Cite the specific bulletin number (e.g., SB 1197E) and aircraft "
            "family for every claim.\n"
            "3. Note compliance times and affected serial numbers when relevant.\n"
            "4. Distinguish between mandatory service bulletins (SB), advisory "
            "service letters (SL), and vendor service publications (VSP).\n"
            "5. When a bulletin supersedes a previous one, note both."
        ),
    ),
]

USAGE_RULES: dict = {
    "citation": (
        "Always cite the document type and number (e.g., SB 1197E, SL 1072) "
        "along with the aircraft family (Cherokee or Saratoga).  These are "
        "manufacturer service documents, not regulatory airworthiness directives; "
        "note which bulletins reference or comply with FAA ADs."
    ),
    "scope_disclaimer": (
        "This collection covers Piper Cherokee (PA-28) and Saratoga (PA-32) "
        "families only.  Bulletins may reference other Piper models in their "
        "applicability lists, but the collection does not guarantee coverage "
        "of all bulletins for those other models."
    ),
    "handling": (
        "Service bulletin content is for informational and maintenance planning "
        "purposes.  Actual maintenance actions must be performed by or under "
        "the supervision of an appropriately certificated mechanic in accordance "
        "with the original manufacturer publications and applicable FAA regulations."
    ),
    "custom_rules": [
        "When a bulletin lists affected serial numbers, include the serial number "
        "range in the response.",
        "Distinguish between mandatory compliance (SB) and advisory recommendations (SL).",
        "Note when a bulletin has been superseded by a later revision.",
        "If a bulletin references an FAA Airworthiness Directive, include the AD number.",
    ],
}

DATA_FRESHNESS: dict = {
    "source_name": "Piper Aircraft Customer Service Publications",
    "source_url": "https://www.piper.com/service-support/",
    "last_refreshed": "2025-01-01",
    "refresh_cadence": "on_demand",
    "staleness_note": (
        "Documents were downloaded from Piper Aircraft's S3-hosted publication "
        "archive.  New bulletins are issued periodically by Piper Aircraft; this "
        "collection may not include the most recent publications.  Always verify "
        "against the manufacturer's current service bulletin index."
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc_url(family_key: str, stem: str) -> str:
    """Build a synthetic URL for a document without a stable public URL."""
    # family_key is e.g. "piper-cherokee"; extract the aircraft name
    aircraft = family_key.split("-", 1)[1] if "-" in family_key else family_key
    return f"piper://{aircraft}/{stem}"


def _classify_doc_type(stem: str) -> str:
    """Extract the document type prefix from a filename stem."""
    m = _DOC_TYPE_RE.match(stem)
    return m.group(1).upper() if m else "OTHER"


def _make_doc_title(stem: str, family_label: str) -> str:
    """Build a human-readable document title from filename stem + family.

    The Docling-extracted titles in manifest.json are unreliable (many are
    just "SERVICE No. BULLETIN" without the number), so we use the filename
    stem as the primary identifier.
    """
    return f"{stem} ({family_label})"


def _extract_sections_from_markdown(text: str) -> list[ParsedSection]:
    """Extract markdown heading positions for section attribution."""
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
    sections: list[ParsedSection] = []
    for match in heading_re.finditer(text):
        sections.append(
            ParsedSection(
                heading=match.group(2).strip(),
                level=len(match.group(1)),
                char_offset=match.start(),
            )
        )
    return sections


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------


def _recipe_content(embedding_endpoint: str) -> dict:
    """Return the recipe content dict stored on RecipeVersion."""
    return {
        "parser": {"kind": "docling_extracted_markdown"},
        "chunker": {
            "kind": "token_fixed",
            "chunk_size_tokens": CHUNK_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
            "note": "cl100k_base chunking; BERT truncation at 512 handled server-side via truncate_prompt_tokens",
            "encoding": "cl100k_base",
        },
        "embedding": {
            "model": EMBEDDING_MODEL,
            "dimension": EMBEDDING_DIMENSION,
            "normalize": True,
            "document_prefix": DOCUMENT_PREFIX,
            "query_prefix": QUERY_PREFIX,
            "endpoint": embedding_endpoint,
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


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _run_ingestion(
    data_dir: Path,
    embedding_endpoint: str,
    db_url: str,
    vectors_db_url: str,
) -> int:
    """Execute the full ingestion pipeline end-to-end."""
    wall_start = time.monotonic()

    # ------------------------------------------------------------------
    # Stage 1: fetch -- read manifests, build document list
    # ------------------------------------------------------------------
    documents: list[tuple[str, str, str, Path]] = []
    # Each tuple: (family_key, family_label, doc_title, md_path)

    for family_key, family_label in AIRCRAFT_FAMILIES.items():
        extracted_dir = data_dir / family_key / "extracted"
        manifest_path = extracted_dir / "manifest.json"

        if not manifest_path.exists():
            logger.error("manifest not found at %s; aborting", manifest_path)
            return 1

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        logger.info(
            "loaded manifest for %s with %d entries from %s",
            family_label,
            len(manifest),
            manifest_path,
        )

        for entry in manifest:
            stem = Path(entry["source_path"]).stem

            if stem in SKIP_STEMS:
                logger.debug("skipping non-bulletin file: %s", stem)
                continue

            md_path = extracted_dir / f"{stem}.md"
            if not md_path.exists():
                logger.warning(
                    "markdown file not found for %s at %s; skipping",
                    stem,
                    md_path,
                )
                continue

            doc_title = _make_doc_title(stem, family_label)
            documents.append((family_key, family_label, doc_title, md_path))

    logger.info("found %d documents to ingest across all families", len(documents))

    if not documents:
        logger.error("no documents found; aborting")
        return 1

    # ------------------------------------------------------------------
    # Stages 2 + 3: parse + normalize
    # ------------------------------------------------------------------
    normalized_docs: list[tuple[str, str, str, NormalizedDocument]] = []
    # Each tuple: (family_key, family_label, doc_title, normalized_doc)
    skipped_short = 0

    for family_key, family_label, doc_title, md_path in documents:
        raw_text = md_path.read_text(encoding="utf-8")
        stem = md_path.stem
        doc_url = _make_doc_url(family_key, stem)

        # Build a ParsedDocument so we can reuse normalize_document().
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
            logger.info("skipping short document: %s (%d chars)", doc_title, len(raw_text))
            skipped_short += 1
            continue

        normalized_docs.append((family_key, family_label, doc_title, normalized))

    logger.info(
        "normalized %d documents (%d skipped as too short)",
        len(normalized_docs),
        skipped_short,
    )

    # ------------------------------------------------------------------
    # Stage 4: chunk
    # ------------------------------------------------------------------
    all_chunks: list[Chunk] = []
    family_counter: Counter[str] = Counter()
    doc_type_counter: Counter[str] = Counter()
    docs_processed = 0

    for _family_key, family_label, doc_title, normalized in normalized_docs:
        chunks = chunk_document(
            normalized,
            chunk_tokens=CHUNK_TOKENS,
            overlap_tokens=OVERLAP_TOKENS,
        )

        all_chunks.extend(chunks)
        family_counter[family_label] += 1
        doc_type_counter[_classify_doc_type(doc_title)] += 1
        docs_processed += 1

        logger.info(
            "chunked %s: %d chunks",
            doc_title,
            len(chunks),
        )

    logger.info(
        "produced %d chunks from %d documents",
        len(all_chunks),
        docs_processed,
    )

    if not all_chunks:
        logger.error("no chunks produced; aborting")
        return 1

    # ------------------------------------------------------------------
    # Stage 5: embed
    # ------------------------------------------------------------------
    from retrieval_hub.ingestion.embed import ChunkEmbedder

    embed_start = time.monotonic()
    embedder = ChunkEmbedder(
        model_name=EMBEDDING_MODEL,
        endpoint=embedding_endpoint,
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

    # ------------------------------------------------------------------
    # Stage 6: write to pgvector
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Stage 7: register source + recipe + physical index in the catalog
    # ------------------------------------------------------------------
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
            recipe_content=_recipe_content(embedding_endpoint),
            physical_index_location=PGVECTOR_TABLE,
            document_count=docs_processed,
            chunk_count=len(all_chunks),
            sample_prompts=SAMPLE_PROMPTS,
            usage_rules={**USAGE_RULES, "data_freshness": DATA_FRESHNESS},
            triggered_by="script:ingest_aircraft_maintenance",
            family=SourceFamily.TECHNICAL_DOCUMENT,
        )

    wall_elapsed = time.monotonic() - wall_start

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    print()
    print("=" * 72)
    print("Aircraft maintenance ingestion complete")
    print("=" * 72)
    print(f"  Data dir             : {data_dir}")
    print(f"  Documents            : {docs_processed}")
    print(f"  Chunks               : {len(all_chunks)}")
    print(f"  Tokens embedded      : {write_stats.total_tokens}")
    print(f"  Embedding model      : {EMBEDDING_MODEL}")
    print(f"  Embedding dimension  : {actual_dim}")
    print(f"  Embedding endpoint   : {embedding_endpoint}")
    print(f"  pgvector table       : {PGVECTOR_TABLE}")
    print()
    print(f"  Source slug          : {result.source_slug}")
    print(f"  Source UUID          : {result.source_id}")
    print(f"  Recipe version       : v{result.recipe_version_number}")
    print(f"  Physical index       : {result.physical_index_id}")
    print()
    print("  Family distribution:")
    for family, count in family_counter.most_common():
        print(f"    {family:20s} : {count}")
    print()
    print("  Document type distribution:")
    for doc_type, count in doc_type_counter.most_common():
        print(f"    {doc_type:20s} : {count}")
    print()
    print(f"  Total wall time      : {wall_elapsed:.1f}s")
    print()
    print("Next: query the source with")
    print(
        '  python scripts/query_demo.py --source aircraft-maintenance '
        '"what service bulletins affect the Cherokee fuel system"'
    )
    print("=" * 72)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_SOURCE_DIR,
        help=f"Path to the aircraft-maintenance data directory. Default: {DEFAULT_DATA_SOURCE_DIR}",
    )
    parser.add_argument(
        "--embedding-endpoint",
        required=True,
        help=(
            "Base URL of an OpenAI-compatible embedding endpoint "
            "(e.g. http://vllm-host:8000). Required."
        ),
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
        data_dir=args.data_dir,
        embedding_endpoint=args.embedding_endpoint,
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
    )


if __name__ == "__main__":
    sys.exit(main())
