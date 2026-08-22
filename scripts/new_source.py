"""Scaffold a new RetrievalHub ingestion script.

Generates a complete, runnable ingestion script for a new data source.
The generated script mirrors the structure of the existing ingestion
scripts (e.g. ingest_va_cpg.py) and is ready to customize with your
source-specific details.

Usage:

    # Basic usage -- generates scripts/ingest_my_data_source.py
    python scripts/new_source.py --slug my-data-source

    # With a human-readable name and source family
    python scripts/new_source.py --slug my-data-source \\
        --name "My Data Source" --family clinical_document

    # Overwrite an existing file
    python scripts/new_source.py --slug my-data-source --force
"""

from __future__ import annotations

import argparse
import py_compile
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_CONSECUTIVE_HYPHENS_RE = re.compile(r"--")


def validate_slug(slug: str) -> tuple[bool, str]:
    """Validate a source slug.

    Returns (True, "") on success, or (False, error_message) on failure.
    """
    if not slug:
        return False, "slug must not be empty"
    if not _SLUG_RE.match(slug):
        return False, (
            f"invalid slug {slug!r}: must contain only lowercase letters, "
            "digits, and hyphens; must not start or end with a hyphen"
        )
    if _CONSECUTIVE_HYPHENS_RE.search(slug):
        return False, (
            f"invalid slug {slug!r}: must not contain consecutive hyphens"
        )
    return True, ""


# ---------------------------------------------------------------------------
# Family mapping
# ---------------------------------------------------------------------------

VALID_FAMILIES: dict[str, str] = {
    "document": "SourceFamily.DOCUMENT",
    "clinical_document": "SourceFamily.CLINICAL_DOCUMENT",
    "technical_document": "SourceFamily.TECHNICAL_DOCUMENT",
}

# Families that exist but need a different script structure.
EXISTING_FAMILY_SCRIPTS: dict[str, str] = {
    "code": "scripts/ingest_code_repo.py",
    "tabular": "(no template yet)",
    "graph": "(no template yet)",
    "process": "(no template yet)",
    "external": "(no template yet)",
}


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

TEMPLATE = '''\
"""Ingest the {name} corpus.

Ingests a pre-extracted corpus into the retrieval-hub catalog and a local
pgvector physical index.

The script expects the corpus to be pre-extracted Markdown files in a sibling
repository (retrieval-hub-data-sources/{slug}/extracted).  Use ``--corpus-dir``
to override that default.

Usage:

    # 1. Start local dependencies (Ansible playbooks)
    ansible-playbook -i deploy/ansible/inventory/local \\\\
      deploy/ansible/playbooks/local_all_up.yml

    # 2. Apply catalog migrations (one time)
    make migrate

    # 3. Run ingestion
    python scripts/ingest_{slug_underscored}.py

    # 4. Or point at a different corpus directory
    python scripts/ingest_{slug_underscored}.py --corpus-dir /path/to/data
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.embed import ChunkEmbedder
from retrieval_hub.ingestion.fetch import FetchError, load_corpus_tree
from retrieval_hub.ingestion.normalize import normalize_document
from retrieval_hub.ingestion.parse import parse_document
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger("ingest_{slug_underscored}")

# ---------------------------------------------------------------------------
# Source identity
# ---------------------------------------------------------------------------

SOURCE_SLUG = "{slug}"
SOURCE_NAME = "{name}"

# ---------------------------------------------------------------------------
# Descriptions
#
# Good descriptions are critical. They are the primary signal agents use
# when deciding which source to query (Phase 4 finding). A vague or generic
# description means agents will skip your source even when it has the best
# answer.
#
# DESCRIPTION_SHORT: One sentence. Start with a count and document type,
# then list 2-3 concrete topic areas. Agents see this in list_sources
# results and use it for fast relevance filtering.
#   Good:  "52 clinical practice guidelines covering chronic disease,
#           mental health, and pain management."
#   Bad:   "A collection of documents."
#
# DESCRIPTION_LONG: 3-5 sentences. Include: what the documents are, who
# produced them, what categories they cover, and the ingestion details
# (parser, chunker config, embedding model). This appears in
# describe_source results and helps agents decide confidence levels.
# ---------------------------------------------------------------------------

DESCRIPTION_SHORT = (
    "TODO: [count] [document type] from [organization] covering "
    "[topic 1], [topic 2], and [topic 3]."
)
DESCRIPTION_LONG = (
    "TODO: A curated collection of [describe corpus]. "
    "Documents cover [list categories]. "
    "Extracted via [method] and chunked with a "
    "512-token fixed-window chunker using "
    "Nomic Embed v1.5 (nomic-ai/nomic-embed-text-v1.5) embeddings."
)

SOURCE_OWNER_TEAM = "TODO: your-team-name"
SOURCE_OWNER_CONTACTS = ["TODO: team-email@example.com"]

# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------

PGVECTOR_TABLE = "idx_{slug_underscored}_v1"
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIMENSION = 768
CHUNK_TOKENS = 512
OVERLAP_TOKENS = 0
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

# ---------------------------------------------------------------------------
# Data directory and DB defaults
# ---------------------------------------------------------------------------

DEFAULT_DATA_SOURCE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "{slug}"
)
DEFAULT_CORPUS_DIR = DEFAULT_DATA_SOURCE_DIR / "extracted"

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)

# ---------------------------------------------------------------------------
# Governance: sample prompts, usage rules, data freshness
#
# These travel with every retrieval response. Any agent querying your source
# sees them and is expected to follow them. See docs/guide-data-owner.md for
# the full governance template and guidance.
# ---------------------------------------------------------------------------

SAMPLE_PROMPTS: list[tuple[str, str]] = [
    (
        "claude-*",
        (
            "TODO: You are a [domain] assistant with access to [source name]. "
            "When answering questions:\\n"
            "1. Retrieve relevant content using the retrieve tool.\\n"
            "2. Cite the specific [document identifier] for every claim.\\n"
            "3. If the retrieved content does not address the question, say so."
        ),
    ),
]

USAGE_RULES: dict = {{
    "citation": (
        "TODO: Always cite [expected format: source URL, document title, "
        "section, etc.] when referencing content from this source."
    ),
    "scope_disclaimer": (
        "TODO: [What agents should say about the limits and provenance of "
        "this data. Note any organizations, jurisdictions, or domains "
        "where other sources might differ.]"
    ),
    "handling": (
        "TODO: [Constraints on how agents should present this content. "
        "e.g., 'Content is for reference only and does not replace "
        "professional judgment.']"
    ),
    "custom_rules": [
        "TODO: [Source-specific rule 1]",
        "TODO: [Source-specific rule 2]",
    ],
}}

DATA_FRESHNESS: dict = {{
    "source_name": "{name}",
    "source_url": "TODO: https://example.com",
    "last_refreshed": "TODO: YYYY-MM-DD",
    "refresh_cadence": "on_demand",
    "staleness_note": (
        "TODO: [When this data might become outdated and where to find "
        "the most current version.]"
    ),
}}


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------


def _recipe_content() -> dict:
    """Return the recipe content dict that will be stored on RecipeVersion."""
    return {{
        "parser": {{"kind": "markdown_passthrough"}},
        "chunker": {{
            "kind": "token_fixed",
            "chunk_size_tokens": CHUNK_TOKENS,
            "overlap_tokens": OVERLAP_TOKENS,
            "encoding": "cl100k_base",
        }},
        "embedding": {{
            "model": EMBEDDING_MODEL,
            "dimension": EMBEDDING_DIMENSION,
            "normalize": True,
            "document_prefix": DOCUMENT_PREFIX,
            "query_prefix": QUERY_PREFIX,
        }},
        "backend": {{
            "kind": "pgvector",
            "table": PGVECTOR_TABLE,
        }},
        "retrieval": {{
            "default_pattern": "vector_ann",
            "supported_patterns": ["vector_ann"],
            "parameters": {{
                "vector_ann": {{"top_k_default": 10, "top_k_max": 50}},
            }},
        }},
    }}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _run_ingestion(
    corpus_dir: Path,
    db_url: str,
    vectors_db_url: str,
    embedding_endpoint: str | None = None,
    replace: bool = True,
) -> int:
    """Execute the full ingestion pipeline end-to-end."""
    wall_start = time.monotonic()

    # ------------------------------------------------------------------
    # Stage 1: fetch (load from local corpus tree)
    # ------------------------------------------------------------------
    logger.info("loading corpus tree from %s", corpus_dir)
    try:
        raw_docs = load_corpus_tree(corpus_dir)
    except FetchError as exc:
        logger.error("corpus load failed: %s", exc)
        return 1
    logger.info("fetched %d documents from corpus_tree", len(raw_docs))

    if not raw_docs:
        logger.error("no documents found in %s; aborting", corpus_dir)
        return 1

    # ------------------------------------------------------------------
    # Stages 2 + 3: parse + normalize
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Stage 4: chunk
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Stage 5: embed
    # ------------------------------------------------------------------
    embed_start = time.monotonic()
    embedder_kwargs: dict = dict(
        model_name=EMBEDDING_MODEL,
        document_prefix=DOCUMENT_PREFIX,
        batch_size=8,
    )
    if embedding_endpoint:
        embedder_kwargs["endpoint"] = embedding_endpoint
    embedder = ChunkEmbedder(**embedder_kwargs)

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
            recipe_content=_recipe_content(),
            physical_index_location=PGVECTOR_TABLE,
            document_count=len(normalized),
            chunk_count=len(all_chunks),
            sample_prompts=SAMPLE_PROMPTS,
            usage_rules={{**USAGE_RULES, "data_freshness": DATA_FRESHNESS}},
            triggered_by="script:ingest_{slug_underscored}",
            family={family_enum},
        )

    wall_elapsed = time.monotonic() - wall_start

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    print()
    print("=" * 72)
    print("{name} ingestion complete")
    print("=" * 72)
    print(f"  Corpus dir           : {{corpus_dir}}")
    print(f"  Documents            : {{len(normalized)}}")
    print(f"  Chunks               : {{len(all_chunks)}}")
    print(f"  Tokens embedded      : {{write_stats.total_tokens}}")
    print(f"  Embedding model      : {{EMBEDDING_MODEL}}")
    print(f"  Embedding dimension  : {{actual_dim}}")
    print(f"  pgvector table       : {{PGVECTOR_TABLE}}")
    print()
    print(f"  Source slug          : {{result.source_slug}}")
    print(f"  Source UUID          : {{result.source_id}}")
    print(f"  Recipe version       : v{{result.recipe_version_number}}")
    print(f"  Physical index       : {{result.physical_index_id}}")
    print()
    print(f"  Total wall time      : {{wall_elapsed:.1f}}s")
    print()
    print("Next steps:")
    print("  1. Verify: python -m retrieval_hub_mcp  # then call list_sources")
    print("  2. Evaluate: write 30-50 QA questions and run a chunking sweep")
    print("     See scripts/sweep_va_cpg_chunking.py as a template")
    print("=" * 72)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=DEFAULT_CORPUS_DIR,
        help=f"Path to the extracted corpus directory. Default: {{DEFAULT_CORPUS_DIR}}",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy URL for the catalog database. Default: {{DEFAULT_DB_URL}}",
    )
    parser.add_argument(
        "--vectors-db-url",
        default=DEFAULT_VECTORS_DB_URL,
        help=f"SQLAlchemy URL for the vectors database. Default: {{DEFAULT_VECTORS_DB_URL}}",
    )
    parser.add_argument(
        "--embedding-endpoint",
        default=None,
        help="Base URL of an OpenAI-compatible embedding endpoint (e.g. http://vllm-host:8000). Optional; omit for local embedding.",
    )
    parser.add_argument(
        "--replace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Replace existing data (default: --replace).",
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
        embedding_endpoint=args.embedding_endpoint,
        replace=args.replace,
    )


if __name__ == "__main__":
    sys.exit(main())
'''


# ---------------------------------------------------------------------------
# Main scaffolding logic
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scaffold a new RetrievalHub ingestion script. "
            "Generates a complete, runnable ingestion script template."
        ),
    )
    parser.add_argument(
        "--slug",
        required=True,
        help=(
            "URL-safe source identifier. Lowercase letters, digits, and "
            "hyphens only. No leading/trailing or consecutive hyphens."
        ),
    )
    parser.add_argument(
        "--name",
        default=None,
        help=(
            "Human-readable source name. "
            "Default: title-case the slug (hyphens become spaces)."
        ),
    )
    parser.add_argument(
        "--family",
        default="document",
        help=(
            "Source family. One of: document, clinical_document, "
            "technical_document. Default: document."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("scripts/"),
        help="Directory to write the generated script. Default: scripts/",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing file.",
    )
    args = parser.parse_args()

    # Validate slug.
    ok, err = validate_slug(args.slug)
    if not ok:
        print(f"error: {err}", file=sys.stderr)
        return 1

    # Validate family.
    if args.family not in VALID_FAMILIES:
        msg = f"error: unsupported family {args.family!r}."
        if args.family in EXISTING_FAMILY_SCRIPTS:
            msg += (
                f" For {args.family!r} sources, see "
                f"{EXISTING_FAMILY_SCRIPTS[args.family]} as a starting point."
            )
        else:
            msg += f" Valid families: {', '.join(sorted(VALID_FAMILIES))}"
        print(msg, file=sys.stderr)
        return 1

    # Derive names.
    slug = args.slug
    slug_underscored = slug.replace("-", "_")
    name = args.name or slug.replace("-", " ").title()
    family_enum = VALID_FAMILIES[args.family]

    # Format the template.
    output = TEMPLATE.format(
        slug=slug,
        slug_underscored=slug_underscored,
        name=name,
        family_enum=family_enum,
    )

    # Determine output path.
    output_dir = args.output_dir
    if not output_dir.exists():
        print(f"error: output directory {output_dir} does not exist", file=sys.stderr)
        return 1

    output_path = output_dir / f"ingest_{slug_underscored}.py"

    if output_path.exists() and not args.force:
        print(
            f"error: {output_path} already exists. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    # Write the file.
    output_path.write_text(output, encoding="utf-8")

    # Verify the generated script compiles.
    try:
        py_compile.compile(str(output_path), doraise=True)
    except py_compile.PyCompileError as exc:
        print(
            f"warning: generated script has a syntax error: {exc}",
            file=sys.stderr,
        )
        print(f"  File written to {output_path} but may need manual fixes.", file=sys.stderr)
        return 1

    # Summary.
    print(f"Created {output_path}")
    print()
    print("Next steps:")
    print(f"  1. Edit {output_path} and fill in the TODO placeholders:")
    print("     - DESCRIPTION_SHORT and DESCRIPTION_LONG")
    print("     - SOURCE_OWNER_TEAM and SOURCE_OWNER_CONTACTS")
    print("     - SAMPLE_PROMPTS, USAGE_RULES, DATA_FRESHNESS")
    print("  2. Place your extracted corpus in:")
    print(f"     retrieval-hub-data-sources/{slug}/extracted/")
    print("  3. Run the ingestion:")
    print(f"     python {output_path}")
    print("  4. Verify the source appears in the catalog:")
    print("     python -m retrieval_hub_mcp  # then call list_sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
