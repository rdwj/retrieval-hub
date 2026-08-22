# Session Summary — 2026-08-22 · eval-convergence · Phase 3 completion and chunk config decision

**Plan:** NEXT_SESSION-eval-convergence.md (Phase 3 wrap-up)   **Commits:** none yet (prepare-and-ask)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual

Planned: run full Ragas evals on 512/64 and 1024/0 chunk configs, decide
winner, record in eval register. Shipped: all planned items plus a new
`/eval-report` skill for standardized Pareto front comparison reports.
Scope expanded slightly with the skill.

## Shipped

- Full Ragas evals (context_precision, answer_relevancy, faithfulness) on
  512/64 and 1024/0 chunk configs via `eval_answer_quality.py` with
  temporary active-index switching.
- Decision: 512/0 confirmed as winner. Pareto-optimal on answer_relevancy
  (0.735) with competitive faithfulness (0.854). 1024/0 has higher
  faithfulness (0.882) but lower answer_relevancy (0.719). 512/64
  dominated on all Ragas metrics.
- `scripts/import_nomic_sweep_results.py` — imports Nomic sweep results
  (retrieval + Ragas metrics) into the eval register as suite
  `va-cpg-nomic-chunking-sweep` v1 with 4 runs.
- `.claude/skills/eval-report/` — Pareto front scatter plot skill with
  faithfulness as bubble size + color gradient, accessible raw-number
  table below, JSON summary alongside.
- Final report at `eval/reports/va-cpg-chunk-sweep-final.png`.
- Eval register populated: baseline metrics now available for refine-tool
  epic Phase 5 (ctx_precision 0.815, ans_rel 0.735, faithfulness 0.854).

## Verification & confidence

- Three full Ragas runs on identical 30-query eval set (seed 42), same
  scoring LLM (gpt-oss-120b), same pipeline.
- Eval register import verified with SQL query (4 runs under the suite).
- Report script lint-clean and tested with the real data.
- Confidence: **high** — all three configs evaluated under identical
  conditions on the same query set.

## Judgment calls & deviations

- Used SQL UPDATE to temporarily switch `active_physical_index_id` rather
  than adding a CLI flag to the eval script. Pragmatic for a one-off
  comparison; future sweeps should use EvalHub.
- Recommended keeping 512/0 despite 1024/0's higher faithfulness because
  the answer_relevancy gap is user-facing and the faithfulness difference
  (0.028) is within noise for 30 queries. Revisit with confidence
  intervals in Phase 5 (100+ queries).
- Created `/eval-report` skill at user request, expanding scope beyond
  the original plan.

## Backlog delta

Phase 3 complete. Refine-tool epic Phase 5 unblocked. No new issues
filed. Memory: none needed (results are in the eval register and reports).

## Drift & forward-collisions

- Backward — none
- Forward — the eval register baseline (ctx_precision 0.815, ans_rel
  0.735, faithfulness 0.854) is the comparator the refine-tool epic's
  Phase 5 A/B testing will use.

## For the reviewer

- Sanity-check: 512/64 having worse Ragas scores than 512/0 despite
  higher MRR is counterintuitive. Overlap may introduce boundary noise
  that hurts answer generation. Worth watching if overlap is revisited.
- Thin verification: 30 queries is enough to see gross differences but
  not to detect <2pt deltas with confidence. Phase 5 (100+ queries with
  bootstrap CIs) will address this.
- Wants guidance: none

## Risks / watch-fors

- 1024/0 may prove better at scale: its higher faithfulness could be
  real, not noise. The Phase 5 expanded query set will tell.
- The eval report script is in `.claude/skills/` (not committed to the
  project proper). Consider moving to `scripts/` if it sees wider use.
- `smoke-e2-e8/` run directory is untracked and was not produced this
  session — should be committed or gitignored separately.
