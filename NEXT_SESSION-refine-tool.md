# Next Session — refine-tool

## Next: doc_title normalization + deploy chunk_id to production

Ship the chunk_id changes (`62f46e4`) to the deployed MCP server and
clean up the doc_title inconsistencies in the VA CPG source. Small
session that closes out the #33 work completely.

1. **Normalize doc_title values during ingestion**
   The VA CPG titles have four classes of inconsistency:
   - Mixed case: `VA/DOD` vs `VA/DoD` (should pick one canonical form)
   - Fragment title: `for the treatment of nightmares associated with PTSD`
     (should be the full guideline title)
   - HTML entities: `&amp;` in the hip/knee osteoarthritis title
   - Duplicate generic titles: two rows differ only in `VA/DOD` vs `VA/DoD`

   Add a title-normalization step to the VA CPG ingestion script. This
   requires re-ingestion of the VA CPG data (the normalization happens at
   write time, not query time). Approach options: normalize in the
   ingestion script itself, or add a reusable normalizer in the chunking
   pipeline. Decide during the session based on whether other sources
   (pubmed, tale-of-two-cities) also need normalization.

2. **Deploy the updated MCP server**
   The deployed server is running pre-chunk_id code. Build and deploy
   with the chunk_id changes + any normalization updates. Follow the
   deployment checklist from CLAUDE.md lessons learned:
   - Verify `requirements-deploy.txt` has all deps
   - Confirm memory limit (currently 4Gi, should be fine)
   - Route path has no trailing slash
   - Test with a retrieve query after deploy to confirm chunk_id appears

**Sequencing.** Normalization first (requires re-ingestion of VA CPG),
then deploy (ships both chunk_id and normalized titles together).

**Session start protocol:**
- Premise checks:
  - `git pull` and confirm clean merge.
  - `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` — green
    baseline (should be 245 + 43).
  - Local databases up: `pg_isready -h localhost -p 5433` (vectors)
    and `pg_isready -h localhost -p 5434` (catalog).
  - Verify current doc_title state:
    `psql ... -c "SELECT DISTINCT doc_title FROM idx_va_cpg_v1"` —
    should show the 28 titles with inconsistencies listed above.
  - Check cluster access for deploy: `oc whoami --context=mcp-rhoai`
- Rules with history:
  - Embedding model comes from the recipe version — use
    `_embedding_model_name()` and `_query_prefix()`, never hardcode.
  - Container deps must be explicit in `requirements-deploy.txt` —
    local venv masks transitive deps (see CLAUDE.md lessons learned).
  - Route path in `openshift.yaml` must not have trailing slash for
    FastMCP (see CLAUDE.md lessons learned).
- Stop-and-ask before: Re-ingesting VA CPG data (replaces all rows
  in `idx_va_cpg_v1`). Confirm the table name and that no other
  session is using it. Also stop-and-ask before any deploy to
  production.
- Close ritual: session summary, commit, update this file.

## What landed last session (2026-08-20, eighth session)

Stable chunk identifiers (#33). See
`session-summaries/2026-08-20-refine-tool-stable-chunk-ids.md`.

- `62f46e4` — chunk_id (pgvector UUID) surfaced in retrieve/refine
  responses; refine accepts optional chunk_id for UUID-based lookup
- `6629200` — lint fix for import ordering
- `54ba54f` — session summary

Deferred: doc_title normalization (step 4 of #33) — requires ingestion
pipeline changes and data re-ingestion.

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
