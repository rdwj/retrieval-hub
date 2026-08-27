"""Generic ingestion pipeline: data directory to registered source in one call.

Composes the existing per-stage functions (fetch, parse, normalize, chunk,
embed, write, register) into a single ``ingest()`` entry point. Dispatches
by family to the appropriate parser and chunker.

Supported families:

- ``document``, ``clinical_document``, ``technical_document``: walk data_dir
  for markdown / text / HTML / PDF files, parse via Docling / BS4, chunk with
  the token-fixed chunker.
- ``code``: walk data_dir for ``.py`` files, chunk with the AST-aware chunker.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
from retrieval_hub.ingestion.chunking.bioc_section import chunk_bioc_document
from retrieval_hub.ingestion.chunking.code_ast import chunk_code_files
from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.embed import ChunkEmbedder
from retrieval_hub.ingestion.fetch import FetchedDocument
from retrieval_hub.ingestion.normalize import normalize_document
from retrieval_hub.ingestion.parse import parse_document
from retrieval_hub.ingestion.register import RegistrationResult, register_document_source
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks
from retrieval_hub.model_registry import try_resolve_endpoint
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger(__name__)

_DOCUMENT_FAMILIES = {"document", "clinical_document", "technical_document"}
_CODE_FAMILIES = {"code"}

_FILE_EXTENSIONS = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
}

_FAMILY_ENUM_MAP: dict[str, SourceFamily] = {
    "document": SourceFamily.DOCUMENT,
    "clinical_document": SourceFamily.CLINICAL_DOCUMENT,
    "technical_document": SourceFamily.TECHNICAL_DOCUMENT,
    "code": SourceFamily.CODE,
}

_SKIP_STEMS = frozenset({
    "readme", "index", "license", "contributing", "changelog",
})


def _load_documents(data_dir: Path) -> list[FetchedDocument]:
    """Walk data_dir for supported document files.

    Extends load_corpus_tree() to handle .txt, .html, .htm, and .pdf in
    addition to .md files.
    """
    data_dir = Path(data_dir)
    docs: list[FetchedDocument] = []

    for ext, content_type in _FILE_EXTENSIONS.items():
        for file_path in data_dir.rglob(f"*{ext}"):
            if file_path.stem.lower() in _SKIP_STEMS:
                continue

            relative = file_path.relative_to(data_dir)
            parts = relative.parent.parts
            title = "/".join(parts) + "/" + relative.stem if parts else relative.stem

            metadata: dict[str, str] = {"source": "pipeline"}
            if len(parts) >= 1:
                metadata["category"] = parts[0]
            metadata["document_type"] = relative.stem

            if content_type == "application/pdf":
                raw = file_path.read_bytes()
                content = ""
            else:
                content = file_path.read_text(encoding="utf-8")
                raw = content.encode("utf-8")

            docs.append(FetchedDocument(
                url=f"file://{file_path.resolve()}",
                title=title,
                content=content,
                content_type=content_type,
                raw_bytes=raw,
                metadata=metadata,
            ))

    docs.sort(key=lambda d: d.title)
    logger.info("pipeline._load_documents dir=%s count=%d", data_dir, len(docs))
    return docs


def _load_bioc_documents(data_dir: Path) -> list[tuple[Any, str]]:
    """Load BioC JSON files from data_dir.

    Returns list of (parsed_json, filename) tuples.
    """
    results = []
    for json_path in sorted(data_dir.rglob("*.json")):
        if json_path.stem.lower() in _SKIP_STEMS:
            continue
        data = json.loads(json_path.read_text(encoding="utf-8"))
        results.append((data, json_path.stem))
    logger.info("pipeline._load_bioc_documents dir=%s count=%d", data_dir, len(results))
    return results


def _load_code_files(data_dir: Path) -> list[tuple[str, str]]:
    """Load Python source files from data_dir.

    Returns list of (source_text, file_path) tuples for chunk_code_files().
    """
    files = []
    for py_path in sorted(data_dir.rglob("*.py")):
        if py_path.stem.lower().startswith("__"):
            continue
        source = py_path.read_text(encoding="utf-8")
        rel = str(py_path.relative_to(data_dir))
        files.append((source, rel))
    logger.info("pipeline._load_code_files dir=%s count=%d", data_dir, len(files))
    return files


def _make_table_name(slug: str, suffix: str) -> str:
    """Build a pgvector table name from slug and suffix."""
    return f"idx_{slug.replace('-', '_')}_{suffix}"


def _make_recipe(
    *,
    family: str,
    chunk_tokens: int,
    overlap_tokens: int,
    embedding_model: str,
    document_prefix: str,
    table_name: str,
) -> dict[str, Any]:
    """Build a recipe content dict."""
    return {
        "parser": "generic_pipeline",
        "chunker": {
            "kind": "token_fixed",
            "chunk_tokens": chunk_tokens,
            "overlap_tokens": overlap_tokens,
        },
        "embedding": {
            "model": embedding_model,
            "document_prefix": document_prefix,
        },
        "backend": {
            "kind": "pgvector",
            "table": table_name,
        },
    }


def ingest(
    *,
    data_dir: Path,
    slug: str,
    name: str,
    family: str,
    description_short: str,
    description_long: str = "",
    owner_team: str = "platform",
    owner_contacts: list[str] | None = None,
    db_url: str,
    vectors_db_url: str,
    chunk_tokens: int = 512,
    overlap_tokens: int = 0,
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5",
    embedding_endpoint: str | None = None,
    document_prefix: str = "search_document: ",
    table_suffix: str = "v1",
    sample_prompts: list[tuple[str, str]] | None = None,
    usage_rules: dict[str, Any] | None = None,
) -> RegistrationResult:
    """Run the full ingestion pipeline: data directory to registered source.

    Parameters
    ----------
    data_dir:
        Directory containing source documents.
    slug:
        URL-safe source identifier.
    name:
        Human-readable source name.
    family:
        Source family (document, clinical_document, technical_document, code).
    description_short, description_long:
        Source descriptions for the catalog.
    owner_team:
        Owning team name.
    owner_contacts:
        Contact emails for the owning team.
    db_url:
        Catalog database URL.
    vectors_db_url:
        pgvector database URL.
    chunk_tokens:
        Target chunk size in tokens.
    overlap_tokens:
        Overlap between adjacent chunks in tokens.
    embedding_model:
        Model name for embedding chunks.
    embedding_endpoint:
        Remote embedding endpoint URL. If None, resolved from model registry
        or falls back to local embedding.
    document_prefix:
        Prefix prepended to chunk text before embedding.
    table_suffix:
        Suffix for the pgvector table name (e.g., "v1", "256_0").
    sample_prompts:
        Optional (llm_family_pattern, prompt_text) pairs.
    usage_rules:
        Optional usage rules dict for the source.
    """
    data_dir = Path(data_dir)
    owner_contacts = owner_contacts or []
    table_name = _make_table_name(slug, table_suffix)

    if family not in _DOCUMENT_FAMILIES and family not in _CODE_FAMILIES:
        raise ValueError(
            f"Unsupported family {family!r}. "
            f"Supported: {sorted(_DOCUMENT_FAMILIES | _CODE_FAMILIES)}"
        )

    # --- Stage 1-4: Load, parse, normalize, chunk ---
    chunks: list[Chunk] = []
    doc_count = 0

    if family in _DOCUMENT_FAMILIES:
        bioc_docs = _load_bioc_documents(data_dir)
        if bioc_docs:
            for bioc_data, bioc_name in bioc_docs:
                bioc_chunks = chunk_bioc_document(
                    bioc_data,
                    doc_url=f"file://{data_dir / bioc_name}.json",
                    doc_title=bioc_name,
                    chunk_tokens=chunk_tokens,
                    overlap_tokens=overlap_tokens,
                )
                chunks.extend(bioc_chunks)
                doc_count += 1
        else:
            fetched = _load_documents(data_dir)
            doc_count = len(fetched)
            for doc in fetched:
                parsed = parse_document(doc)
                normalized = normalize_document(parsed)
                if normalized is None:
                    logger.warning(
                        "pipeline.ingest skip_short_doc title=%s", doc.title,
                    )
                    doc_count -= 1
                    continue
                doc_chunks = chunk_document(
                    normalized,
                    chunk_tokens=chunk_tokens,
                    overlap_tokens=overlap_tokens,
                )
                chunks.extend(doc_chunks)

    elif family in _CODE_FAMILIES:
        code_files = _load_code_files(data_dir)
        doc_count = len(code_files)
        chunks = chunk_code_files(
            code_files,
            chunk_tokens=chunk_tokens,
        )

    if not chunks:
        raise ValueError(
            f"No chunks produced from {data_dir}. Check that the directory "
            f"contains supported files for the {family!r} family."
        )

    logger.info(
        "pipeline.ingest slug=%s docs=%d chunks=%d",
        slug, doc_count, len(chunks),
    )

    # --- Stage 5: Embed ---
    if embedding_endpoint is None:
        embedding_endpoint = try_resolve_endpoint(db_url, embedding_model)

    embedder = ChunkEmbedder(
        model_name=embedding_model,
        endpoint=embedding_endpoint,
        document_prefix=document_prefix,
    )
    embeddings = embedder.embed_chunks(chunks)
    dimension = embedder.dimension

    # --- Stage 6: Write to pgvector ---
    ensure_pgvector_schema(vectors_db_url, table_name, dimension)
    stats = write_chunks(vectors_db_url, table_name, chunks, embeddings)
    logger.info(
        "pipeline.ingest write table=%s rows=%d tokens=%d",
        stats.table, stats.rows_written, stats.total_tokens,
    )

    # --- Stage 7: Register in catalog ---
    recipe = _make_recipe(
        family=family,
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        embedding_model=embedding_model,
        document_prefix=document_prefix,
        table_name=table_name,
    )

    family_enum = _FAMILY_ENUM_MAP.get(family, SourceFamily.DOCUMENT)
    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        result = register_document_source(
            session,
            slug=slug,
            name=name,
            description_short=description_short,
            description_long=description_long or description_short,
            owner_team=owner_team,
            owner_contacts=owner_contacts,
            recipe_content=recipe,
            physical_index_location=table_name,
            document_count=doc_count,
            chunk_count=len(chunks),
            sample_prompts=sample_prompts,
            usage_rules=usage_rules,
            triggered_by="pipeline:ingest",
            family=family_enum,
        )

    logger.info(
        "pipeline.ingest registered slug=%s source_id=%s created=%s",
        result.source_slug, result.source_id, result.created_source,
    )
    return result
