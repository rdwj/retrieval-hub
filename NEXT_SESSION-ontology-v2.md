# Next Session -- Ontology v2

## Epic: Ontology self-improvement and concept-first retrieval

Build on the ontology registry (shipped in the ontology v1 epic) with
eval-driven self-improvement, query success monitoring, concept-first
retrieval, an onboarding pipeline with HITL, and authority score
improvements.

Issues: #61 (closed), #62 (closed), #63 (closed), #64, #68 (closed)

## Next: Authority score normalization + query success monitoring (#64)

Two related pieces: normalize authority scores to [0, 1] so the
self-improvement pipeline's adjustments are visible, then instrument
the retrieval path to track per-mapping hit rates for runtime monitoring.

### Part 1: Normalize authority score range

The multiplicative authority formula (`status * family * agreement *
terminology * coverage * freshness`) produces scores from 0.870 to 1.850
across 186 mappings. Since the self-improvement ceiling is 1.0, every
eval-adjusted score clamps to the ceiling and the pipeline can't
differentiate mappings. Two approaches to consider:

**Option A — Post-hoc min-max normalization.** After computing raw
scores, normalize to [0, 1]: `(score - min) / (max - min)`. Preserves
relative ordering. Downside: adding a single extreme-scoring mapping
shifts all other scores.

**Option B — Cap multiplicative factors.** Reduce factor weights so the
product stays in [0, 1] by construction. For example, change agreement
from 1.0-1.3 to 1.0-1.15, terminology from 1.2 to 1.1, etc. Downside:
requires retuning all constants.

**Recommendation:** Option A is simpler and preserves the factor
semantics. Add a normalization step at the end of
`compute_authority_scores()` that maps [min, max] → [0.3, 1.0] (the
self-improvement bounds). This keeps the factor weights as-is and gives
the eval pipeline room to adjust.

**Files:** `src/retrieval_hub/ontology/authority.py`,
`tests/test_ontology/test_authority.py`

### Part 2: Query success monitoring (#64)

Instrument the retrieval path to emit per-mapping metrics at query time,
store them, and wire trigger conditions to the self-improvement pipeline.

1. **Metrics table.** New `ontology_query_metrics` table (or lightweight
   append model) with: `mapping_id`, `query_timestamp`, `hit_count`,
   `source_slug`, `concept`. Alembic migration.

2. **Instrumentation.** In `retrieval_hub.retrieval.api`, after
   `concept_query()` and `expand_doc_section_via_registry()` resolve
   mappings, emit a metric record per mapping exercised. Lightweight:
   just INSERT, no blocking. This also provides the real per-query
   precision data that the batch benchmark can't (solving the
   "precision always 1.0" limitation from Phase 3).

3. **Aggregation query.** Function to compute rolling hit rates per
   mapping (e.g., last 7 days). Used by the doctor and the
   self-improvement pipeline.

4. **Trigger integration.** Extend the self-improvement CLI
   (`scripts/run_self_improvement.py`) to accept `--from-metrics`
   as an alternative to `--benchmark-dir`. When metrics are available,
   the pipeline uses observed hit rates instead of benchmark data.

5. **Doctor integration.** New check: `check_low_hit_rate(session)`
   queries the metrics table for mappings below a hit-rate threshold,
   reports as WARN.

**Files:** `src/retrieval_hub/models/` (new model),
`src/retrieval_hub/retrieval/api.py`, `src/retrieval_hub/ontology/doctor.py`,
`scripts/run_self_improvement.py`, `alembic/versions/` (migration)

**Sequencing.** Part 1 first (targeted change, ~30 min). Part 2 in
order: migration → instrumentation → aggregation → triggers → doctor.
Parts 2.4 and 2.5 can be deferred to a follow-up if the session runs
long — the core value is metrics table + instrumentation.

**Constraints for the session:**
- After normalizing scores, re-run the self-improvement dry-run to
  verify scores now differentiate (not all clamped to 1.0)
- The instrumentation must not add latency to the hot retrieval path.
  Use fire-and-forget writes or batch at the end of `concept_query()`.
- `127.0.0.1` not `localhost` for local DB connections (CLAUDE.md)
- `flag_modified()` for any JSON column mutations (CLAUDE.md)
- Alembic migration must work against both local SQLite (tests) and
  cluster PostgreSQL

**Session start protocol:**
- Premise checks (~5 min, report before acting):
  1. Port-forward to cluster DB: `oc port-forward retrieval-hub-pg-0
     5434:5432 --context=gpt-oss-120b -n retrieval-hub`
  2. Verify self-improvement pipeline runs:
     `python scripts/run_self_improvement.py --skip-benchmark --dry-run`
  3. Check current score range:
     `SELECT min(authority_score), max(authority_score) FROM ontology_mapping`
  4. Confirm doctor runs clean:
     `python scripts/ontology_doctor.py --skip-retrieval`
- Rules with history:
  1. `flag_modified()` for JSON column mutations (CLAUDE.md)
  2. `127.0.0.1` not `localhost` for DB connections (CLAUDE.md)
  3. Score normalization must be idempotent — running
     `compute_authority_scores()` twice produces the same results
- Stop-and-ask before: modifying production authority scores on the
  cluster DB, deploying the monitoring instrumentation to the live
  MCP server.
- Close ritual: session summary + close #63 + close #64 (if all
  acceptance criteria met) + `/plan-next-session ontology-v2` or
  `/retro ontology-v2` if the epic is complete.

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

### Phase 3: Eval-driven self-improvement (#63) -- COMPLETE

Shipped 2026-09-10. Per-mapping quality metrics in benchmark
(`per_mapping_quality` in summary.json). Self-improvement module
(`ontology/self_improve.py`) with evaluate/adjust/apply pipeline.
Doctor integration (`check_eval_findings`). CLI orchestrator
(`scripts/run_self_improvement.py`). 22 new tests (103 total ontology).
Dry-run validated against cluster DB: 19 findings, 14 healthy,
5 missing_coverage.

Known limitation: precision metric is always 1.0 because
`concept_query()` returns only merged top-k results. Phase 4 runtime
monitoring provides the real per-query precision data.

**Dependencies:** Phase 2 (concept-first queries generate per-mapping
signal data).

### Phase 4: Query success monitoring (#64)

Instrument the retrieval path to track per-mapping hit rates and
trigger self-improvement when thresholds are crossed. Also normalize
authority scores to [0, 1] so eval adjustments are visible.

**Definition of done:** Authority scores normalized to [0, 1]. Per-mapping
metrics stored at query time. Trigger conditions fire the doctor or
score adjustment when hit rates drop. Dashboard or report for ops.

**Dependencies:** Phase 3 (self-improvement pipeline must exist for
triggers to invoke).

### Phase 5: Onboarding pipeline with HITL (#61) -- COMPLETE

Shipped 2026-09-10. Entity discovery via LLM (discover_entities()),
CLI review wizard (review_ontology_proposal.py), pipeline integration
(Stage 8 of pipeline.ingest()), doctor validation after ontology
population. All 5 acceptance criteria met.

## What landed last session (2026-09-10, session 4)

Eval-driven self-improvement shipped (Phase 3, #63). Per-mapping
quality metrics in the benchmark, self-improvement module with
idempotent score adjustment, doctor integration for eval findings,
CLI orchestrator. 22 new tests. Dry-run against cluster DB validated
end-to-end: 19 findings (14 healthy, 5 missing_coverage), all score
adjustments ceiling-clamped to 1.0 (motivating the score normalization
work in Phase 4).

**Closed:** #63 — Eval-driven self-improvement loops for mapping quality

See: `session-summaries/2026-09-10-ontology-v2-eval-self-improvement.md`

## Watch out for

- Authority scores currently range 0.870-1.850. After normalization, all
  existing tests that assert specific score values will need updating.
  Run the full test suite after changing the formula.
- The benchmark's authority_correlation metric is structurally broken with
  RRF-based scores. Don't use it as a quality signal.
- `pubmed-hypertension` uses a different embedding model than vllm-nomic,
  causing 404s when the benchmark or concept_query fans out to it. This
  silently drops results. Not blocking but affects monitoring coverage.
- The `_check_confidence` false positive affects the multi-source path
  (server.py line 856). Not blocking but worth fixing if touching nearby
  code.

## If blocked

- If the metrics table migration is complex (schema concerns), implement
  the score normalization first and ship it standalone. The monitoring
  instrumentation can follow in a separate commit.
- If the cluster DB port-forward is unstable, develop against the local
  SQLite test database and validate the Alembic migration separately.

## What this covers (and what it doesn't)

**In scope:**
- #61 Onboarding pipeline with HITL (closed)
- #62 Concept-first retrieval (closed)
- #63 Eval self-improvement loops (closed)
- #64 Query success monitoring
- #68 Authority score improvements (closed)

**Out of scope:**
- Platform ops (NEXT_SESSION-platform-ops.md): #27, #66, #67, #70
- Platform quality (NEXT_SESSION-platform-quality.md): #65
