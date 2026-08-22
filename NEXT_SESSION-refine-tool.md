# Next Session — refine-tool

## Next: #34 Multi-source retrieve

Search across sources in one call. The 4 existing sources are enough
to build and test it. Phase 5 is done — refine does not improve
automated answer quality (see session summary below).

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
