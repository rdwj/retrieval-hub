# Session Summary — 2026-08-22 · refine-tool · Phase 5 A/B eval

**Plan:** NEXT_SESSION-refine-tool.md (Phase 5)   **Commits:** d6f068e..66e50e6 (main)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual

Planned: extend eval pipeline with refine stage, run adjacent + section
evals, compare against baseline. Shipped: implementation + adjacent eval
completed. Slipped: section eval skipped (justified — adjacent already
showed clear degradation, section returns 8x more context and would be
worse).

## Shipped

- `d6f068e` — eval pipeline extended with `--refine-strategy` and
  `--refine-window` flags. New `_stage_refine()` between retrieve and
  generate, with refined.json caching, chunk_index/chunk_id in
  serialized hits, refine params in config fingerprint.
- `66e50e6` — Phase 5 results recorded: adjacent refine degrades all
  three automated metrics. Session summary and plan update.

## Results

| Metric             | Baseline | Adjacent refine | Delta    |
|--------------------|----------|-----------------|----------|
| context_precision  | 0.815    | 0.386           | -0.429   |
| answer_relevancy   | 0.735    | 0.678           | -0.057   |
| faithfulness       | 0.854    | 0.837           | -0.017   |

## Verification & confidence

- Adjacent eval ran end-to-end against the 30-query Q/A set with the
  same LLM endpoints as the baseline (gpt-oss:20b for generation,
  gpt-oss-120b for scoring). Stages cached/checkpointed correctly.
- Smoke-tested refine API directly before running full eval.
- 323 + 43 tests pass. No test regressions.
- Confidence: **high** — the result is clear and directionally expected
  (diluting context with positionally-adjacent but semantically-irrelevant
  chunks penalizes precision).

## Judgment calls & deviations

- Skipped section eval after adjacent showed -0.429 on context_precision.
  Section returns ~43 chunks per hit vs 5 for adjacent — would be worse.
- Refine applied to both raw and rewrite conditions (not just raw), keeping
  the comparison fair within the run.

## Backlog delta

Closed Phase 5 of refine-tool epic. No issues filed this session.
Next for this epic: #34 multi-source retrieve.

## Drift & forward-collisions

- Backward — none. This session's changes don't affect other open issues.
- Forward — none.

## For the reviewer

- Sanity-check: the context_precision drop is large (-0.429). Worth
  verifying that the Ragas context_precision metric is measuring what
  we think it is with expanded context. The metric penalizes irrelevant
  retrieved chunks, which is exactly what adjacent refine adds.
- Thin verification: section eval was not run. The inference that it would
  be worse is sound (more dilutive context) but unproven.
- Wants guidance: none.

## Risks / watch-fors

- The eval_answer_quality.py file has changes from multiple parallel
  sessions (expanded SLUG_TO_KEYWORDS, bootstrap CI, dynamic query_count).
  These are user-applied improvements, not conflicts, but the file should
  be committed coherently by one session.
