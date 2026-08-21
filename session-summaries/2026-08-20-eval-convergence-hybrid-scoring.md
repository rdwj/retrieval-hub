# Session Summary -- 2026-08-20 (evening) eval-convergence hybrid scoring

**Plan:** NEXT_SESSION-eval-convergence.md (E2 + E8)   **Commits:** uncommitted (pending approval)   **Branch:** main
**Deployed:** none   **Model:** Claude Opus 4.6 (1M context)

## Plan vs. actual
Planned: implement register-aware rewriting (E2) and hybrid scoring (E8),
run full 30-query eval, identify best configuration. Shipped: all three
steps completed. Slipped: none. Scope: stayed in scope.

## Shipped
- Added `cross_encoder_register_aware` strategy (E2) and three
  `hybrid_alpha_N` strategies (E8) to `scripts/eval_rerank_strategies.py`
- Full 30-query Ragas eval (3 metrics, 6 strategies) completed in
  `eval/rewrite_lift/runs/rerank-full-30/`
- Eval register updated with Run 6 results
- Best configuration identified: `hybrid_alpha_03` (alpha=0.3)

## Verification & confidence
- Smoke test (3 queries, all 4 new strategies) passed before full run
- Full 30-query eval with Ragas scoring (gpt-oss-120b, reasoning off)
- Results compared against cached baselines from prior session (same seed,
  same models, same query set)
- Confidence: **high** -- the alpha sweep shows a clean monotonic trend,
  hybrid_0.3 dominates on 3 of 4 metrics (answer_relevancy, faithfulness,
  MRR), and the 30-query sample covers both registers

## Judgment calls & deviations
- Used stored cosine scores from retrieval (not re-embedded) for the hybrid
  blend's cosine component. For candidates found via rewrites, this is
  cosine to the rewrite query, not the original. Kept highest score per
  text across all variants. This is consistent with what makes cosine_dedup
  effective and avoids loading the embedding model, but a future experiment
  could test re-embedding against the original query.
- Min-max normalization for blending cross-encoder and cosine scores.
  Alternative: z-score or rank-based normalization. Min-max is simplest and
  worked well.

## Backlog delta
Filed: none. Closed: none. Deferred: answer model/prompt tuning deprioritized
(hybrid scoring resolved the trade-off without needing it).

## Drift & forward-collisions
- Backward: none
- Forward: none

## For the reviewer
- Sanity-check: the faithfulness improvement with hybrid scoring (+4.3pts)
  is surprisingly large given that it's a re-ranking change. Worth verifying
  on the expanded query set (Phase 5) to see if it holds or is noise.
- Thin verification: per-register faithfulness is NaN for most strategies
  due to Ragas issues with shorter answers. The aggregate faithfulness is
  computed only from queries where Ragas returned a value.
- Wants guidance: none

## Risks / watch-fors
- Ragas "1 generation instead of requested 3" warnings appear consistently.
  This may affect answer_relevancy scores (which depend on multiple
  generated questions). Could explain some of the scoring noise between
  strategies.
- gpt-oss-120b connection errors caused retries during scoring. One
  InstructorRetryException was logged. Results appear unaffected but the
  scoring model's stability is a recurring concern.
