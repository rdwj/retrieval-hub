# Next Session — refine-tool

## Next: Entity-arc retrieval (Phase 4, implementation)

Research complete — entity-arc retrieval is feasible. Design is in
`docs/entity-arc-retrieval-research.md`. This session implements the
`entity_arc` refine strategy.

**Implementation tasks:**

1. **New SQL helper: `_keyword_search_with_scores`**
   In `src/retrieval_hub/adapters/document.py`. Runs
   `WHERE doc_title = %s AND chunk_text ILIKE %s` but also computes
   cosine similarity against a query vector for ranking. Returns the
   same row shape as `_filtered_similarity_search`.

2. **New adapter method: `_entity_arc_refine`**
   Hybrid vector+keyword search within one document:
   - Embed query, filtered ANN search (`top_k=window`)
   - Keyword search for entity name (and aliases from SemanticContext)
   - Union by chunk_index, keeping higher score for duplicates
   - Apply score floor (default 0.30) to remove noise
   - Sort by chunk_index for structural ordering
   - Token budgeting: select by score, re-sort by position
   - Return `RefineOutput`

3. **Register `entity_arc` strategy**
   - Add `"entity_arc"` case in `DocumentAdapter.refine` dispatch
   - Add to `_FAMILY_DEFAULT_STRATEGY` comments (not as default)
   - Add to `_resolve_refine_strategy` documentation
   - Update MCP tool docstring for the strategy parameter

4. **Optional: `min_score` on RefinementStrategy**
   New optional field. Default null. Only meaningful for entity_arc.
   Filters keyword-only matches with low vector relevance.

5. **Tests**
   - Unit tests for `_keyword_search_with_scores` (mock pgvector)
   - Unit tests for `_entity_arc_refine` (mock SQL helpers)
   - Integration test if cluster is available

6. **Verify end-to-end against cluster**
   Query: "SSRIs" against PTSD CPG with `strategy="entity_arc"`.
   Confirm arc order, token truncation, score filtering.

**Session start protocol:**
- Premise checks:
  - `git pull` and confirm clean merge.
  - Run `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` to
    confirm green baseline (should be 212 + 33).
  - Port-forward cluster PG: `scripts/port_forward_cluster_pg.sh`
- Rules with history:
  - Raw psycopg SQL in the adapter, not SQLAlchemy Core.
  - `RefineOutput` wrapper carries truncation metadata from the adapter.
  - `_resolve_refine_strategy` in the MCP server resolves strategy from
    source config with family defaults; tool-level params override.
  - **Embedding model comes from the recipe version** — use
    `_embedding_model_name()` and `_query_prefix()`, never hardcode.
    VA CPG uses PubMedBERT (no prefix), code source uses Nomic v1.5.
- Stop-and-ask before: Any changes to the pgvector table DDL or the
  ingestion write path. Any new fields on `RefineResponse` envelope.

## What landed last session (2026-08-20, fourth session)

Phase 4 research complete: entity-arc retrieval is feasible.
See `session-summaries/2026-08-20-refine-tool-phase4-research.md` and
`docs/entity-arc-retrieval-research.md` for detail.

Key findings:
- PubMedBERT entity-scoped search produces 0.39-0.56 scores (usable)
- Hybrid vector+keyword needed for full recall (7 of 15 keyword
  matches missed by vector top-20)
- doc_section ordering unreliable (13/19 sections fragmented);
  chunk_index is the only valid structural signal
- Token budget (4,000 tokens) fits ~7 of 27 arc chunks; score-weighted
  sampling preserves the most relevant segments

**Commit:** (research docs, no code changes)

## What landed earlier (2026-08-20, third session)

Phase 3 complete: cross-reference following with entity relationship
traversal across VA CPG documents.
See `session-summaries/2026-08-20-refine-tool-phase3.md` for detail.

**Commit:** 0bda717

Key decisions:
- `EntityDefinition.doc_titles` maps entities to their CPG document
  titles. 10 condition entities populated.
- `cross_reference` strategy: entity graph walk via
  `_resolve_cross_reference_targets`, filtered ANN search via
  `_filtered_similarity_search`, score-based token truncation.
- `strategy` parameter added to MCP refine tool — agent explicitly
  selects strategy, overriding source defaults.
- Per-hit `doc_title`/`doc_url` on `RefineHit` for cross-document
  results (null for same-document strategies).
- Verified end-to-end: PTSD <-> SUD cross-references work both
  directions against cluster DB.

Noted: phantom entities in relationship graph (CKD, Stroke,
Benzodiazepines referenced but not in ENTITIES list) — expand later.

## What landed earlier (2026-08-20, second session)

Phase 2 complete: section-aware expansion with token budgeting.
See `session-summaries/2026-08-20-refine-tool-phase2.md` for detail.

**Commit:** ea5fa67

## What landed earlier (2026-08-20, first session)

Phase 1 complete: refine MCP tool with adjacent-chunk retrieval, plus
exercise-tools pass improving ergonomics across all four tools.
See `session-summaries/2026-08-20-refine-tool-phase1.md` for detail.

**Commits:** c1c495d..a7e2216

**Parallel session:** eval-convergence filed #28-31 (entity-arc, elicitation,
auth, MCP-level eval). #28 maps to Phase 4 of this epic.

## Remaining epic phases

### Phase 4: Entity-arc retrieval ← NEXT (implementation)

Research complete. Hybrid vector+keyword approach within a document,
ordered by chunk_index, with score-based token truncation. Design in
`docs/entity-arc-retrieval-research.md`. Implementation session needed.

**Dependencies:** Phase 2 (done). Independent of Phase 3.

### Phase 5: A/B eval (refine lift measurement)

The epic's gate: does refine actually improve answer quality?

**Dependencies:** Eval-convergence epic Phase 1 (need the answer-quality
eval pipeline). Refine-tool Phase 2 at minimum (done).

## Tool ergonomics backlog (from exercise-tools pass)

Issues filed during the Phase 2 exercise-tools session. These are not
gating for the remaining epic phases but should be addressed before adding
more sources.

- **#32** Score calibration — add a relevance indicator so agents can
  interpret raw cosine scores. Becomes critical with multiple embedding
  models.
- **#33** Stable chunk identifiers — add chunk_id alongside doc_title to
  make refine calls less fragile.
- **#34** Multi-source retrieve — search across sources in one call.
  Low urgency at 2 sources, needed at 5+.
- **#35** describe_source recipe_content — omit implementation detail
  from agent-facing responses.

Data quality guidance for doc_title consistency and doc_section granularity
is documented in `docs/onboarding-journey-va-cpg.md` (section 4a). A
future data-owner usability epic should address:
- Tooling to validate doc_title consistency post-ingestion
- Configurable doc_section splitting in the normalization stage
- Score distribution profiling per source for relevance threshold config

---

## Watch out for

- **Embedding model mismatch:** VA CPG data uses `NeuML/pubmedbert-base-embeddings`
  (no prefix). Code source uses `nomic-ai/nomic-embed-text-v1.5` (with
  `search_query:` prefix). Always read the model from the recipe version
  via `_embedding_model_name()` and `_query_prefix()`. Using the wrong
  model produces near-zero similarity scores that look like "search is
  broken" but are actually a model mismatch.
- The PTSD CPG doc_title is `"for the treatment of nightmares associated
  with PTSD"` — poorly extracted. Entity-arc queries against this document
  will need the exact title string.
- **doc_section is not orderable.** 13/19 multi-chunk sections are
  fragmented (non-contiguous chunk ranges). Use chunk_index for ordering.
- Phantom entities (CKD, Stroke, Benzodiazepines) in the relationship
  graph have no EntityDefinition — entity-arc queries for these will
  silently return nothing. Not blocking but worth noting.

## If blocked

- If entity-arc retrieval proves intractable quickly, pivot to the
  ergonomics backlog (#32-35). Those are self-contained, well-scoped
  enhancements that deliver concrete value.
- If the cluster DB is inaccessible, the research exploration can still
  be designed and prototyped against unit-test fixtures with synthetic
  data, then verified against the cluster later.
