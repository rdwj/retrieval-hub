# Next Session -- Ontology v2

## Epic: Ontology self-improvement and concept-first retrieval

Build on the ontology registry (shipped in the ontology v1 epic) with
eval-driven self-improvement, query success monitoring, concept-first
retrieval, an onboarding pipeline with HITL, and authority score
improvements.

Issues: #61 (closed), #62, #63, #64, #68

## Next: Widen authority score range (#68)

The current scoring formula in `authority.py` compresses all 77 mappings
into a 1.04–1.248 range — too narrow for concept-first retrieval (Phase 2)
to rank sources meaningfully. The benchmark shows weak positive correlation
(r=0.36) that should improve with a wider, more informative score range.

1. **Add formal terminology signal**
   Sources backed by a formal terminology standard (SNOMED, FHIR, Hetionet)
   should score higher than informal sources (tale-of-two-cities). Add a
   `formal_terminology: true/false` flag to `semantic_context` for each
   source, and wire it into `compute_authority_scores()` as a multiplier.
   The flag values require judgment per source — set them in the scoring
   function or in `semantic_context` during onboarding.

2. **Add entity count coverage signal**
   A mapping where the source has 500 entities of a type should score higher
   than one with 3. `discover_entities()` already computes `entity_count` in
   its output. Wire a coverage weight into the formula — e.g., log-scaled
   entity count so large sources don't dominate linearly.

3. **Consider data freshness signal**
   `Source.last_refresh_at` exists in the model. Sources refreshed recently
   should get a modest boost over stale ones. This is lower priority than
   signals 1-2 — include if the range still needs widening after the first
   two, skip if the range is already well-differentiated.

4. **Re-seed scores and verify with doctor**
   Run `seed_authority_scores.py` (or the recompute path in
   `onboard_ontology_sources.py`). Run `ontology_doctor.py --skip-retrieval`
   and confirm: score range spans at least 0.5, no new score clustering
   warnings, no regressions in other checks.

5. **Re-run ontology benchmark**
   Run `eval_ontology_benchmark.py` and compare score-quality correlation
   against the baseline (r=0.36, range 1.04–1.248). The definition of done
   is: range ≥ 0.5, correlation improves or holds.

**Sequencing.** Steps 1-3 are formula changes in `authority.py` (can be
developed together). Step 4 verifies. Step 5 validates against retrieval
quality. All can run locally against the local catalog DB.

**Constraints for the session:**
- The formula is in `src/retrieval_hub/ontology/authority.py` (95 lines).
  Keep it a single function — don't over-engineer into a plugin system.
- The doctor's `_check_score_clustering()` (doctor.py:319) is the existing
  diagnostic. It should pass after the range widens.
- The benchmark baseline is in `eval/ontology_benchmark/runs/20260908-220904/`.
  Compare against that run.
- `semantic_context` is a JSON column — remember `flag_modified()` if
  updating it via SQLAlchemy (CLAUDE.md lesson).

**Session start protocol:**
- Premise checks (before step 1, ~5 min, report before acting):
  Confirm `authority.py` still has the 3-factor formula (status × family ×
  agreement). Run `ontology_doctor.py --skip-retrieval` to get current score
  distribution. Check that the benchmark baseline run still exists at the
  expected path.
- Rules with history:
  1. `flag_modified()` required for any `semantic_context` mutations (burned
     us once — CLAUDE.md).
  2. Use `127.0.0.1` not `localhost` for any DB connections (CLAUDE.md).
- Stop-and-ask before: running score updates against the cluster catalog DB.
  Local-only work is fine without asking.
- Close ritual: session summary + `/plan-next-session ontology-v2` to queue
  Phase 2 (#62).

## Remaining epic phases

### Phase 1: Authority score improvements (#68) -- COMPLETE

Shipped 2026-09-10. Added formal terminology, entity coverage, and
data freshness signals. Score range widened from 0.632 to 0.980
(29 distinct scores). Doctor score clustering: 17 → 1. Benchmark
correlation metric invalidated by BM25 hybrid retrieval change (#65)
but retrieval quality metrics held or improved.

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

## What landed last session (2026-09-10, session 2)

Authority score range widened (Phase 1, #68). Added 3 new scoring signals
to the 6-factor formula: formal terminology (1.2x boost for SNOMED, FHIR,
Hetionet, ClinicalTrials), log2-scaled entity coverage, and data freshness
(no-op while `last_refresh_at` is null). Score range: 0.632 → 0.980,
distinct scores: 11 → 29, clustering findings: 17 → 1. Doctor WARN count
unchanged (29). Retrieval quality held (overall hit lift +7.75 → +8.5).

Benchmark authority_correlation dropped (r=0.358 → 0.096) but this is
caused by BM25 hybrid retrieval (#65) changing similarity scores to
RRF-based values (only 6 distinct scores across 57 hits). The metric is
structurally unable to discriminate with rank-based RRF scores.

## What landed (2026-09-10, session 1)

HITL onboarding pipeline shipped (Phase 5, #61). Entity discovery via LLM,
CLI review wizard, pipeline integration as Stage 8, doctor validation.
`flag_modified` fix for JSON column persistence. Retro ran covering
platform-quality + onboarding pipeline.

**Closed:** #61 — Onboarding pipeline with HITL — all 5 acceptance criteria met

## Watch out for

- The `semantic_context` JSON column needs `flag_modified()` after mutation.
  If adding `formal_terminology` flags to sources, use the ORM carefully.
- The doctor's score clustering check uses a threshold that may need
  adjustment once the range widens — currently it flags when the range is
  "too narrow," but the threshold definition lives in doctor.py:319.
- The benchmark runs against local data. If the local catalog DB is out of
  sync with the cluster, scores and correlations may differ. Sync before
  drawing conclusions.

## If blocked

- If the local catalog DB is missing ontology data, re-run
  `scripts/onboard_ontology_sources.py` to repopulate.
- If the benchmark harness has issues, the doctor's score distribution
  check (step 4) is sufficient to verify range widening — the benchmark
  correlation check (step 5) can be deferred.

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
