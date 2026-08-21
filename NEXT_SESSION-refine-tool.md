# Next Session — refine-tool

## Next: Phase 5 planning or #34 multi-source retrieve

All refine-tool implementation (Phases 1-4) and data normalization are
complete and deployed. The epic's remaining work is Phase 5 (A/B eval)
and #34 (multi-source retrieve).

1. **Assess Phase 5 readiness**
   Phase 5 (A/B eval for refine lift) depends on the eval-convergence
   epic having baseline metrics. Check current eval-convergence status.
   If blocked, pull #34 forward.

2. **#34 Multi-source retrieve** (if Phase 5 blocked)
   Search across sources in one call. The 4 existing sources (VA CPG,
   aircraft maintenance, code repo, tale-of-two-cities) are enough to
   build and test. See the tool ergonomics backlog below.

**Session start protocol:**
- Premise checks:
  - `git pull` and confirm clean merge
  - `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` — green
  - Cluster access: `oc whoami --context=gpt-oss-120b`
- Close ritual: session summary, commit, update this file.

## What landed this session (2026-08-21, ninth session)

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

### Phase 5: A/B eval (refine lift measurement)

The epic's gate: does refine actually improve answer quality?

**Dependencies:** Eval-convergence epic chunk-sweep results (in
progress). Refine-tool Phases 1-4 all done.

**Status:** Blocked. Phase 5 unblocks once the eval pipeline has
baseline metrics to compare refine-augmented retrieval against.

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

- **Re-ingestion replaces all rows.** The VA CPG ingestion script uses
  `write_chunks(replace=True)`, which drops and recreates the table
  contents. Confirm the table name before running.
- **Deploy memory limit.** Currently 4Gi, sufficient for Nomic v1.5.
  Don't change unless the embedding model changes.
- **Parallel sessions.** The data-products and eval-convergence epics
  may be running concurrently. Don't touch their pgvector tables.

## If blocked

- **Cluster unavailable for deploy:** Complete normalization and
  re-ingestion locally, commit, and defer deploy to next available
  cluster window.
- **Normalization scope creep:** If title normalization turns into a
  larger framework concern (multiple sources, complex rules), scope
  down to VA CPG only and file a follow-up for a general normalizer.
- **If both items finish quickly:** Pull #34 (multi-source retrieve)
  forward — the 4 existing sources are enough to build and test it.
