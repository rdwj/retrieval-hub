# Retrospective: Code Source Epic

**Date:** 2026-08-18
**Effort:** Add code source family to retrieval-hub -- AST-aware chunking, code-specific embeddings, live GitHub file fetch, quality hardening
**Issues:** Closed #8, #11, #12, #13, #14
**Commits:** `9b548c6`..`8357f81` (4 feat commits across 2 sessions)

## What We Set Out To Do

Add a `code` source family so retrieval-hub can index and search codebases. The plan covered tree-sitter-based AST chunking, code-specific embeddings (jina-code-embeddings-0.5b), a full ingestion pipeline, and extending the `retrieve` MCP tool with live GitHub file fetch so agents get both indexed search and fresh file access.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Skipped TEI deployment for jina-code-embeddings | Scope deferral | Decoder-based model with uncertain TEI compatibility. In-process sentence-transformers adequate for dev. |
| Reused DocumentAdapter instead of new CodeAdapter | Good pivot | Per-recipe config handles model/prefix differences. Separate adapter only needed for language filtering or symbol search. |
| Recipe resolution through PhysicalIndex chain | Bug fix | Source.recipe_version_id not populated by register_document_source. Caught during end-to-end testing of file fetch. |
| Fixed MCP server test infrastructure | Missed (pre-existing) | pytest-asyncio mode never configured; all async tests silently skipped. Added asyncio_mode=auto and fixed mock setup. |

## What Went Well

- cAST chunking algorithm worked first try: 321 tokens/chunk average, good retrieval quality on 4/5 test queries
- Live GitHub file fetch was clean: one async helper, rate limit logging, same RetrievalResponse shape, 4 tests
- Auto-detecting `github_repo` from git remote eliminated manual config
- min_tokens post-processing (merge small chunks after AST splitting) was the right separation of concerns
- Extracting `_build_response()` eliminated the duplicated usage_rules/data_freshness assembly

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Python-only chunking (no other tree-sitter grammars) | Accept | Fine for MVP, add grammars when needed |
| No incremental re-indexing | Accept | On-demand re-ingest adequate |
| GitHub 60/hr rate limit could block demos | Accept | PAT fallback documented but not implemented |
| Hybrid retrieval (BM25) for navigation queries | Follow-up | "Where is X defined?" queries underserved by vector-only |
| Query rewriting for code | Follow-up | Ambiguous terms ("query") hurt retrieval; next epic |

## Action Items

- [x] Write session summary for 2026-08-18
- [ ] Archive NEXT_SESSION-code-source.md

## Patterns

First retro in this project, so no cross-retro patterns yet. Noting for future reference:

**Continue:** Sub-agent delegation for independent implementation tasks. Parallel work on chunker + recipe changes saved wall-clock time. End-to-end testing after integration caught the recipe resolution bug that unit tests missed.

**Start:** Run MCP server tests as part of the standard check (they were silently broken). Consider adding a CI step or Makefile target that covers both test suites.

**Watch:** Model downloads during ingestion can dominate session time (13 min this session). Pre-warming the model cache before sessions that involve re-ingestion would help.
