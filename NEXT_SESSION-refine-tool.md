# Next Session — refine-tool

## Next: Cross-reference following (Phase 3)

The VA CPG guidelines cross-reference each other (PTSD -> SUD, Diabetes ->
CKD). The semantic layer captures these as `RelationshipHint` entries. This
phase uses them to let the agent follow cross-document references via refine.

1. **Cross-document retrieval in the adapter**
   When the agent says "tell me about the related guidelines" or similar,
   look up the current document's entity in
   `semantic_context.relationships` and retrieve from the referenced
   sources/documents. Implement as a new strategy kind (`"cross_reference"`)
   or a separate refine call that accepts a relationship type.

2. **Provenance chain support**
   The refined result must carry both the original retrieval provenance and
   the cross-reference hop. The current `RefineResponse` has `source` and
   `doc_title` on the envelope — cross-references may return chunks from a
   different source/document, so the response shape may need adjustment.

3. **Test with VA CPG corpus**
   The PTSD CPG mentions substance use; refine should fetch the relevant
   section from the SUD CPG. Requires the relationship graph in
   `semantic_context` to be populated for both sources.

**Prerequisites:**
- Confirm that `RelationshipHint` entries exist in the VA CPG source's
  `semantic_context`. If not, populate them before implementing.
- Phase 3 depends on Phase 2 (section expansion is the building block for
  fetching sections from referenced documents).

**Session start protocol:**
- Premise checks:
  - `git pull` and confirm clean merge.
  - Run `pytest tests/ && cd retrieval-hub-mcp && pytest tests/` to
    confirm green baseline (should be 205 + 29).
  - Check `semantic_context.relationships` for the VA CPG source:
    query the catalog DB for the source's `semantic_context` JSON.
- Rules with history:
  - Raw psycopg SQL in the adapter, not SQLAlchemy Core.
  - Doc-level fields on the response envelope, actionable ToolError on
    empty results.
  - `RefineOutput` wrapper carries truncation metadata from the adapter.
  - `_resolve_refine_strategy` in the MCP server resolves strategy from
    source config with family defaults.
- Stop-and-ask before: Any changes to the pgvector table DDL, the
  ingestion write path, or the `RefineResponse` envelope shape (since
  cross-references may need a different document context).

## What landed last session (2026-08-20, second session)

Phase 2 complete: section-aware expansion with token budgeting.
See `session-summaries/2026-08-20-refine-tool-phase2.md` for detail.

**Commit:** ea5fa67

Key decisions:
- `RefineOutput` dataclass wraps results with truncation metadata, avoiding
  a double database query to detect truncation.
- `_resolve_refine_strategy` reads `semantic_context.refinement_strategies`,
  falls back to family defaults (section for document/clinical_document,
  adjacent for code). Source-configured `window` and `max_context_tokens`
  are defaults that tool-level parameters override.
- Applied `semantic_context` Alembic migration to deployed catalog DB.

## What landed earlier (2026-08-20, first session)

Phase 1 complete: refine MCP tool with adjacent-chunk retrieval, plus
exercise-tools pass improving ergonomics across all four tools.
See `session-summaries/2026-08-20-refine-tool-phase1.md` for detail.

**Commits:** c1c495d..a7e2216

**Parallel session:** eval-convergence filed #28-31 (entity-arc, elicitation,
auth, MCP-level eval). #28 maps to Phase 4 of this epic.

## Remaining epic phases

### Phase 3: Cross-reference following

The VA CPG guidelines heavily cross-reference each other (PTSD -> SUD,
Diabetes -> CKD). The semantic layer already captures these as
`RelationshipHint` entries. This phase uses them.

**Work:**
1. When the agent says "tell me about the related guidelines" or similar,
   look up the current document's entity in `semantic_context.relationships`
   and retrieve from the referenced sources/documents.
2. Implement cross-document refinement: given a chunk from the PTSD CPG
   that mentions substance use, fetch the relevant section from the SUD
   CPG.
3. Add provenance chain support: the refined result carries both the
   original retrieval provenance and the cross-reference hop.

**Definition of done:** An agent can retrieve a PTSD chunk, then refine
to get the referenced SUD guideline section. Provenance chain shows both
hops.

**Dependencies:** Phase 2 (done). Also depends on the relationship graph in
`semantic_context` being populated (already done for VA CPG).

### Phase 4: Entity-arc retrieval (research phase)

The hardest refinement problem: tracing an entity's arc across a document
or corpus. This is a research phase -- the outcome may be a working
implementation, a design document, or a documented finding.

**Dependencies:** Phase 2 (done). Independent of Phase 3.

**Parallel-ok:** Yes -- can run concurrently with Phase 3.

### Phase 5: A/B eval (refine lift measurement)

The epic's gate: does refine actually improve answer quality?

**Dependencies:** Eval-convergence epic Phase 1 (need the answer-quality
eval pipeline). Refine-tool Phase 2 at minimum (done).

---

## If blocked

- If the relationship graph isn't populated for multiple VA CPG sources,
  populate it manually for PTSD + SUD as a test fixture before implementing
  cross-reference following.
- If entity-arc retrieval (Phase 4) proves intractable, document the
  findings and move on. The first three phases deliver concrete value.
