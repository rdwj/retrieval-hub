"""Ingest a code repository into the RetrievalHub catalog.

Walks a local code repository, parses Python source files with the AST-aware
chunker (tree-sitter), embeds the chunks with a code-specific embedding model,
and stores them in pgvector. The source is then registered in the catalog with
code-appropriate usage rules.

Usage:

    # 1. Start local dependencies (Ansible playbooks)
    ansible-playbook -i deploy/ansible/inventory/local \
      deploy/ansible/playbooks/local_all_up.yml

    # 2. Apply catalog migrations (one time)
    make migrate

    # 3. Ingest a repository
    python scripts/ingest_code_repo.py \
      --repo /path/to/my-project \
      --slug my-project-code

    # 4. With optional name and description
    python scripts/ingest_code_repo.py \
      --repo /path/to/my-project \
      --slug my-project-code \
      --name "My Project" \
      --description "Internal Python service for widget processing"

The script reports a summary at the end: file/chunk counts, Source UUID,
pgvector table name, and the exact command to query it next.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.ingestion.chunking.code_ast import chunk_code_files
from retrieval_hub.ingestion.register import register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger("ingest_code_repo")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "jinaai/jina-code-embeddings-0.5b"
EMBEDDING_DIMENSION = 896
DOCUMENT_PREFIX = ""  # unused when prompt_name is set
QUERY_PREFIX = ""  # unused when prompt_name is set
DOCUMENT_PROMPT_NAME = "nl2code_document"
QUERY_PROMPT_NAME = "nl2code_query"
CHUNK_TOKENS = 512

SOURCE_OWNER_TEAM = "ai-americas"
SOURCE_OWNER_CONTACTS = ["ai-americas@example.com"]

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)

IGNORE_DIRS = {
    ".venv", "__pycache__", ".git", ".model_cache", ".ruff_cache",
    ".pytest_cache", "node_modules", ".mypy_cache", "htmlcov",
    ".benchmarks", ".cache_ggshield",
}

SAMPLE_PROMPTS: list[tuple[str, str]] = [
    (
        "claude-*",
        (
            "You are a code assistant with access to an indexed codebase. "
            "When answering questions:\n"
            "1. Retrieve relevant code using the retrieve tool.\n"
            "2. Reference specific files and functions by name.\n"
            "3. Note that the index is from a specific commit and may be outdated.\n"
            "4. If the retrieved code doesn't answer the question, say so explicitly."
        ),
    ),
]

USAGE_RULES: dict = {
    "citation": (
        "Reference code by file path and function/class name. "
        "Include the doc_url field (file path) when citing results."
    ),
    "scope_disclaimer": (
        "This index was built from a specific commit. "
        "Code may have changed since indexing. Always verify against the live repository."
    ),
    "handling": (
        "Code snippets are from a specific point in time. "
        "Do not assume the current codebase matches these results."
    ),
    "custom_rules": [
        "When showing code results, include the file path from doc_url.",
        "If multiple chunks come from the same file, note that to the user.",
        "The doc_section field contains the scope ancestry (e.g., ClassName.method_name).",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_name_from_slug(slug: str) -> str:
    """Derive a pgvector table name from the source slug."""
    return f"idx_{slug.replace('-', '_')}_v1"


def _detect_github_repo(repo_path: Path) -> str | None:
    """Extract ``owner/repo`` from the git origin remote, if it's on GitHub.

    Handles both HTTPS (``https://github.com/owner/repo.git``) and SSH
    (``git@github.com:owner/repo.git``) URLs.  Returns *None* when the
    remote is absent, not a GitHub URL, or any error occurs.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        url = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    # HTTPS: https://github.com/owner/repo.git
    m = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)

    # SSH: git@github.com:owner/repo.git
    m = re.match(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)

    return None


def _recipe_content(table_name: str, github_repo: str | None = None) -> dict:
    """Return the recipe content dict that will be stored on RecipeVersion."""
    content = {
        "parser": {"kind": "tree_sitter_python"},
        "chunker": {
            "kind": "ast_treesitter",
            "chunk_size_tokens": CHUNK_TOKENS,
            "encoding": "cl100k_base",
        },
        "embedding": {
            "model": EMBEDDING_MODEL,
            "dimension": EMBEDDING_DIMENSION,
            "normalize": True,
            "document_prefix": DOCUMENT_PREFIX,
            "query_prefix": QUERY_PREFIX,
            "document_prompt_name": DOCUMENT_PROMPT_NAME,
            "query_prompt_name": QUERY_PROMPT_NAME,
        },
        "backend": {
            "kind": "pgvector",
            "table": table_name,
        },
        "retrieval": {
            "default_pattern": "vector_ann",
            "supported_patterns": ["vector_ann"],
            "parameters": {
                "vector_ann": {"top_k_default": 10, "top_k_max": 50},
            },
        },
    }
    if github_repo:
        content["github_repo"] = github_repo
    return content


def _git_info(repo_path: Path) -> tuple[str, str]:
    """Return (commit_sha, branch) for the repository, or fallback values."""
    sha = "unknown"
    branch = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        sha = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("could not read git SHA from %s", repo_path)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, check=True,
        )
        branch = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("could not read git branch from %s", repo_path)

    return sha, branch


def _walk_python_files(repo_path: Path) -> list[tuple[str, str]]:
    """Walk the repo and return (source_text, relative_path) for each .py file."""
    files = []
    for py_file in sorted(repo_path.rglob("*.py")):
        if any(part in IGNORE_DIRS for part in py_file.parts):
            continue
        rel_path = str(py_file.relative_to(repo_path))
        try:
            source = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if source.strip():
            files.append((source, rel_path))
    return files


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def _run_ingestion(
    repo_path: Path,
    slug: str,
    name: str | None,
    description: str | None,
    db_url: str,
    vectors_db_url: str,
    github_repo: str | None = None,
) -> int:
    """Execute the full ingestion pipeline end-to-end."""
    wall_start = time.monotonic()
    repo_path = repo_path.resolve()
    repo_name = repo_path.name
    table_name = _table_name_from_slug(slug)

    if not repo_path.is_dir():
        logger.error("repository path does not exist: %s", repo_path)
        return 1

    # Derive name/description from slug if not provided.
    source_name = name or f"Code: {repo_name}"
    description_short = description or (
        f"Python source code from the {repo_name} repository."
    )
    description_long = (
        f"AST-aware ingestion of Python source files from {repo_name}. "
        f"Uses tree-sitter for parsing, the cAST chunking algorithm at "
        f"{CHUNK_TOKENS} tokens, and {EMBEDDING_MODEL} for code-specific "
        f"embeddings stored in pgvector."
    )

    # Git metadata for data_freshness.
    git_sha, git_branch = _git_info(repo_path)

    # Detect GitHub repo (CLI override takes precedence over auto-detection).
    if github_repo is None:
        github_repo = _detect_github_repo(repo_path)
    if github_repo:
        logger.info("GitHub repository: %s", github_repo)

    # Stage 1: walk the repository for Python files.
    logger.info("walking repository at %s", repo_path)
    py_files = _walk_python_files(repo_path)
    logger.info("found %d Python files", len(py_files))

    if not py_files:
        logger.error("no Python files found in %s; aborting", repo_path)
        return 1

    # Stage 2+3: parse and chunk (AST-aware, no separate normalize step).
    logger.info("chunking %d files with AST chunker (budget=%d tokens)", len(py_files), CHUNK_TOKENS)
    all_chunks = chunk_code_files(py_files, chunk_tokens=CHUNK_TOKENS)
    logger.info("produced %d chunks total", len(all_chunks))

    if not all_chunks:
        logger.error("no chunks produced; aborting")
        return 1

    # Stage 4: embed.
    from retrieval_hub.ingestion.embed import ChunkEmbedder

    embed_start = time.monotonic()
    embedder = ChunkEmbedder(
        model_name=EMBEDDING_MODEL,
        document_prefix=DOCUMENT_PREFIX,
        prompt_name=DOCUMENT_PROMPT_NAME,
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

    # Stage 5: write to pgvector.
    ensure_pgvector_schema(vectors_db_url, table_name, actual_dim)
    write_stats = write_chunks(
        vectors_db_url,
        table_name,
        all_chunks,
        embeddings,
    )
    logger.info(
        "wrote %d rows to %s (%d tokens)",
        write_stats.rows_written,
        write_stats.table,
        write_stats.total_tokens,
    )

    # Stage 6: build data_freshness with git info.
    source_url = (
        f"https://github.com/{github_repo}"
        if github_repo
        else f"file://{repo_path}"
    )
    data_freshness = {
        "source_name": f"Code Repository: {repo_name}",
        "source_url": source_url,
        "last_refreshed": datetime.now(UTC).strftime("%Y-%m-%d"),
        "refresh_cadence": "on_demand",
        "staleness_note": "Re-run ingestion to update after code changes.",
        "commit_sha": git_sha,
        "branch": git_branch,
    }

    # Stage 7: register source + recipe + physical index in the catalog.
    session_factory = make_session_factory(create_db_engine(db_url))
    with session_factory() as session:
        result = register_document_source(
            session,
            slug=slug,
            name=source_name,
            description_short=description_short,
            description_long=description_long,
            owner_team=SOURCE_OWNER_TEAM,
            owner_contacts=SOURCE_OWNER_CONTACTS,
            recipe_content=_recipe_content(table_name, github_repo=github_repo),
            physical_index_location=table_name,
            document_count=len(py_files),
            chunk_count=len(all_chunks),
            sample_prompts=SAMPLE_PROMPTS,
            usage_rules={**USAGE_RULES, "data_freshness": data_freshness},
            triggered_by="script:ingest_code_repo",
            family=SourceFamily.CODE,
        )

    wall_elapsed = time.monotonic() - wall_start

    # Final summary.
    print()
    print("=" * 72)
    print("Code repository ingestion complete")
    print("=" * 72)
    print(f"  Repository           : {repo_path}")
    print(f"  Branch               : {git_branch}")
    print(f"  Commit               : {git_sha[:12]}")
    print(f"  Python files         : {len(py_files)}")
    print(f"  Chunks               : {len(all_chunks)}")
    print(f"  Tokens embedded      : {write_stats.total_tokens}")
    print(f"  Embedding model      : {EMBEDDING_MODEL}")
    print(f"  Embedding dimension  : {actual_dim}")
    print(f"  pgvector table       : {table_name}")
    print()
    print(f"  Source slug          : {result.source_slug}")
    print(f"  Source UUID          : {result.source_id}")
    print(f"  Recipe version       : v{result.recipe_version_number}")
    print(f"  Physical index       : {result.physical_index_id}")
    print()
    print(f"  Total wall time      : {wall_elapsed:.1f}s")
    print()
    print("Next: start the MCP server and query the source with")
    print(f'  retrieve(source="{slug}", query="how does the auth module work")')
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="Path to the code repository",
    )
    parser.add_argument(
        "--slug",
        required=True,
        help="Source slug for the catalog",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Human-readable source name (default: derived from slug)",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="Short description (default: auto-generated)",
    )
    parser.add_argument(
        "--github-repo",
        default=None,
        help=(
            "GitHub owner/repo (e.g., rdwj/retrieval-hub). "
            "Auto-detected from git remote origin when omitted."
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
        repo_path=args.repo,
        slug=args.slug,
        name=args.name,
        description=args.description,
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
        github_repo=args.github_repo,
    )


if __name__ == "__main__":
    sys.exit(main())
