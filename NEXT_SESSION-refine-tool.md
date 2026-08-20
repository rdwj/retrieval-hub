# Next Session — refine-tool

## Next: Tool ergonomics (#32 + #35)

The refine-tool epic is paused at Phase 5 (A/B eval), which is gated
on the eval-convergence epic's chunk-sweep results. While that runs,
the next refine-tool session addresses the ergonomics backlog — read-
path-only changes that improve agent experience without touching
ingestion or DDL.

1. **#32 — Score calibration: add relevance indicator**
   Raw cosine scores differ by embedding model (PubMedBERT 0.35-0.55,
   Nomic 0.6-0.85). Agents can't interpret these without context. Add
   a relevance tier or normalized indicator to retrieve/refine hits so
   agents know whether a 0.42 is strong or weak for a given source.
   Approach: per-source score distribution metadata on the physical
   index (computed at ingest time or lazily), mapped to a tier label
   (high/medium/low) at query time. Implementation in
   `DocumentAdapter` + `RetrievalResult` + MCP response schemas.

2. **#35 — describe_source: omit recipe_content**
   The `describe_source` tool returns the full recipe body including
   embedding model config, chunking params, and github_repo. Agents
   don't need implementation detail. Filter to agent-useful fields
   only (description, sample prompts, document/chunk counts).
   Small change in `retrieval-hub-mcp/src/retrieval_hub_mcp/server.py`.

**Sequencing.** #35 is independent and small — do it first as a warmup.
#32 is the main session focus and may need design work on the score
distribution metadata format before implementation.

**Session start protocol:**
- Premise checks:
  - `git pull` and confirm clean merge.
  - Run `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` to
    confirm green baseline (should be 245 + 38).
  - Deploy to cluster and exercise both retrieve and refine with
    `mcp-test-mcp` to confirm entity_arc is working in production.
- Rules with history:
  - Raw psycopg SQL in the adapter, not SQLAlchemy Core.
  - **Embedding model comes from the recipe version** — use
    `_embedding_model_name()` and `_query_prefix()`, never hardcode.
  - Score calibration must work across all three sources (VA CPG with
    PubMedBERT, code with Nomic v1.5, PubMed hypertension with
    PubMedBERT). Different models produce different score distributions.
- Stop-and-ask before: Any changes to the pgvector table DDL or the
  ingestion write path. Any new fields that would require re-ingestion
  of existing sources.

## What landed last session (2026-08-20, fifth session)

Phase 4 implementation complete: entity-arc refinement strategy.
See `session-summaries/2026-08-20-refine-tool-phase4-impl.md`.

- `29503b5` — hybrid vector+keyword entity-arc search with ILIKE
  wildcard escaping, alias resolution, score floor (0.30), chunk_index
  ordering, score-based token budgeting. `min_score` on
  `RefinementStrategy`. MCP wiring with `origin_chunk_index=-1`.
- Deployed and exercised E2E: SSRIs arc (7/23 chunks in 4K budget),
  prazosin arc (3 chunks, no truncation).
- 15 new tests across 3 files (245 + 38 total).
- Closed #28.

**Commit:** 29503b5

## What landed earlier (2026-08-20, sessions 1-4)

- Phase 1: refine MCP tool with adjacent-chunk retrieval (`c1c495d`)
- Phase 2: section-aware expansion with token budgeting (`ea5fa67`)
- Phase 3: cross-reference following (`0bda717`)
- Phase 4 research: entity-arc feasibility study (`8c033bd`)

See session summaries in `session-summaries/2026-08-20-refine-tool-*.md`.

## Remaining epic phases

### Phase 5: A/B eval (refine lift measurement)

The epic's gate: does refine actually improve answer quality?

**Dependencies:** Eval-convergence epic chunk-sweep results (in
progress — next eval-convergence session runs VA CPG + PubMed
sweeps). Refine-tool Phases 1-4 all done.

**Status:** Blocked. Eval-convergence is the higher-priority epic for
the next session slot. Phase 5 unblocks once the eval pipeline has
baseline metrics to compare refine-augmented retrieval against.

## Tool ergonomics backlog (from exercise-tools pass)

- **#32** Score calibration — add a relevance indicator so agents can
  interpret raw cosine scores. Becomes critical with multiple embedding
  models. **← NEXT**
- **#33** Stable chunk identifiers — add chunk_id alongside doc_title to
  make refine calls less fragile. Touches ingestion write path — needs
  design work.
- **#34** Multi-source retrieve — search across sources in one call.
  Low urgency at 3 sources, needed at 5+.
- **#35** describe_source recipe_content — omit implementation detail
  from agent-facing responses. **← NEXT**

## Watch out for

- **Embedding model mismatch:** VA CPG data uses `NeuML/pubmedbert-base-embeddings`
  (no prefix). Code source uses `nomic-ai/nomic-embed-text-v1.5` (with
  `search_query:` prefix). PubMed hypertension uses PubMedBERT. Always
  read the model from the recipe version via `_embedding_model_name()`
  and `_query_prefix()`.
- **OpenShift route 307 redirect:** FastMCP redirects `/mcp/` to `/mcp`
  with `http://` scheme, but the edge-terminated route requires HTTPS.
  Port-forward works; direct HTTPS hits 503 after redirect. Pre-existing
  issue, not blocking but worth fixing if touching deploy.
- **Sub-agent drift:** Sub-agents introduced unrelated file changes
  twice during Phase 4 implementation (enums.py, chunking/__init__.py).
  Verify `git diff --stat HEAD` after delegated work to catch stray edits.

## If blocked

- If score calibration design is unclear, pivot to #33 (stable chunk
  identifiers) — that has a clearer implementation path even though it
  touches ingestion.
- If the cluster is inaccessible, #35 (describe_source cleanup) and
  the design work for #32 can proceed without it.
