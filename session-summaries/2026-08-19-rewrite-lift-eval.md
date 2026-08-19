# Session: Rewrite lift evaluation (2026-08-19)

Phase 4 of the query-rewriter epic: run a retrieval eval comparing raw vs.
rewritten queries on the VA CPG source to measure whether the rewriter
produces a real improvement.

## What landed

### Eval script (`scripts/eval_rewrite_lift.py`)

Automated end-to-end eval that, for each query in a 30-query test set:

1. Runs raw retrieval via `retrieval_hub.retrieval.api.query()` (top-5)
2. Rewrites the query via `RewriterService.rewrite()` against gpt-oss-120b
3. Runs retrieval for each rewrite, deduplicates, takes top-5
4. Computes hit_rate@5, MRR@5, and mean cosine similarity for both paths
5. Outputs per-query CSV and aggregate JSON to `eval/rewrite_lift/`

Test set: all 14 lay-register questions + 16 randomly sampled
clinical-register questions from `eval/autorag/qa_dataset_draft.json`.

### Results

**Lay register (n=14) -- the target use case:**

| Metric     | Raw   | Rewrite | Delta   |
|------------|-------|---------|---------|
| hit_rate@5 | 0.929 | 1.000   | +0.071  |
| MRR@5      | 0.881 | 0.964   | +0.083  |
| mean_score | 0.572 | 0.689   | +0.117  |

One query (q024: "How long should someone keep taking antidepressants after
feeling better?") flipped from miss to hit with rewriting.

**Clinical register (n=16) -- control:**

| Metric     | Raw   | Rewrite | Delta   |
|------------|-------|---------|---------|
| hit_rate@5 | 1.000 | 1.000   | 0.000   |
| MRR@5      | 1.000 | 0.854   | -0.146  |
| mean_score | 0.619 | 0.708   | +0.089  |

Clinical queries don't benefit from rewriting (already using correct
terminology) and MRR slightly degrades as rewrites introduce broader
clinical terms that sometimes surface less-specific chunks.

**Overall (n=30):** hit_rate +0.033, MRR -0.039, mean_score +0.102.

### Methodology notes

- Metrics: hit_rate@5, MRR@5, mean cosine similarity (ground-truth-based,
  no LLM judge needed)
- Hit matching: CPG slug -> keyword lookup against chunk doc_title
  (case-insensitive)
- Ragas 0.4.3 was installed but not used for scoring. `answer_relevancy`
  is a generation metric (needs a generated response) and doesn't apply to
  a retrieval-only eval. `context_precision` requires `instructor` which
  doesn't work cleanly with the gpt-oss-120b reasoning model. The
  ground-truth metrics are more directly informative anyway.
- LLM: gpt-oss-120b (reasoning model, `/mnt/models` on sandbox cluster)
- Embedding model: PubMedBERT (NeuML/pubmedbert-base-embeddings, 768-dim)
- Eval wall time: 858 seconds (~14 minutes for 30 queries)

## Interpretation

The rewriter delivers its intended value: bridging the vocabulary gap
between lay queries and clinical documentation. On lay-register queries,
all three metrics improve. The +11.7% mean_score lift indicates the
rewriter consistently finds semantically closer chunks even when both raw
and rewritten paths hit the correct document.

The MRR degradation on clinical queries (-0.146) is expected and
acceptable. When the original query already uses clinical terminology,
rewrites add breadth at the cost of precision. A production deployment
could skip rewriting when the query already uses domain-specific
vocabulary (a future optimization, not needed for MVP).

## Commits

- `scripts/eval_rewrite_lift.py`: eval script
- `eval/rewrite_lift/results.csv`: per-query results
- `eval/rewrite_lift/summary.json`: aggregate metrics
- `session-summaries/2026-08-19-rewrite-lift-eval.md`: this summary

## Epic status

The query-rewriter epic (issue #15) is complete. All five phases are done:
- Phase 1: Core rewriter service (commit `625a750`)
- Phase 2: VA CPG metadata (commit `625a750`)
- Phase 3: Wire into retrieve (commit `625a750`)
- Phase 4: Eval -- rewrite lift measurement (this session)
- Phase 5: README quick-start (commit `6ec9bfe`)
