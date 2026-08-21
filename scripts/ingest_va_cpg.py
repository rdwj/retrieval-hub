"""Ingest the VA/DoD Clinical Practice Guidelines corpus.

Ingests a pre-extracted corpus of VA/DoD Clinical Practice Guidelines into the
retrieval-hub catalog and a local pgvector physical index. The corpus covers
chronic disease, mental health, pain management, rehabilitation, and women's
health guidelines.

The script expects the corpus to be pre-extracted Markdown files in a sibling
repository (retrieval-hub-data-sources/va-cpg/extracted) organized by clinical
category. Use ``--corpus-dir`` to override that default.

Usage:

    # 1. Start local dependencies (Ansible playbooks)
    ansible-playbook -i deploy/ansible/inventory/local \\
      deploy/ansible/playbooks/local_all_up.yml

    # 2. Apply catalog migrations (one time)
    make migrate

    # 3. Run ingestion
    python scripts/ingest_va_cpg.py

    # 4. Or point at a different corpus directory
    python scripts/ingest_va_cpg.py --corpus-dir /path/to/va-cpg/extracted

The script reports a summary at the end: doc/chunk counts, Source UUID,
pgvector table name, and the exact command to query it next.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import time
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.fetch import FetchError, load_corpus_tree
from retrieval_hub.ingestion.normalize import normalize_document
from retrieval_hub.ingestion.parse import ParsedSection, parse_document
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger("ingest_va_cpg")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
SOURCE_NAME = "VA/DoD Clinical Practice Guidelines"
DESCRIPTION_SHORT = (
    "52 clinical practice guidelines from the VA/DoD covering chronic disease, "
    "mental health, pain management, rehabilitation, and women's health."
)
DESCRIPTION_LONG = (
    "A curated ingestion of the VA/DoD Clinical Practice Guidelines corpus "
    "covering five clinical categories: chronic disease management (diabetes, "
    "hypertension, heart failure, COPD, CKD), mental health (PTSD, depression, "
    "substance use disorders, bipolar disorder, suicide prevention), pain "
    "management (opioid therapy, low back pain, headache), rehabilitation "
    "(TBI, amputation, spinal cord injury), and women's health (pregnancy, "
    "contraception, cervical cancer screening). These evidence-based guidelines "
    "are jointly developed by the Department of Veterans Affairs and the "
    "Department of Defense to standardize clinical decision-making across "
    "military and veteran healthcare settings. The ingestion uses a markdown "
    "passthrough parser, a token-fixed chunker at 512/0 tokens, and "
    "Nomic Embed v1.5 (nomic-ai/nomic-embed-text-v1.5) for embeddings "
    "stored in pgvector. Nomic v1.5 was selected after a systematic "
    "comparison (eval Run 7) showing it outperforms PubMedBERT and "
    "BioLORD-2023 on context precision and answer relevancy."
)
SOURCE_OWNER_TEAM = "ai-americas"
SOURCE_OWNER_CONTACTS = ["ai-americas@example.com"]

PGVECTOR_TABLE = "idx_va_cpg_nomic_v1"
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIMENSION = 768
CHUNK_TOKENS = 512
OVERLAP_TOKENS = 0
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

DEFAULT_DATA_SOURCE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "va-cpg"
)
DEFAULT_CORPUS_DIR = DEFAULT_DATA_SOURCE_DIR / "extracted"
DEFAULT_PDF_URLS = DEFAULT_DATA_SOURCE_DIR / "pdf-urls.json"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
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


def _recipe_content() -> dict:
    """Return the recipe content dict that will be stored on RecipeVersion."""
    return {
        "parser": {"kind": "markdown_passthrough"},
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


def _build_source_url_map(pdf_urls_path: Path) -> dict[str, str]:
    """Build a slug/doc-type -> source URL map from pdf-urls.json.

    Returns a dict like ``{"hypertension/full-guideline": "https://..."}``.
    """
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


_CPG_TITLE_RE = re.compile(r"CLINICAL PRACTICE GUIDELINE(?!S)\b", re.IGNORECASE)


def _normalize_title(title: str, sections: list[ParsedSection]) -> str:
    """Fix doc_title inconsistencies in VA CPG extracted documents."""
    t = html.unescape(title)
    t = t.replace("VA/DOD", "VA/DoD")
    t = t.replace("DIAGNOSI S", "DIAGNOSIS")

    if not _CPG_TITLE_RE.search(t):
        for sec in sections:
            heading = html.unescape(sec.heading)
            heading = heading.replace("VA/DOD", "VA/DoD")
            heading = heading.replace("DIAGNOSI S", "DIAGNOSIS")
            if _CPG_TITLE_RE.search(heading):
                t = heading
                break

    # Two source docs use Title Case while the rest use ALL CAPS.
    if _CPG_TITLE_RE.search(t):
        t = t.upper().replace("VA/DOD", "VA/DoD")

    return t


def _run_ingestion(corpus_dir: Path, db_url: str, vectors_db_url: str) -> int:
    """Execute the full ingestion pipeline end-to-end."""
    wall_start = time.monotonic()

    # Build source URL map so chunks link to the original VA.gov PDFs.
    pdf_urls_path = corpus_dir.parent / "pdf-urls.json"
    url_map = _build_source_url_map(pdf_urls_path)

    # Stage 1: fetch (load from local corpus tree).
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

    # Stages 2 + 3: parse, normalize.
    normalized = []
    for raw in raw_docs:
        parsed = parse_document(raw)
        norm = normalize_document(parsed)
        if norm is None:
            logger.info("skipping empty/short document url=%s", raw.url)
            continue
        norm.title = _normalize_title(norm.title, norm.sections)
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
        batch_size=8,
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
            triggered_by="script:ingest_va_cpg",
            family=SourceFamily.CLINICAL_DOCUMENT,
        )

    wall_elapsed = time.monotonic() - wall_start

    # Final summary.
    print()
    print("=" * 72)
    print("VA CPG ingestion complete")
    print("=" * 72)
    print(f"  Corpus dir           : {corpus_dir}")
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
    print(
        '  python scripts/query_va_cpg_demo.py "what does the VA CPG recommend for PTSD treatment"'
    )
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=DEFAULT_CORPUS_DIR,
        help=(f"Path to the extracted VA CPG corpus directory. Default: {DEFAULT_CORPUS_DIR}"),
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
        corpus_dir=args.corpus_dir,
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
    )


if __name__ == "__main__":
    sys.exit(main())
