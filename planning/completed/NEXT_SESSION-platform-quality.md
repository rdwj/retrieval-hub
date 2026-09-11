# Next Session -- Platform Quality

## Epic: Hybrid retrieval and cross-cutting quality improvements

Add BM25 lexical search alongside vector ANN for all families that use
pgvector. The single biggest retrieval quality improvement identified
across the project's eval work.

Issues: #65

## Next: BM25 hybrid retrieval (#65)

Add a tsvector column to pgvector index tables, implement hybrid
scoring (vector ANN + BM25 via RRF or weighted sum), and verify the
lift on navigation queries.

1. **Schema: add tsvector column + GIN index**
   Add `chunk_tsvector TSVECTOR` to `_create_table_sql()` in
   `src/retrieval_hub/ingestion/write.py`. Populate via
   `to_tsvector('english', chunk_text)` at insert time. Create a
   GIN index on the column. This is the foundation for all FTS
   queries.

2. **Write path: populate tsvector during ingestion**
   Update `write_chunks()` (line 76) and `write_chunk_batch()`
   (line 159) in `write.py` to include `chunk_tsvector` in the
   INSERT. Use `to_tsvector('english', %s)` in the SQL so Postgres
   computes the tsvector server-side.

3. **Backfill existing tables**
   Write a migration script (`scripts/backfill_tsvector.py`) that:
   - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS chunk_tsvector TSVECTOR`
   - `UPDATE ... SET chunk_tsvector = to_tsvector('english', chunk_text)`
   - `CREATE INDEX IF NOT EXISTS ... USING GIN (chunk_tsvector)`
   Run against all 15 index tables in the cluster vectors DB. This
   is a data-mutating operation on production -- stop-and-ask.

4. **Retrieval: hybrid scoring in DocumentAdapter**
   Add a `_hybrid_search()` method to `DocumentAdapter` that
   combines vector ANN and BM25 results. Two approaches to evaluate:
   - **RRF fusion** (separate queries, merge ranks) -- reuses the
     existing `rrf_merge()` pattern from `api.py`. Simpler, no
     schema coupling, but 2x queries.
   - **Single-query** -- `ts_rank(chunk_tsvector, query) + cosine`
     in one SQL query. Faster but harder to tune alpha.
   Start with RRF (simpler). Wire it into `retrieve()` with a
   recipe-level config flag (`retrieval.hybrid: true`).

5. **Verify: benchmark on VA CPG**
   Compare hybrid vs. vector-only on navigation queries that
   vector search is known to underserve: exact term lookups
   ("prazosin"), definitional queries ("PTSD screening criteria"),
   code/acronym queries ("SSRIs", "CBT-P"). Use the existing
   eval harness or a quick ad-hoc comparison.

**Sequencing.** Steps 1-3 are schema work (sequential). Step 4 is
the retrieval logic. Step 5 is verification. Steps 1-2 can be
tested locally; step 3 hits the cluster.

**Constraints for the session:**
- Schema changes to the vectors DB use raw SQL in `write.py`, not
  Alembic. The vectors DB is a separate database from the catalog.
- All adapters inherit from `DocumentAdapter`, so hybrid search
  in `DocumentAdapter._similarity_search()` benefits graph, process,
  and tabular families automatically.
- The existing `_keyword_search_with_scores()` method (document.py
  line 513) is an ILIKE-based precedent -- BM25 via tsvector is
  the proper replacement.
- 15 index tables exist in the cluster vectors DB. The backfill
  script must handle all of them.

**Session start protocol:**
- Premise checks: `oc get pods --context=gpt-oss-120b -n retrieval-hub`
  (PG and vLLM still running?). `git log --oneline -5` (no surprise
  merges?). Quick port-forward check that the vectors DB is accessible
  and tables exist.
- Rules with history: Use `127.0.0.1` not `localhost` for port-forward
  DB connections (CLAUDE.md). Use `--context=gpt-oss-120b -n retrieval-hub`
  on every oc command.
- Stop-and-ask before: running the backfill script against the cluster
  vectors DB (step 3). This adds a column and creates an index on all
  15 production tables.
- Close ritual: session summary + `/plan-next-session platform-quality`
  (or `/retro platform-quality` if #65 is complete and the epic is done).

## Remaining epic phases

None. This is a single-phase epic. If #65 ships, run `/retro` to close.

## What landed last session (2026-09-09)

Platform-ops Phase 4 completed: ingestion Job runner shipped and
verified end-to-end. TEI cooldown sleeps removed. Lazy imports fixed.
All platform-ops issues closed (#27, #66, #67, #70).

**See:** session-summaries/2026-09-09-platform-ops-phase4-ingestion-jobs.md

## Watch out for

- The port-forward to the vectors DB may already be running from a
  previous session. Check `lsof -i :5433` before starting a new one.
- Some of the 15 index tables are sweep/test artifacts (e.g.,
  `idx_aircraft_maintenance_sweep`, `idx_va_cpg_biolord_v1`). The
  backfill should still cover them (harmless), but the benchmark
  should use the active `_v1` tables.
- The `to_tsvector('english', ...)` config assumes English text.
  Non-English sources would need a different text search config.
  All current sources are English.
- pgvector tables currently have NO indexes at all -- not even HNSW
  on the embedding column. The GIN index for tsvector will be the
  first secondary index. Consider adding HNSW while we're at it
  (separate from BM25, but good hygiene).

## If blocked

- If the vectors DB is inaccessible, the schema and retrieval work
  (steps 1, 2, 4) can all be done and tested locally using the
  Ansible playbook (`local_pgvector_up.yml`). Only the backfill
  (step 3) needs the cluster.
- If vLLM is down (no embedding endpoint), use pre-existing embedded
  data in the local vectors DB for benchmarking.
