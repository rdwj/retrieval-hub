# Next Session — refine-tool

## Next: #34 — Federated multi-source retrieve

Build federated search: a single retrieve call that searches across
multiple sources, normalizes scores across different embedding models,
and returns a merged ranked list. The 4 existing sources use 3 different
embedding models (Nomic, PubMedBERT, Snowflake Arctic), which makes
this a good testbed for cross-model score normalization.

1. **Core retrieval API (`src/retrieval_hub/retrieval/api.py`)**
   Add a `multi_query()` function (or extend `query()`) that accepts
   a list of source slugs (or `"*"` for all queryable sources). For
   each source, embed the query with that source's model, run the
   similarity search, then merge results with normalized scores.

   Score normalization strategy to decide up front: reciprocal rank
   fusion (RRF) is model-agnostic and well-studied for merging ranked
   lists from heterogeneous retrieval systems. Simpler than min-max
   normalization, which requires knowing each model's score distribution.
   Start with RRF unless there's a reason not to.

2. **MCP tool surface (`retrieval-hub-mcp/src/retrieval_hub_mcp/server.py`)**
   Extend `retrieve` so `source` accepts `str | list[str]`. When a list
   is passed, call the federated search. The `"*"` shorthand searches
   all queryable sources. Response shape stays the same (list of hits),
   but each hit already carries `source_slug` provenance — the agent
   sees which source each result came from.

3. **Tests**
   - Unit tests for score normalization (RRF with known inputs)
   - Unit tests for multi-source query routing (correct model per source)
   - Integration test with 2+ mock sources

4. **Smoke test against live data**
   Query across va-cpg + pubmed-hypertension for a clinical question
   that spans both. Verify results are interleaved sensibly and scores
   are comparable.

**Sequencing.** Step 1 first (core API), then step 2 (MCP surface),
then steps 3-4 together (test + validate).

**Session start protocol:**
- Premise checks (~5 min):
  - `git pull` and confirm clean merge
  - `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` — green
  - Local databases up: `pg_isready -h 127.0.0.1 -p 5433` (vectors)
    and `pg_isready -h 127.0.0.1 -p 5434` (catalog)
  - Verify at least 2 sources are queryable (have active physical
    indexes): `SELECT slug, active_physical_index_id FROM source
    WHERE active_physical_index_id IS NOT NULL;`
- Rules with history:
  - Use 127.0.0.1 not localhost for Postgres connections
  - Nomic requires `search_query: ` / `search_document: ` prefixes;
    PubMedBERT and Snowflake do not — the recipe's `query_prefix`
    field handles this per source
  - Embedding models are per-source config; the adapter already
    resolves model name + endpoint from the recipe
- Stop-and-ask before: changing the `retrieve` tool's MCP schema
  (breaking change for existing agents); modifying any pgvector tables
- Close ritual: session summary, commit, update this file.

## What landed this session (2026-08-22, tenth session)

Phase 5 A/B eval — refine does not improve answer quality. See
`session-summaries/2026-08-22-refine-tool-phase5-eval.md`.

- `d6f068e` — eval pipeline extended with `--refine-strategy` and
  `--refine-window` flags. New `_stage_refine()` between retrieve
  and generate, with refined.json caching.
- Adjacent refine eval: context_precision 0.386 (baseline 0.815),
  answer_relevancy 0.678 (baseline 0.735), faithfulness 0.837
  (baseline 0.854). Refine dilutes context precision by ~53%.
- Section eval skipped — adjacent already showed clear degradation.
- Phase 5 closed. Refine tool is valuable for exploration, not
  automated RAG augmentation.

## What landed last session (2026-08-21, ninth session)

doc_title normalization + MCP server deploy. See
`session-summaries/2026-08-21-refine-tool-title-normalization-and-deploy.md`.

- `3d1cae7` — `_normalize_title()` in VA CPG ingestion: HTML entities,
  VA/DOD casing, DIAGNOSI S typo, fragment/generic title fallback to
  section headings, ALL CAPS normalization. 26 canonical titles.
- MCP server deployed to `gpt-oss-120b` cluster (build #6), shipping
  chunk_id + all prior code updates. Verified retrieve/refine work.
- Cluster `idx_va_cpg_nomic_v1` titles normalized via SQL UPDATEs
  (no re-embedding needed — metadata-only change). Verified end-to-end
  via deployed MCP server retrieve.

## What landed last session (2026-08-20, eighth session)

Stable chunk identifiers (#33). See
`session-summaries/2026-08-20-refine-tool-stable-chunk-ids.md`.

- `62f46e4` — chunk_id (pgvector UUID) surfaced in retrieve/refine
  responses; refine accepts optional chunk_id for UUID-based lookup
- `6629200` — lint fix for import ordering
- `54ba54f` — session summary

## What landed earlier (2026-08-20, sessions 1-7)

- Phase 1: refine MCP tool with adjacent-chunk retrieval (`c1c495d`)
- Phase 2: section-aware expansion with token budgeting (`ea5fa67`)
- Phase 3: cross-reference following (`0bda717`)
- Phase 4 research: entity-arc feasibility study (`8c033bd`)
- Phase 4 impl: entity-arc refinement strategy (`29503b5`)
- Tool ergonomics: embedding_model transparency (`c3eb259`), describe_source cleanup (`2026fe0`)
- Tale of Two Cities ingestion + entity-arc validation (`50ef540`)
- Deployment fixes: route trailing slash, missing einops, OOMKill (`ae22366`)

## Remaining epic phases

### ~~Phase 5: A/B eval (refine lift measurement)~~ — Done

Adjacent refine degrades automated eval metrics (context_precision
halved, answer_relevancy and faithfulness slightly worse). Section
eval skipped. The refine tool is valuable for human exploration,
not automated RAG augmentation.

### #34 Multi-source retrieve

Search across sources in one call. Sequenced after the aircraft
maintenance ingestion (data-products epic Phase 4) — urgency increases
with source count. Could be pulled forward with the existing 4 sources
if Phase 5 remains blocked.

## Tool ergonomics backlog (from exercise-tools pass)

- ~~#32 Score calibration~~ — Closed (`c3eb259`).
- ~~#33 Stable chunk identifiers~~ — Closed (`62f46e4`).
- **#34** Multi-source retrieve — after aircraft data ingestion.
- ~~#35 describe_source recipe_content~~ — Closed (`2026fe0`).

## Watch out for

- **Score normalization is the hard part.** Different embedding models
  produce scores on different scales. Cosine similarity from Nomic v1.5
  clusters around 0.7-0.85 for relevant hits; PubMedBERT may differ.
  RRF sidesteps this by using rank position instead of raw scores, but
  verify the merged ranking makes intuitive sense.
- **Query embedding cost scales with source count.** Each unique
  embedding model requires a separate embed call. With 3 models across
  4 sources, that's 3 embed calls per query. Acceptable at 4 sources;
  worth noting for future scaling.
- **Parallel sessions.** The data-products, eval-convergence, and
  model-registry epics may be running concurrently. Don't touch their
  pgvector tables or eval runs.

## If blocked

- **Embedding model not loadable locally.** PubMedBERT and Snowflake
  Arctic may not be cached in `.model_cache/`. If download fails, test
  with just the 2 Nomic sources (va-cpg + tale-of-two-cities) first.
- **Only 1-2 sources queryable.** If some sources lack active physical
  indexes, the implementation still works — test with whatever is
  available and add coverage as more sources come online.
