# Session Summary — 2026-08-31 · Self-Serve Onboarding · Phases 2, 3a, 3b complete

**Plan:** NEXT_SESSION-self-serve-onboarding.md   **Commits:** 81656a3..19ed9bc (main)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: prove ProcessAdapter end-to-end, data card auto-population, create tabular data + adapter.
Shipped: all three. Slipped: none, though embedding pod stability cost significant session time.
Scope: stayed in scope. Added embedding resilience work (retry, watchdog, TEI tuning) as a necessary
side effect of running batch ingestion against the cluster.

## Shipped
- `81656a3` — Data card auto-population: `describe_source` returns `eval_baseline` and `chunk_config`
  from `build_metadata`. `onboard_source.py` writes these on every ingestion. Backfilled `aircraft-sb-test`.
- `0563291` — TabularAdapter + tabular chunker + embedding retry resilience. TabularAdapter with
  `table_context` refine. Tabular chunker reads JSONL, renders rows to NL text. Retry catches
  `RemoteProtocolError` and 429, max retries bumped to 10, inter-batch delay + periodic cooldown.
  `embedding_batch_size` exposed on `ingest()` (default 2).
- `19ed9bc` — CLAUDE.md lesson: TEI CPU memory leak under sustained batch embedding.
- Companion repo: 200 ClinicalTrials.gov hypertension studies downloaded to
  `retrieval-hub-data-sources/clinicaltrials-hypertension/` (download script, OVERVIEW, JSONL).
- Cluster: TEI nomic pod bumped 8Gi to 32Gi, `--max-client-batch-size 8` added.

## Verification & confidence
- **Phase 2:** Backfilled `aircraft-sb-test`, queried `build_metadata` — `eval_baseline` and
  `chunk_config` hydrate correctly through the Pydantic schema. Confidence: high.
- **Phase 3b:** 2,456 chunks ingested. SQL verified `instructions/step-N` and `header` doc_section
  patterns. `procedure` refine tested on SB 1006B — returned 17 chunks (11 steps + preamble + headers)
  in correct order. Confidence: high.
- **Phase 3a:** 307 chunks ingested from 200 studies. Source registered as `tabular` family, `curated`
  status. `chunk_tabular_data()` tested standalone (correct NCT IDs in doc_section). TabularAdapter
  imports clean. Confidence: high (chunking + wiring). Medium (refine strategy untested against
  live cluster MCP — only import and unit-level verification done).
- All 411 tests pass (359 core + 52 MCP).

## Judgment calls & deviations
- TEI pod OOMed repeatedly (8Gi, 12Gi, 16Gi, 32Gi) during batch embedding. Fixed with batch_size=2,
  10 retries with exponential backoff, self-healing port-forward watchdog, and 32Gi. Total embedding
  time for 2,456 process chunks: ~90 minutes with 4 pod restart cycles.
- Kept `embedding_batch_size` default at 2 (not 8 or 32) because TEI CPU leaks memory under sustained
  load. This makes future ingestion slow but reliable.
- Clinical trials download used stdlib `urllib.request` instead of `requests` to avoid adding
  dependencies to the companion repo.

## Backlog delta
Filed: none. Closed: none. Deferred: Phase 3c (Graph), Phase 3d (External) to separate sessions.
Memory: none new (TEI lesson captured in CLAUDE.md instead).

## Drift & forward-collisions
- Backward: none. No open issues affected by this session's work.
- Forward: none.

## For the reviewer
- Sanity-check: the `embedding_batch_size=2` default is conservative. If TEI memory management
  improves (or we swap to vLLM for embedding), bump it back to 8-16.
- Thin verification: TabularAdapter `table_context` refine strategy was not tested end-to-end via the
  MCP server against live data. Import + code review only.
- Wants guidance: should we pursue checkpointed embedding (save intermediate vectors to disk, resume
  after crash) to make large ingestion runs idempotent? The TEI OOM pattern will recur for any
  dataset over ~500 chunks.

## Risks / watch-fors
- TEI CPU memory leak is a recurring cost for any large ingestion. Current workaround (survive
  restarts) works but is fragile and slow. Consider vLLM embedding deployment or checkpointed
  embedding pipeline as a proper fix.
- The 32Gi TEI pod is expensive for a service that handles single-text queries 99% of the time.
  Consider an HPA that scales to 2 replicas under load, or a separate "batch embedding" deployment
  with higher memory that spins down when idle.
