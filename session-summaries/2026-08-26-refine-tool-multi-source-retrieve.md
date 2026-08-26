# Session Summary: 2026-08-26 — Federated Multi-Source Retrieve (#34)

## What landed

- `9952f7e` — Federated multi-source retrieve with RRF score normalization.
  The `source` parameter on the `retrieve` MCP tool now accepts comma-separated
  slugs (e.g., `"va-cpg,pubmed-hypertension"`) or `"*"` for all queryable
  sources. Results are merged using Reciprocal Rank Fusion (RRF), which uses
  rank position instead of raw cosine scores, making it model-agnostic across
  5 sources using 4 different embedding models.

- Per-source metadata (embedding model, usage rules, data freshness) returned
  in `per_source_metadata` dict on the response. Top-level metadata fields are
  null for multi-source queries. Each hit carries `source_slug` provenance.

- Deployed to `gpt-oss-120b` cluster (build #10). Verified end-to-end via
  mcp-test-mcp: multi-source query across va-cpg + pubmed-hypertension returns
  interleaved results with correct RRF scores and per-source metadata.

- 397 tests (345 core + 52 MCP), all green.

## Epic status

The refine-tool epic and tool ergonomics backlog (#32-#35) are complete:

- #32 Score calibration — closed
- #33 Stable chunk identifiers — closed
- #34 Multi-source retrieve — closed (this session)
- #35 describe_source recipe_content — closed
- Phase 1-4 refine strategies — all shipped
- Phase 5 A/B eval — done (refine aids exploration, not automated RAG)

## Files changed

- `src/retrieval_hub/retrieval/api.py` — `source_slug` on RetrievalResult, `rrf_merge()`, `multi_query()`
- `retrieval-hub-mcp/src/retrieval_hub_mcp/schemas.py` — `source_slug` on RetrievalHit, `SourceRetrievalMetadata`, `per_source_metadata` on RetrievalResponse
- `retrieval-hub-mcp/src/retrieval_hub_mcp/server.py` — `_parse_source_slugs()`, multi-source branch in `retrieve`
- `tests/test_retrieval/test_api.py` — 7 new tests (RRF merge + multi_query)
- `retrieval-hub-mcp/tests/test_server.py` — 9 new tests (multi-source retrieve)

## Design decisions

- **RRF over min-max normalization.** RRF uses rank position (score = 1/(k+rank), k=60),
  avoiding the need to understand each model's score distribution. Well-studied for
  merging ranked lists from heterogeneous retrieval systems.

- **Comma-separated string, not schema change.** Kept `source: str` to avoid MCP schema
  breaks. Comma-separated slugs and `"*"` are parsed server-side. Fully backward
  compatible.

- **No query rewriting for multi-source.** Rewriting is source-specific (uses source
  vocabulary mappings). Multi-source queries skip rewriting and use the raw query
  against all sources.
