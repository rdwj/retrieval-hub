# Session Summary — 2026-08-26 · eval-convergence · Phase 2 completion + checkpoint rewrite

**Plan:** NEXT_SESSION-eval-convergence.md (Phase 2)   **Commits:** `b84d4b6`..staged (main)
**Deployed:** EvalHub container rebuilt with checkpointing on gpt-oss-120b   **Model:** Claude Opus 4.6

## Plan vs. actual

Planned: complete the refine-strategy sweep (4 jobs). Shipped: per-batch JSONL checkpointing for scoring stage, PVC-backed run data, 48h default deadline, and all 4 sweep jobs completed with results registered. Scope expanded to include the checkpoint rewrite after two jobs were killed by the 12h deadline, losing 30+ hours of compute.

## Shipped

- `scripts/eval_answer_quality.py` — rewrote `_stage_score()` to score in configurable batches (default 10), appending per-query results to JSONL checkpoint files; resumes from checkpoint on restart; added `--score-batch-size` CLI arg
- `retrieval-hub-evalhub/openshift.yaml` — renamed PVC from `evalhub-model-cache` to `evalhub-run-data`
- `retrieval-hub-evalhub/submit-job.sh` — switched from emptyDir to PVC mount; added `EVALHUB_SCORE_BATCH_SIZE` env var; default `activeDeadlineSeconds` raised to 172800 (48h)
- `retrieval-hub-evalhub/src/evalhub_runner/__main__.py` — added `score_batch_size` env var mapping
- Memory: `feedback-long-job-deadlines` — always use 48h+ deadlines on eval Jobs
- Memory: `project-eval-checkpoint-rewrite` — checkpoint rewrite context and rationale

## Verification & confidence

- All 4 sweep runs completed and registered in the eval register
- refine-section survived a 40-hour run with JSONL checkpoints saving every 10 queries — the checkpoint mechanism proved out under real conditions
- 358 tests pass, 1 pre-existing failure from parallel session (`test_resolve_embedding_endpoint_unhealthy_model`)
- Confidence: **high** — the checkpointing was validated by the longest eval run in the project's history (refine-section, ~40h wall time)

## Judgment calls & deviations

- Extended deadlines to 48h (then baked as default) after two jobs were killed at 12h, losing all scoring progress. The CLAUDE.md lesson about container memory limits has a parallel here: eval job deadlines must account for worst-case scoring time.
- Ran sweep jobs sequentially after the initial parallel attempt caused LLM contention (4 jobs at 30s/eval became 235s/eval for section-refine). Sequential is slower in wall clock but each job finishes reliably.

## Backlog delta

Memory `feedback-long-job-deadlines` created. Memory `project-eval-checkpoint-rewrite` created. No issues filed or closed.

## Drift & forward-collisions

- Forward — eval-convergence Phase 4 (leaderboards/publication): all sweep data is now in the eval register, ready for the arXiv methods section and leaderboard gap analysis.

## For the reviewer

- Sanity-check: the `_stage_score()` rewrite processes batches sequentially within a condition. The Ragas `evaluate()` call is still the unit of work — if it hangs on a single query, the batch timer keeps running. Consider adding a per-batch timeout.
- Thin verification: the JSONL resume path (killing a job mid-batch and resubmitting) was validated by the refine-section run surviving multiple deadline extensions, but not by an explicit kill-and-resume test.
- Wants guidance: none.

## Risks / watch-fors

- The parallel session introduced a test failure (`test_resolve_embedding_endpoint_unhealthy_model`). Not from this session's changes but needs investigation.
- The `eval/aircraft-sb-test/` untracked directory is from the parallel session — needs gitignoring or committing.

## Refine-strategy sweep results

| Config | ctx_prec | ans_rel | faith |
|---|---|---|---|
| no refine | 0.732 | 0.725 | 0.843 |
| adjacent-2 | 0.353 | 0.735 | 0.838 |
| adjacent-4 | 0.272 | 0.724 | 0.847 |
| section | 0.253 | 0.728 | 0.877 |

No refine is the Pareto winner. Refine strategies hurt context precision significantly while providing modest faithfulness gains. Answer relevancy is stable across all configs.
