# Next Session — refine-tool

## Next: Entity-arc retrieval (Phase 4, research)

Investigate whether the current architecture can support entity-arc
retrieval — tracing an entity's mentions across a document in
narrative/structural order. This is a research phase: the outcome may be
a working prototype, a design document, or a documented finding that the
problem needs capabilities beyond what exists.

1. **#28 — Entity-arc retrieval for temporal/narrative traversal**
   The core question: given an entity (e.g., "SSRIs" in the PTSD CPG),
   can we retrieve all mentions across sections in document order and
   return a coherent arc (screening -> treatment selection -> dosing ->
   maintenance -> relapse)? The PTSD CPG has SSRIs mentioned across 13
   sections — a concrete test case. The Phase 3 infrastructure
   (`_resolve_cross_reference_targets`, `_filtered_similarity_search`,
   entity graph walk) provides building blocks.

   **Research questions to answer:**
   - Does entity-scoped filtered search (embed entity name, filter to
     one document, order by chunk_index) produce a usable arc? Or does
     vector similarity cluster too tightly around one meaning?
   - Is `doc_section` ordering sufficient for structural position, or do
     we need explicit section-order metadata?
   - How should the response shape differ from cross-reference? An arc
     is ordered and spans many sections; cross-reference is unordered
     and spans documents.
   - What's the token budget story? An entity arc across 13 sections
     could be huge — need a summarization or sampling strategy.

   **Approach:** Start with empirical exploration against the cluster DB
   (query SSRIs, sertraline, CPT across the PTSD CPG; trace the
   treatment pathway). Evaluate whether a simple "embed entity + filter
   to document + order by chunk_index" strategy produces coherent arcs.
   If it does, prototype a `entity_arc` refine strategy. If it doesn't,
   document why and what would be needed (co-reference resolution,
   process metadata, etc.).

**Session start protocol:**
- Premise checks:
  - `git pull` and confirm clean merge.
  - Run `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` to
    confirm green baseline (should be 212 + 33).
  - Port-forward cluster PG: `scripts/port_forward_cluster_pg.sh`
  - Verify semantic_context is populated (Phase 3 seeded entities with
    doc_titles and relationships).
- Rules with history:
  - Raw psycopg SQL in the adapter, not SQLAlchemy Core.
  - `RefineOutput` wrapper carries truncation metadata from the adapter.
  - `_resolve_refine_strategy` in the MCP server resolves strategy from
    source config with family defaults; tool-level params override.
  - This is a research phase — document findings even if the outcome is
    "this approach doesn't work." A design document is a valid
    deliverable.
- Stop-and-ask before: Any changes to the pgvector table DDL or the
  ingestion write path. Any new fields on `RefineResponse` envelope
  (cross-reference set precedent for per-hit fields; entity-arc may
  need a different shape).

## What landed last session (2026-08-20, third session)

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

### Phase 4: Entity-arc retrieval (research phase) ← NEXT

The hardest refinement problem: tracing an entity's arc across a document
or corpus. This is a research phase -- the outcome may be a working
implementation, a design document, or a documented finding.

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

- The PTSD CPG doc_title is `"for the treatment of nightmares associated
  with PTSD"` — poorly extracted. Entity-arc queries against this document
  will need the exact title string.
- Entity-arc retrieval may surface that `doc_section` ordering doesn't
  match narrative order (sections are alphabetically or arbitrarily named,
  not sequentially numbered). If so, chunk_index ordering within a
  document may be the only reliable structural signal.
- Phantom entities (CKD, Stroke, Benzodiazepines) in the relationship
  graph have no EntityDefinition — entity-arc queries for these will
  silently return nothing. Not blocking for research but worth noting.

## If blocked

- If entity-arc retrieval proves intractable quickly, pivot to the
  ergonomics backlog (#32-35). Those are self-contained, well-scoped
  enhancements that deliver concrete value.
- If the cluster DB is inaccessible, the research exploration can still
  be designed and prototyped against unit-test fixtures with synthetic
  data, then verified against the cluster later.
