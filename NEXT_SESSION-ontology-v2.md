# Next Session -- Ontology v2

## Epic: Ontology self-improvement and concept-first retrieval

Build on the ontology registry (shipped in the ontology v1 epic) with
eval-driven self-improvement, query success monitoring, concept-first
retrieval, an onboarding pipeline with HITL, and authority score
improvements.

Issues: #61 (closed), #62, #63, #64, #68

## Next: to be planned via /plan-next-session

(No next-session focus selected yet. Run `/plan-next-session ontology-v2`
to pick the first slice from the phases below.)

## Remaining epic phases

### Phase 1: Authority score improvements (#68)

Widen the authority score range with additional signals (formal
terminology, entity count, data freshness) so scores provide
meaningful differentiation.

**Definition of done:** Score range spans at least 0.5 across all
mappings. Benchmark shows score-ranked results correlate with
retrieval quality.

**Dependencies:** None.

### Phase 2: Concept-first retrieval (#62)

`retrieve(concept="Condition")` without naming a source. Fan-out to
all sources with that concept, merge results weighted by authority
scores.

**Definition of done:** API accepts `concept=` parameter. Fan-out
queries all mapped sources and merges results. Benchmark validates
cross-source recall.

**Dependencies:** Phase 1 (meaningful scores improve fan-out ranking).

### Phase 3: Eval-driven self-improvement (#63)

Build an eval pipeline measuring per-mapping retrieval effectiveness
with a feedback loop to adjust authority scores and flag dead/stale
mappings.

**Definition of done:** Eval run produces per-mapping quality scores.
Auto-adjustment of authority scores based on observed retrieval
performance. Doctor integration for flagged mappings.

**Dependencies:** Phase 2 (concept-first queries generate the per-mapping
signal data).

### Phase 4: Query success monitoring (#64)

Instrument the retrieval path to track per-mapping hit rates and
trigger self-improvement when thresholds are crossed.

**Definition of done:** Per-mapping metrics stored. Trigger conditions
fire the doctor or score adjustment when hit rates drop. Dashboard or
report for ops visibility.

**Dependencies:** Phase 3 (self-improvement pipeline must exist for
triggers to invoke).

### Phase 5: Onboarding pipeline with HITL (#61) -- COMPLETE

Shipped 2026-09-10. Entity discovery via LLM (discover_entities()),
CLI review wizard (review_ontology_proposal.py), pipeline integration
(Stage 8 of pipeline.ingest()), doctor validation after ontology
population. All 5 acceptance criteria met.

## What this covers (and what it doesn't)

**In scope:**
- #61 Onboarding pipeline with HITL
- #62 Concept-first retrieval
- #63 Eval self-improvement loops
- #64 Query success monitoring
- #68 Authority score improvements

**Out of scope:**
- Platform ops (NEXT_SESSION-platform-ops.md): #27, #66, #67, #70
- Platform quality (NEXT_SESSION-platform-quality.md): #65
