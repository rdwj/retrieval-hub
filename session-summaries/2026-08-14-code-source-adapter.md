# Session Summary: Code Source Family Adapter

**Date:** 2026-08-14 (evening session)
**Branch:** main (uncommitted)

## What landed

Built and validated the code-family adapter using the retrieval-hub repo itself as the first worked example.

### New capabilities

1. **AST-aware code chunker** (`src/retrieval_hub/ingestion/chunking/code_ast.py`)
   - Tree-sitter-based, implements the cAST algorithm from EMNLP 2025
   - Recursive AST splitting, sibling merging, scope ancestry headers
   - Produces ~321 tokens/chunk average at 512 budget (117 files -> 327 chunks in 0.18s)
   - Python only for now; tree-sitter approach generalizes to other languages by adding grammars

2. **Code ingestion script** (`scripts/ingest_code_repo.py`)
   - Follows the existing 7-stage ingestion pattern
   - Accepts `--repo` (local path), `--slug`, optional `--name` and `--description`
   - AST-chunks Python files, embeds with jina-code-embeddings-0.5b, writes to pgvector
   - Registers as `family=CODE` with code-appropriate usage rules and git metadata

3. **Prompt-name support in embedders** (`src/retrieval_hub/ingestion/embed.py`)
   - ChunkEmbedder and QueryEmbedder accept optional `prompt_name` parameter
   - When set, passed to `sentence_transformers.encode()` for models with task-specific prefixes
   - Backward compatible -- existing prefix-based behavior unchanged

4. **SourceFamily.CODE dispatched to DocumentAdapter** (`src/retrieval_hub/retrieval/api.py`)
   - Code sources reuse DocumentAdapter since per-recipe config handles model/prefix differences
   - No separate CodeAdapter class needed for MVP

### Evaluation results

Ingested 117 Python files (327 chunks, 105K tokens) from this repo in 44.7s total. Tested retrieval with 5 queries:

| Query | Top Score | Relevant | Assessment |
|-------|-----------|----------|------------|
| Ingestion pipeline overview | 0.77 | 5/5 | Excellent |
| DocumentAdapter definition | 0.64 | 4/5 | Good |
| Query rewriter design | 0.49 | 2/5 | Fair (ambiguous terms) |
| Embedding model support | 0.54 | 5/5 | Excellent |
| Source registration function | 0.70 | 5/5 | Excellent |

### Key decisions

- **Skipped TEI deployment for jina-code-embeddings** -- it's decoder-based (Qwen2.5-Coder backbone) and TEI compatibility isn't confirmed. Used sentence-transformers in-process instead. TEI deployment can be revisited when validated.
- **Reused DocumentAdapter** for code sources rather than creating a separate CodeAdapter. The per-recipe configuration already handles model and prefix differences. A code-specific adapter would only be needed for features like language filtering or symbol-level search.
- **No separate pgvector schema** for code sources. The existing columns (doc_url=file_path, doc_section=scope ancestry) carry code-specific metadata adequately.

## What didn't land

- TEI deployment for jina-code-embeddings (blocked by uncertain compatibility)
- Extended pgvector schema with code-specific columns (file_path, language, symbol_name)
- Multi-language support (only Python grammar loaded)
- Incremental re-indexing (on-demand only)

## Improvement opportunities

- **Minimum chunk size threshold** -- some chunks are only 16 tokens (tiny fragments from sibling merging). A floor of ~50 tokens would reduce noise.
- **Hybrid retrieval** -- BM25 keyword search alongside vector ANN would help navigation queries ("where is X defined?") that are better served by exact match.
- **Query rewriting** -- ambiguous terms ("query" as rewriter vs demo script) suggest the query rewriter feature would materially improve code retrieval.

## Files changed

- `src/retrieval_hub/ingestion/chunking/code_ast.py` (new, 255 lines)
- `src/retrieval_hub/ingestion/chunking/__init__.py` (modified)
- `src/retrieval_hub/ingestion/embed.py` (modified)
- `src/retrieval_hub/adapters/document.py` (modified)
- `src/retrieval_hub/retrieval/api.py` (modified)
- `scripts/ingest_code_repo.py` (new, 410 lines)
