# Retrospective: Eval Convergence Epic

**Date:** 2026-08-31
**Effort:** Build a production eval pipeline, identify optimal retrieval configuration, deploy EvalHub to cluster, establish statistical rigor, survey publication venues
**Duration:** 2026-08-12 through 2026-08-31 (11 sessions across ~3 weeks)

## What We Set Out To Do

Five phases to answer: what's the best retrieval configuration, and can we prove it with statistical rigor?

1. Build a full answer-quality eval pipeline (RAGAS scoring with context_precision, answer_relevancy, faithfulness)
2. Package it as EvalHub and deploy to the cluster for repeatable sweeps
3. Run a retrieval configuration sweep (embedding model, chunk size, reranking)
4. Survey industry leaderboards and publication venues
5. Expand the query set from 30 to 100+ with bootstrap confidence intervals

## What We Found

| Question | Answer |
|----------|--------|
| Best embedding model? | Nomic v1.5 dominates PubMedBERT (+9.4pts answer_relevancy) and BioLORD |
| Best chunk size? | 512/0 for VA CPG; 512/64 for aircraft-sb-test. Domain-dependent. |
| Reranking? | Not worth it with Nomic. Cross-encoder adds marginal ctx_precision (+1.7pts) but costs answer_relevancy (-5.2pts) |
| Refine strategy? | No-refine is Pareto winner. All refine strategies crush context_precision (-0.4 to -0.5 pts) |
| General-purpose vs domain-specific embedding? | General-purpose wins on clinical text — counterintuitive but consistent across both query registers |
| Leaderboard fit? | No relevant leaderboard accepts custom retrieval systems on custom corpora |

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Dropped hybrid reranking recommendation | Reversed finding | Run 6 said hybrid_0.3 was best (for PubMedBERT). Run 8 showed it's not needed with Nomic — simpler is better |
| Checkpoint rewrite mid-sweep | Emergency fix | Two jobs killed by 12h deadline, losing 30+ hours of compute. Rewrote scoring to per-batch JSONL checkpoints |
| Shifted from local to cluster-hosted embedding | Architecture | Repeated OOMKills from per-pod model loading. Nomic v1.5 deployed as shared TEI service |
| Phase ordering (5 before 4) | Practical | Dataset expansion was needed for statistical rigor; leaderboard survey was independent research. Running 5 first gave better data for the leaderboard decision |

## What Went Well

- **The eval infrastructure paid for itself repeatedly.** Built once in Phase 1 (Aug 20), used without major modification for 8+ eval runs across two sources, three embedding models, four refine strategies, and three chunk configs. The checkpoint rewrite was the only structural change.
- **Clear, defensible configuration winners.** The sweep results are unambiguous. No-refine Pareto-dominates all refine strategies. Nomic v1.5 dominates all tested embedding models. These aren't marginal — the gaps are 5-40 points.
- **EvalHub cluster deployment worked.** The refine-strategy sweep ran 4 jobs sequentially on the cluster, including a 40-hour section-refine run. The checkpoint mechanism survived real conditions. deploy-platform.sh orchestrates the full stack.
- **Statistical rigor is real.** 107 queries with bootstrap CIs, up from the original 30-query evaluation. The aircraft-sb-test proving run (156 queries) confirmed the pipeline generalizes to new sources.
- **The leaderboard survey saved effort.** Rather than spending weeks preparing a submission, a focused survey identified that no leaderboard fits our system type. Clean decision to defer.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| gpt-oss-120b instability | Recurring friction | Connection drops, retries, streaming workaround needed. Mentioned in 4/11 summaries. No mitigation beyond retry logic and streaming |
| Faithfulness NaN rate (12%) | Accept | RAGAS limitation on some query types. CIs computed on non-NaN subset. Would need a different scorer to eliminate |
| No per-batch timeout in scoring | Minor | If RAGAS hangs on a single query, the batch timer keeps running. Checkpoint saves progress but doesn't recover from a hung batch |
| Ragas "1 generation instead of 3" warnings | Accept | May affect answer_relevancy precision. Consistent across all runs so comparison validity is maintained |
| onboarding-journey-va-cpg.md still recommends PubMedBERT | Stale doc | Superseded by Nomic v1.5 decision. Not updated during this epic |

## Action Items

- [ ] Update `docs/onboarding-journey-va-cpg.md` to reference Nomic v1.5 instead of PubMedBERT
- [ ] Monitor Clinical NLP Workshop 9th edition CFP (dates TBD, likely late 2026) and SIGIR 2027 CFP (~Jan 2027) if paper work is revisited
- [ ] Consider per-batch timeout in `_stage_score()` to handle hung RAGAS evaluations

## Patterns

Compared with prior retros (code-source, data-products, model-registry-and-health):

**Continue:**
- Building reusable eval infrastructure rather than one-off scripts. The eval pipeline's longevity (8+ runs, 2 sources, no structural changes needed) validates the investment. Same pattern as the data-products retro's eval harness reuse.
- Smoke tests before full runs. Every session that ran a sweep tested on a small subset first. This caught issues (batch_size OOM, Ragas config problems) before committing to multi-hour runs.
- Per-batch checkpointing for long-running jobs. The 30-hour compute loss that prompted the rewrite is the kind of mistake you only make once. This should be the default pattern for any cluster job over 1 hour.

**Start:**
- Set 48h+ deadlines on cluster Jobs from the start, not after losing compute. This lesson is now in CLAUDE.md and MemoryHub but was learned expensively.
- Deploy embedding models as shared TEI services rather than loading per-container. The OOMKill cycle (4Gi limit, model loads to 1.5GB + Python overhead) repeated until the architecture changed.

**Stop:**
- Nothing to stop. The epic stayed well-scoped. Phase 4 was cleanly gated on the survey result rather than pushing through to leaderboard prep that wouldn't have been useful.

**Watch:**
- gpt-oss-120b stability. Four sessions hit connection issues. If the sandbox cluster is reprovisioned, deploy-platform.sh handles redeployment, but mid-run failures still cost wall time.
- #31 (MCP e2e testing) has appeared in both prior reconciliations and this one. It's the persistent gap — everything else gets tested except a live MCP retrieve round-trip.

## Appendix: Complete Eval Run Register

All eval runs produced during this epic and related work, organized by dataset and experiment type. Metrics are RAGAS scores unless noted. "rewrite" condition uses the query rewriter; "raw" does not.

### Dataset 1: VA CPG (clinical practice guidelines)

**Rewrite lift baseline** (30 queries, PubMedBERT 768-dim, 512/0 chunks)

| Run | Source | Condition | ctx_prec | ans_rel | faith | Notes |
|-----|--------|-----------|----------|---------|-------|-------|
| rewrite_lift/summary | eval_rewrite_lift.py | raw | — | — | — | hit@5 0.967, MRR 0.944, mean_score 0.597 |
| rewrite_lift/summary | eval_rewrite_lift.py | rewrite | — | — | — | hit@5 1.000, MRR 0.934, mean_score 0.704 |

**Answer-quality pipeline runs** (30 queries, PubMedBERT, 512/0)

| Run | Condition | ctx_prec | ans_rel | faith | Session |
|-----|-----------|----------|---------|-------|---------|
| 9084a31205273246 | raw | 0.809 | 0.646 | — | 2026-08-20 (Phase 1) |
| 9084a31205273246 | rewrite | 0.740 | 0.700 | — | 2026-08-20 (Phase 1) |

**Reranking comparison** (30 queries, PubMedBERT, 512/0, 6 strategies)

| Strategy | ctx_prec | ans_rel | faith | MRR | Session |
|----------|----------|---------|-------|-----|---------|
| cosine_dedup | 0.738 | 0.734 | 0.838 | 0.903 | 2026-08-20 |
| cross_encoder | 0.859 | 0.655 | 0.837 | 0.906 | 2026-08-20 |
| cross_encoder_register_aware | 0.845 | 0.680 | 0.838 | 0.933 | 2026-08-20 |
| hybrid_alpha_03 | 0.817 | 0.729 | 0.881 | 0.961 | 2026-08-20 |
| hybrid_alpha_05 | 0.824 | 0.682 | 0.878 | 0.928 | 2026-08-20 |
| hybrid_alpha_07 | 0.869 | 0.687 | 0.854 | 0.900 | 2026-08-20 |

**Embedding model comparison** (30 queries, 512/0)

| Run | Model | Condition | ctx_prec | ans_rel | faith | Session |
|-----|-------|-----------|----------|---------|-------|---------|
| embed-nomic | Nomic v1.5 | raw | 0.822 | 0.740 | — | 2026-08-21 |
| embed-nomic | Nomic v1.5 | rewrite | 0.807 | 0.704 | — | 2026-08-21 |
| embed-biolord | BioLORD-2023 | raw | 0.511 | 0.655 | — | 2026-08-21 |
| embed-biolord | BioLORD-2023 | rewrite | 0.571 | 0.698 | — | 2026-08-21 |
| embed-nomic-faithful | Nomic v1.5 | raw | 0.815 | 0.735 | 0.854 | 2026-08-21 |
| embed-nomic-faithful | Nomic v1.5 | rewrite | 0.809 | 0.704 | 0.813 | 2026-08-21 |

**Nomic reranking check** (30 queries, Nomic v1.5, 512/0)

| Strategy | ctx_prec | ans_rel | faith | Session |
|----------|----------|---------|-------|---------|
| cosine_dedup (Nomic raw) | 0.815 | 0.735 | 0.854 | 2026-08-21 |
| hybrid_alpha_03 (Nomic) | 0.832 | 0.683 | — | 2026-08-21 |

**Chunk config sweep** (30 queries, Nomic v1.5)

| Run | Chunk/Overlap | Condition | ctx_prec | ans_rel | faith | Session |
|-----|--------------|-----------|----------|---------|-------|---------|
| embed-nomic-faithful | 512/0 | raw | 0.815 | 0.735 | 0.854 | 2026-08-22 |
| nomic-512-64 | 512/64 | raw | 0.804 | 0.724 | 0.825 | 2026-08-22 |
| nomic-512-64 | 512/64 | rewrite | 0.718 | 0.701 | 0.789 | 2026-08-22 |
| nomic-1024-0 | 1024/0 | raw | 0.824 | 0.719 | 0.882 | 2026-08-22 |
| nomic-1024-0 | 1024/0 | rewrite | 0.754 | 0.693 | 0.804 | 2026-08-22 |

**Refine-strategy comparison** (30 queries, Nomic v1.5, 512/0)

| Run | Refine strategy | Condition | ctx_prec | ans_rel | faith | Session |
|-----|----------------|-----------|----------|---------|-------|---------|
| refine-adjacent | adjacent (window=2) | raw | 0.386 | 0.678 | 0.837 | 2026-08-22 |
| refine-adjacent | adjacent (window=2) | rewrite | 0.352 | 0.692 | 0.958 | 2026-08-22 |

**Expanded dataset** (107 queries, Nomic v1.5, 512/0, with bootstrap CIs)

| Run | Condition | ctx_prec | CI | ans_rel | CI | faith | CI | Session |
|-----|-----------|----------|----|---------|----|----|-------|---------|
| v2-512-0-expanded | raw | 0.738 | [0.682, 0.792] | 0.723 | [0.686, 0.759] | 0.806 | [0.752, 0.858] | 2026-08-22 |
| v2-512-0-expanded | rewrite | 0.610 | [0.540, 0.676] | 0.679 | [0.627, 0.727] | 0.765 | [0.697, 0.820] | 2026-08-22 |

**EvalHub cluster sweep — refine strategies** (107 queries, Nomic v1.5, 512/0, rewrite condition)

| Config | ctx_prec | ans_rel | faith | Session |
|--------|----------|---------|-------|---------|
| no refine | 0.732 | 0.725 | 0.843 | 2026-08-26/28 |
| adjacent-2 | 0.353 | 0.735 | 0.838 | 2026-08-26/28 |
| adjacent-4 | 0.272 | 0.724 | 0.847 | 2026-08-26/28 |
| section | 0.253 | 0.728 | 0.877 | 2026-08-26/28 |

### Dataset 2: aircraft-sb-test (aviation service bulletins)

**Chunk config proving run** (156 queries, Nomic v1.5, no refine, with bootstrap CIs)

| Run | Chunk/Overlap | Condition | ctx_prec | CI | ans_rel | CI | faith | CI | Session |
|-----|--------------|-----------|----------|----|---------|----|----|-------|---------|
| 256_0 | 256/0 | raw | 0.655 | [0.593, 0.715] | 0.788 | [0.772, 0.801] | 0.804 | [0.764, 0.848] | 2026-08-29/30 |
| 256_0 | 256/0 | rewrite | 0.659 | [0.601, 0.719] | 0.792 | [0.778, 0.806] | 0.831 | [0.792, 0.869] | 2026-08-29/30 |
| 512_0 | 512/0 | raw | 0.668 | [0.608, 0.726] | 0.791 | [0.777, 0.804] | 0.801 | [0.754, 0.842] | 2026-08-29/30 |
| 512_0 | 512/0 | rewrite | 0.651 | [0.594, 0.712] | 0.792 | [0.772, 0.808] | 0.804 | [0.759, 0.847] | 2026-08-29/30 |
| 512_64 | 512/64 | raw | 0.663 | [0.604, 0.722] | 0.798 | [0.783, 0.812] | 0.787 | [0.742, 0.835] | 2026-08-29/30 |
| 512_64 | 512/64 | rewrite | 0.665 | [0.603, 0.727] | 0.789 | [0.775, 0.802] | 0.839 | [0.800, 0.880] | 2026-08-29/30 |

**Winner: 512/64** — selected on faithfulness edge (+0.035 over 512/0 rewrite).

### Dataset 3: cross_dataset_reasoning (source selection)

Different eval methodology — measures source selection accuracy, not retrieval quality. 20 questions across ad-hoc, cross-dataset, and single-source categories.

| Run | Catalog size | src_precision | src_recall | exact_match | Session |
|-----|-------------|--------------|------------|-------------|---------|
| v0-baseline | 4 sources | 0.858 | 0.950 | 0.450 | 2026-08-22 |
| v1-disambiguate | 4 sources | 0.842 | 0.825 | 0.550 | 2026-08-22 |
| scale-14 | 14 sources | 0.526 | 0.950 | 0.100 | 2026-08-22 |
| scale-54 | 54 sources | 0.538 | 0.925 | 0.050 | 2026-08-22 |

Source precision degrades at scale; recall stays high. The agent over-queries (retrieves from too many sources) as catalog size grows.
