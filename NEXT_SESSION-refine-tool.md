# Next Session — refine-tool

## Next: Phase 5 — A/B eval (does refine improve answer quality?)

The epic's gate. Eval-convergence Phase 3 is done and baseline metrics
are available. Extend the eval pipeline to compare retrieve-only vs
retrieve+refine, then measure the lift.

1. **Extend `eval_answer_quality.py` with a refine stage**
   The eval pipeline is retrieve → generate → score. Add an optional
   refine step between retrieve and generate that calls the refine API
   (adjacent or section strategy) to expand context around the top
   retrieve hits before generation. The script should support a flag
   like `--refine-strategy adjacent` to enable it, defaulting to no
   refine (the current behavior, which is the baseline).

   Key files:
   - `scripts/eval_answer_quality.py` — the eval pipeline
   - `src/retrieval_hub/retrieval/api.py` — `query()` function used
     by the eval script for retrieval
   - `src/retrieval_hub/retrieval/refine.py` — the refine
     implementation (adjacent, section, cross_reference, entity_arc)
   - `eval/autorag/qa_dataset_draft.json` — the 30-query Q/A set

2. **Run the eval with refine enabled**
   Run with `--refine-strategy adjacent` and `--refine-strategy section`
   against the same 30-query Q/A set. Use the same LLM endpoint
   (gpt-oss-120b) for generation and scoring.

3. **Compare against baseline**
   Baseline metrics (from eval-convergence Phase 3, 512/0 Nomic v1.5):
   - context_precision: 0.815
   - answer_relevancy: 0.735
   - faithfulness: 0.854

   Use the `/eval-report` skill to generate a Pareto front comparison.
   The question is whether refine improves answer_relevancy and/or
   faithfulness without degrading context_precision.

4. **Record results in the eval register**
   Import results using the eval register import pattern from
   eval-convergence (see `scripts/import_nomic_sweep_results.py`).

**Sequencing.** Step 1 first (implementation), then steps 2-4 together
(run + compare + record).

**Session start protocol:**
- Premise checks (~5 min):
  - `git pull` and confirm clean merge
  - `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` — green
    baseline (should be 260 + 43)
  - Local databases up: `pg_isready -h 127.0.0.1 -p 5433` (vectors)
    and `pg_isready -h 127.0.0.1 -p 5434` (catalog)
  - Verify baseline exists: check that `eval/rewrite_lift/runs/` has
    the 512/0 baseline run with `summary.json`
  - gpt-oss-120b reachable for LLM generation/scoring
- Rules with history:
  - gpt-oss-120b reasoning off via `enable_thinking=False` in
    `extra_body` (from eval-convergence sessions)
  - Ragas max_tokens=8192 to avoid faithfulness NaN
  - Per-condition checkpointing in scoring stage
  - Use 127.0.0.1 not localhost for Postgres connections
  - Nomic requires `search_query: ` / `search_document: ` prefixes
- Stop-and-ask before: modifying the eval register (append only);
  dropping or re-ingesting any index tables
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

- **gpt-oss-120b sandbox may be reprovisioned.** If the endpoint
  changes, update the eval scripts. Also: reasoning off via
  `enable_thinking=False`, max_tokens=8192 for faithfulness scoring.
- **Refine window size affects token budget.** Adjacent with window=2
  returns 5 chunks (origin + 2 before + 2 after). Section strategy
  can return much more. The generation prompt may need truncation or
  the eval script may need a token budget parameter.
- **Parallel sessions.** The data-products and eval-convergence epics
  may be running concurrently. Don't touch their pgvector tables or
  eval runs.

## If blocked

- **gpt-oss-120b unavailable:** The eval pipeline needs an LLM for
  generation and scoring. If the endpoint is down, defer to next
  session — the implementation work (step 1) can still be done and
  tested locally with mock responses.
- **Refine shows no lift:** That's a valid result. Document it, close
  Phase 5, and move to #34. The refine tool still has value for
  human-in-the-loop exploration even if it doesn't improve automated
  answer quality.
- **If Phase 5 finishes quickly:** Pull #34 (multi-source retrieve)
  forward — the 4 existing sources are enough to build and test it.
