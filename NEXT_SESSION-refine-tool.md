# Next Session — refine-tool

## Next: to be planned via /plan-next-session

(No next-session focus selected yet. Run `/plan-next-session refine-tool`
to pick the first slice from the phases below.)

## Remaining epic phases

Implement the `refine` MCP tool: given a reference handle from a previous
retrieval result plus a natural language description of what more the agent
wants, return additional context using source-specific refinement logic.
The goal is "100% of what the agent needs to answer the question, 0% of
what it doesn't" -- refine bridges the gap between a single chunk hit and
a complete answer.

The definition of done for this epic is an A/B test showing that retrieval
with refine produces measurably better answer quality than retrieval alone,
measured by the eval infrastructure from the eval-convergence epic.

Refinement strategies are per-dataset, configured by data owners as part of
the source's semantic layer. The platform provides sensible defaults per
source family; data owners customize from there.

### Phase 1: Adjacent chunk retrieval (baseline refine)

The simplest refinement: given a chunk, fetch the chunks immediately before
and after it in the same document. This works because `chunk_index` already
exists in the pgvector table.

**Work:**
1. Add the `refine` MCP tool to the server with a `reference_handle`
   parameter (the `request_id` + chunk identifier from a previous retrieve
   result) and a `query` parameter (what more the agent wants).
2. Implement `DocumentAdapter.refine()` with the default strategy: fetch
   N adjacent chunks (configurable, default 2 before + 2 after) from the
   same document, filtered by `doc_title` and ordered by `chunk_index`.
3. Return refined context with provenance (original chunk reference +
   refinement path, per the design doc's provenance chain spec).
4. Add a `refinement_strategies` field to `SemanticContext` so data owners
   can configure refinement behavior per source.

**Definition of done:** An agent can call `retrieve` and then `refine` on a
result to get surrounding context. Works on both VA CPG and code sources.

**Dependencies:** None (can start without the eval-convergence epic).

**Parallel-ok:** Yes -- fully independent of eval-convergence. The eval
infrastructure is needed for the final A/B test (Phase 5) but not for
building refine.

### Phase 2: Section-aware expansion

Adjacent chunks are a blunt instrument. A better default for document
sources is "expand to the full section this chunk belongs to." The
`doc_section` column in pgvector already tracks which section each chunk
came from.

**Work:**
1. Implement section-scoped retrieval: given a chunk, fetch all chunks
   from the same `doc_section` in the same document.
2. Add a token budget parameter (`max_context_tokens`) so the refine tool
   doesn't overwhelm a small-context-window agent. Truncate from the
   edges of the section toward the original chunk if the section exceeds
   the budget.
3. Make the default refinement strategy configurable per source: adjacent
   chunks vs. section expansion, with section expansion as the default for
   document/clinical_document families.

**Definition of done:** Refine returns the full section containing the
hit chunk, respecting a token budget. VA CPG "recommendation" sections
return complete recommendation text, not fragments.

**Dependencies:** Phase 1.

**Parallel-ok:** No -- sequential after Phase 1.

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

**Dependencies:** Phase 2. Also depends on the relationship graph in
`semantic_context` being populated (already done for VA CPG).

**Parallel-ok:** No -- sequential after Phase 2.

### Phase 4: Entity-arc retrieval (research phase)

The hardest refinement problem: tracing an entity's arc across a document
or corpus. "What eventually happened to Madame Defarge?" requires finding
all mentions of an entity and presenting them in narrative/temporal order,
not just the closest vector match. This is relevant for CPGs (a patient's
treatment pathway across modules), business processes (a strategy's
evolution), and episodic content (character arcs).

This is a research phase -- the outcome may be a working implementation,
a design document describing the approach, or a documented finding that
the problem requires capabilities beyond what the current architecture
supports.

**Work:**
1. Research approaches: entity-scoped retrieval with temporal ordering,
   entity co-reference resolution across chunks, knowledge-graph-backed
   entity timelines.
2. Prototype on the VA CPG corpus: given "trace the treatment pathway for
   a patient with PTSD and comorbid SUD," retrieve the relevant sections
   from both CPGs in clinical workflow order (screening -> diagnosis ->
   treatment -> maintenance -> relapse).
3. Evaluate whether the semantic layer's entity definitions and
   relationships are sufficient for this, or whether additional metadata
   (temporal markers, process-step ordering) is needed.
4. If a working approach emerges, implement it as a refinement strategy.
   If not, document the gap and what would be needed.

**Definition of done:** Either a working entity-arc refinement strategy, or
a published design document describing the problem, attempted approaches,
and what's missing. This is one of the project's potential arXiv
contributions.

**Dependencies:** Phase 2 (needs section-aware expansion as a building
block). Independent of Phase 3.

**Parallel-ok:** Yes -- can run concurrently with Phase 3.

### Phase 5: A/B eval (refine lift measurement)

The epic's gate: does refine actually improve answer quality? Use the eval
infrastructure from the eval-convergence epic to measure.

**Work:**
1. Extend the eval pipeline to include a refine step: for each query, run
   retrieve-only and retrieve-then-refine, generate answers from both,
   score with Ragas answer_relevancy and faithfulness.
2. Run the A/B eval on the VA CPG source with the best retrieval config
   from the eval-convergence epic.
3. Analyze: which refinement strategy helps most? Which query types
   benefit? Does refine ever hurt (by adding noise)?
4. Record results in the eval register.

**Definition of done:** Measurable improvement in answer quality (Ragas
answer_relevancy or faithfulness) when refine is used, on at least 60% of
queries where the raw retrieval result was incomplete. Results in the eval
register.

**Dependencies:** Eval-convergence epic Phase 1 (need the answer-quality
eval pipeline). Refine-tool Phase 2 at minimum.

**Parallel-ok:** No -- this is the convergence point between both epics.

---

## What this covers (and what it doesn't)

**In scope:**
- `refine` MCP tool implementation
- Adjacent chunk retrieval (baseline)
- Section-aware expansion with token budgeting
- Cross-reference following using semantic layer relationships
- Entity-arc retrieval (research)
- Per-source refinement strategy configuration
- A/B eval against retrieve-only baseline

**Out of scope (other epics own):**
- Eval infrastructure and EvalHub packaging (`NEXT_SESSION-eval-convergence.md`)
- Fine-tuning / model training (future work -- the "Tale of Two Cities"
  scenario where the model should just know the content)
- Graph adapter and knowledge-graph traversal (future family)
- Tabular adapter and join-following (future family)

## Watch out for

- Context window constraints. A 32K-context agent can't absorb a full CPG
  section (some are 50+ chunks). The `max_context_tokens` parameter is
  load-bearing -- if we get it wrong, refine hurts more than it helps.
- The temporal/entity-arc problem (Phase 4) may not have a clean solution
  within the current architecture. That's fine -- documenting the gap is a
  valid outcome and a potential paper contribution.
- Cross-reference following (Phase 3) depends on the semantic layer's
  relationship graph being accurate. For VA CPG it's manually curated;
  for other sources it may need automated extraction.

## If blocked

- If the eval-convergence epic isn't ready for Phase 5, run a lightweight
  eval using the existing retrieval-metrics approach (does refine change
  hit_rate/MRR?) as a proxy.
- If entity-arc retrieval (Phase 4) proves intractable, document the
  findings and move on. The first three phases deliver concrete value
  independent of Phase 4.
