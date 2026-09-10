# Next Session -- Ontology v2

## Epic: Ontology self-improvement and concept-first retrieval

Build on the ontology registry (shipped in the ontology v1 epic) with
eval-driven self-improvement, query success monitoring, concept-first
retrieval, an onboarding pipeline with HITL, and authority score
improvements.

Issues: #61 (closed), #62 (closed), #63, #64, #68 (closed)

## Next: Eval-driven self-improvement (#63)

Build a per-mapping eval pipeline that measures how much each ontology
mapping improves retrieval, then wire a feedback loop that auto-adjusts
authority scores and flags low-quality mappings for the doctor.

### Implementation steps

1. **Add per-mapping quality metrics to the benchmark**

   Extend `scripts/eval_ontology_benchmark.py` to produce per-mapping
   scores. For each mapping exercised in the cross_source and
   concept_first dimensions, compute:
   - `hit_contribution`: how many hits came through this mapping's
     local_name (compare with-ontology hits by source+doc_section
     against without-ontology baseline)
   - `precision_signal`: fraction of hits from this mapping that ranked
     in the top-k (did this mapping's hits actually surface useful
     content, or did they get buried?)
   - `is_dead`: mapping produced zero hits across all queries that
     should have exercised it

   Output: a `per_mapping_quality` section in `summary.json` keyed by
   `(canonical_name, source_slug, local_name)` with these metrics.

2. **Build the self-improvement pipeline**

   New module `src/retrieval_hub/ontology/self_improve.py` with:
   - `evaluate_mapping_quality(session, benchmark_results) -> list[MappingFinding]`
     Reads the per-mapping metrics from step 1 and classifies each
     mapping: `healthy` (positive hit contribution), `underperforming`
     (low precision), `dead` (zero hits), `missing_coverage` (concept
     has mappings in some sources but not others).
   - `adjust_authority_scores(session, findings) -> list[ScoreAdjustment]`
     For underperforming mappings, reduce authority score by a damping
     factor (e.g., `score *= 0.9`). For consistently healthy mappings
     with high precision, apply a small boost (e.g., `score *= 1.05`,
     capped at 1.0). Returns the list of adjustments made for audit.
   - `apply_adjustments(session, adjustments)` writes the new scores
     back to `OntologyMapping.authority_score` with `flag_modified()`.

3. **Integrate with the doctor**

   Wire findings from step 2 into the doctor:
   - `dead` findings trigger `check_dead_mappings` for confirmation
     (the eval may have insufficient queries to exercise a mapping;
     the doctor does an actual retrieval probe)
   - `missing_coverage` findings feed into `check_coverage_gaps`
   - Add a new doctor check: `check_eval_flagged_mappings(session,
     findings)` that reports mappings the eval flagged but the doctor's
     existing checks wouldn't catch (underperforming but not dead)

4. **CLI entry point**

   Add a `scripts/run_self_improvement.py` that orchestrates:
   benchmark run -> evaluate_mapping_quality -> adjust_authority_scores
   -> doctor validation. Should be runnable as a one-shot or as a
   CronJob in the cluster.

5. **Test with real data**

   Run the pipeline against the dev database. Verify:
   - Per-mapping metrics appear in benchmark output
   - At least one mapping gets a score adjustment (use a known
     low-quality mapping if needed)
   - Doctor picks up eval-flagged findings
   - Authority scores are persisted correctly

**Sequencing.** Steps 1-2 are the core. Step 3 integrates with existing
infra. Step 4 wraps it for ops. Step 5 validates end-to-end. Steps 1
and 2 can be developed together since the eval output schema drives the
self-improvement input.

**Constraints for the session:**
- `flag_modified()` on `OntologyMapping.authority_score` after writes
  (CLAUDE.md lesson).
- The benchmark's `authority_correlation` metric is broken with RRF
  scores. Don't use it. The new per-mapping metrics replace it as the
  quality signal.
- Authority score adjustments must be bounded: no mapping should drop
  below a floor (0.3) or exceed a ceiling (1.0). Prevents runaway
  feedback.
- `compute_authority_scores()` in `ontology/authority.py` computes
  scores from source metadata (static factors). The self-improvement
  adjustments are a separate, additive signal from observed retrieval
  performance. Keep the two mechanisms distinct -- don't merge them
  into one function.
- `127.0.0.1` not `localhost` for local DB connections (CLAUDE.md).

**Session start protocol:**
- Premise checks (~5 min, report before acting):
  1. Confirm `concept_query()` is in `retrieval/api.py` and returns
     `(results, source_mappings)` with authority weights
  2. Run the benchmark: `python scripts/eval_ontology_benchmark.py`
     and verify it produces results including the `concept_first`
     dimension added in session 3
  3. Confirm the doctor runs clean:
     `python scripts/ontology_doctor.py --skip-retrieval`
- Rules with history:
  1. `flag_modified()` for JSON/float column mutations (CLAUDE.md)
  2. `127.0.0.1` not `localhost` for DB connections (CLAUDE.md)
  3. Score adjustments must be idempotent -- running the pipeline
     twice on the same benchmark results should produce the same
     final scores, not compound the adjustment
- Stop-and-ask before: deploying the self-improvement pipeline as a
  CronJob, modifying production authority scores on the cluster DB.
- Close ritual: session summary + `/plan-next-session ontology-v2` to
  queue Phase 4 (#64).

## Remaining epic phases

### Phase 1: Authority score improvements (#68) -- COMPLETE

Shipped 2026-09-10. Added formal terminology, entity coverage, and
data freshness signals. Score range widened from 0.632 to 0.980
(29 distinct scores). Doctor score clustering: 17 → 1. Benchmark
correlation metric invalidated by BM25 hybrid retrieval change (#65)
but retrieval quality metrics held or improved.

**Dependencies:** None.

### Phase 2: Concept-first retrieval (#62) -- COMPLETE

Shipped 2026-09-10. `retrieve(concept="Condition")` fans out to all
mapped sources, queries each with per-source doc_section filters, and
merges via authority-weighted RRF. Deployed and live-tested on
gpt-oss-120b. 21 new tests, benchmark dimension added.

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

## What landed last session (2026-09-10, session 3)

Concept-first retrieval shipped (Phase 2, #62). Added `concept`
parameter to the MCP `retrieve` tool, `resolve_concept_sources()` and
`concept_query()` to the retrieval API, authority-weighted RRF merge
via `source_weights` on `rrf_merge()`. Benchmark `concept_first`
dimension with 3 queries. 21 new tests. Deployed to gpt-oss-120b and
live-tested -- `concept="Condition"` returned results from 3 sources
(SNOMED, FHIR, Hetionet) with per-source metadata for 5 mapped sources.
Review-driven fixes: removed false confidence warnings on RRF-scored
queries, removed dead error handler.

**Closed:** #62 — Concept-first retrieval with fan-out across sources
**Closed:** #68 — Authority score improvements (session 2)

See: `session-summaries/2026-09-10-ontology-v2-concept-first-retrieval.md`

## Watch out for

- The `semantic_context` JSON column needs `flag_modified()` after mutation
  (CLAUDE.md lesson).
- The benchmark's authority_correlation metric is structurally broken with
  RRF-based scores (only 6 distinct similarity values across 57 hits).
  Don't use it as a quality signal. Per-mapping quality metrics (Phase 3)
  are the replacement.
- Authority score adjustments from eval feedback must be bounded (floor
  0.3, ceiling 1.0) and idempotent to prevent runaway feedback loops.
- The `_check_confidence` false positive also affects the existing
  multi-source path (server.py line 856). Not introduced by session 3,
  but now more visible. Consider fixing for all RRF-scored paths.

## If blocked

- If the benchmark can't run (embedding service down), implement the
  self-improvement module against mock benchmark results and validate
  the score adjustment logic with unit tests. Wire to real data later.
- If the doctor integration is too complex for one session, ship steps
  1-2 (per-mapping metrics + score adjustment) and defer step 3 (doctor
  integration) to a follow-up.

## What this covers (and what it doesn't)

**In scope:**
- #61 Onboarding pipeline with HITL (closed)
- #62 Concept-first retrieval (closed)
- #63 Eval self-improvement loops
- #64 Query success monitoring
- #68 Authority score improvements (closed)

**Out of scope:**
- Platform ops (NEXT_SESSION-platform-ops.md): #27, #66, #67, #70
- Platform quality (NEXT_SESSION-platform-quality.md): #65
