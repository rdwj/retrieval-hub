# Next Session — refine-tool

## Next: Stable chunk identifiers (#33)

Add a `chunk_id` field (the pgvector row UUID) to retrieve and refine
responses so consuming agents can reference chunks without fragile
doc_title string matching. The UUID already exists in every pgvector
table (`id UUID PRIMARY KEY`); it just needs to surface through the
adapter, schemas, and MCP tool responses.

1. **Expose `chunk_id` in retrieve hits**
   The `RetrievalHit` schema in `retrieval-hub-mcp/src/retrieval_hub_mcp/schemas.py`
   gets a new `chunk_id: str` field. The adapter's `_similarity_search()`
   in `src/retrieval_hub/adapters/document.py` already SELECTs `id` from
   the pgvector table — thread it through to the response. The MCP
   `retrieve` tool returns it alongside `doc_title` and `chunk_index`.

2. **Accept `chunk_id` in refine**
   The `refine` tool should accept an optional `chunk_id` parameter as
   an alternative to `doc_title` + `chunk_index`. When `chunk_id` is
   provided, look up the chunk directly by UUID instead of title + index.
   Keep `doc_title` + `chunk_index` working for backward compatibility.

3. **Expose `chunk_id` on refine response chunks**
   Each chunk in the `RefineResponse.chunks` list should include its
   `chunk_id` so agents can chain refine calls without reverting to
   title-based lookup.

4. **Normalize doc_title during ingestion**
   While we're touching the identifier path, audit and normalize
   doc_title values at ingestion time. The VA CPG has inconsistent
   titles (e.g., "for the treatment of nightmares associated with PTSD"
   is a fragment, not the full guideline title). Add a title-normalization
   step in the ingestion pipeline or document why we don't.

5. **Tests**
   Update existing retrieve/refine tests to verify `chunk_id` appears
   in responses and that refine-by-chunk_id works.

**Sequencing.** Steps 1-3 together (the core plumbing), then step 4
(ingestion normalization — may be deferred if it's a larger scope change),
then step 5 (tests throughout, but a final pass at the end).

**Session start protocol:**
- Premise checks:
  - `git pull` and confirm clean merge.
  - `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` — green
    baseline (should be 245 + 41).
  - Local databases up: `pg_isready -h localhost -p 5433` (vectors)
    and `pg_isready -h localhost -p 5434` (catalog).
  - Confirm the UUID column exists on all pgvector tables:
    `psql ... -c "\d idx_va_cpg_v1" | grep "^  id"`
- Rules with history:
  - Embedding model comes from the recipe version — use
    `_embedding_model_name()` and `_query_prefix()`, never hardcode.
  - Raw psycopg SQL in the adapter, not SQLAlchemy Core.
  - Container deps must be explicit in `requirements-deploy.txt` —
    local venv masks transitive deps (see CLAUDE.md lessons learned).
- Stop-and-ask before: Any changes to existing pgvector table DDL
  (column adds/renames). The UUID column already exists; this session
  should only need to SELECT it, not ALTER TABLE.
- Close ritual: session summary, commit, update this file.

## What landed last session (2026-08-20, seventh session)

Tale of Two Cities ingestion + entity-arc validation + deployment fixes.
See `session-summaries/2026-08-20-refine-tool-tale-ingestion.md`.

- `50ef540` — Ingestion script + semantic context seeder (376 chunks,
  Nomic v1.5, 9 characters with aliases, entity_arc/section/cross_reference
  strategies enabled)
- `ae22366` — Fix deployed MCP server: route trailing slash → 503,
  missing einops, OOMKill at 2Gi → 4Gi
- `12e6805` — CLAUDE.md with deployment lessons learned

Entity-arc validated locally against three queries (Carton arc, Evrémonde
alias resolution, Doctor Manette arc). All returned coherent
narrative-ordered chunks.

## What landed earlier (2026-08-20, sessions 1-6)

- Phase 1: refine MCP tool with adjacent-chunk retrieval (`c1c495d`)
- Phase 2: section-aware expansion with token budgeting (`ea5fa67`)
- Phase 3: cross-reference following (`0bda717`)
- Phase 4 research: entity-arc feasibility study (`8c033bd`)
- Phase 4 impl: entity-arc refinement strategy (`29503b5`)
- Tool ergonomics: embedding_model transparency (`c3eb259`), describe_source cleanup (`2026fe0`)

## Remaining epic phases

### Phase 5: A/B eval (refine lift measurement)

The epic's gate: does refine actually improve answer quality?

**Dependencies:** Eval-convergence epic chunk-sweep results (in
progress). Refine-tool Phases 1-4 all done.

**Status:** Blocked. Phase 5 unblocks once the eval pipeline has
baseline metrics to compare refine-augmented retrieval against.

### Aircraft maintenance data source ingestion

Import aircraft maintenance data sources. Sequenced after #33
(stable chunk identifiers) so the new sources benefit from chunk_id
from day one.

### #34 Multi-source retrieve

Search across sources in one call. Sequenced after the aircraft
maintenance ingestion — urgency increases with source count.

## Tool ergonomics backlog (from exercise-tools pass)

- ~~#32 Score calibration~~ — Closed (`c3eb259`).
- **#33** Stable chunk identifiers — **next session focus**.
- **#34** Multi-source retrieve — after aircraft data ingestion.
- ~~#35 describe_source recipe_content~~ — Closed (`2026fe0`).

## Watch out for

- **chunk_id is a UUID string, not an int.** The pgvector `id` column
  is `UUID`. Surface it as a string in the schema, not as a typed UUID
  (MCP tools serialize as JSON; string is the safest representation).
- **Backward compatibility.** Agents already using `doc_title` +
  `chunk_index` must keep working. `chunk_id` is additive, not a
  replacement. The refine tool should accept either.
- **Sub-agent drift.** Sub-agents introduced unrelated file changes
  in earlier sessions. Verify `git diff --stat HEAD` after delegated
  work.

## If blocked

- If local databases can't start, the schema and adapter changes
  (steps 1-3) can still be written and tested with mocked data.
- If doc_title normalization (step 4) turns out to be a larger scope
  change than expected, defer it to a follow-up and ship steps 1-3 + 5.
