# Session Summary: BM25 Hybrid Retrieval

**Date:** 2026-09-09
**Epic:** platform-quality
**Issue:** #65

## What shipped

BM25 hybrid retrieval via PostgreSQL tsvector + Reciprocal Rank Fusion.
Deployed to cluster (MCP server build #26) and verified end-to-end.

### Schema and write path

- Added `chunk_tsvector TSVECTOR` column to pgvector table DDL
- Added GIN index on tsvector column for fast full-text search
- Both `write_chunks()` and `write_chunk_batch()` now populate tsvector
  at insert time via `to_tsvector('english', chunk_text)`

### Backfill

- Ran `scripts/backfill_tsvector.py` against all 15 cluster index tables
- 53,001 rows updated across tables (from idx_aircraft to idx_va_cpg)
- Script is idempotent (0 rows on re-run)

### Retrieval

- `_bm25_search()`: Full-text search using `ts_rank()` + `plainto_tsquery()`
  with optional `doc_section` filtering
- `_rrf_fuse()`: Merges vector and BM25 ranked lists by chunk UUID using
  Reciprocal Rank Fusion (k=60). Chunks in both lists get summed RRF scores
- Opt-in per source via recipe config `retrieval.hybrid: true`
- Enabled for `va-cpg-clinical-guidelines` (recipe version 4)

### Verification results

Compared vector-only vs hybrid on three benchmark queries:

| Query | Vector top-3 | BM25 top-3 | Hybrid top-3 | BM25 promoted |
|-------|-------------|-----------|-------------|---------------|
| prazosin | [88,204,203] | [88,204,203] | [88,204,203] | 1 |
| PTSD screening criteria | [14,9,40] | [118,27,154] | [12,14,118] | 2 |
| SSRIs | [217,173,107] | [172,67,51] | [173,217,172] | 2 |

Key finding: for definitional/acronym queries where vector and BM25
produce divergent ranked lists, hybrid surfaces results from both
retrieval modes that neither alone would rank in the top 3.

### Tests

9 new tests (39 total in test_document.py), covering RRF fusion logic,
BM25 SQL structure, hybrid wiring, and DDL changes.

## Commit

`56b4ce9` feat: Add BM25 hybrid retrieval via tsvector + RRF fusion (#65)

## What's next

- Re-auth MCP server token and run full eval comparison (hybrid vs
  vector-only) through EvalHub
- Consider enabling hybrid on other document-family sources
- Run `/retro platform-quality` if #65 is considered complete
