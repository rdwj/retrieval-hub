# Next Session — eval-convergence

## Next: Phase 5 — Query set expansion and statistical rigor

Expand the eval query set from 50 (30 sampled) to 120+ with clinical
category stratification and bootstrap confidence intervals. This gives
the statistical power to confirm the 512/0 vs 1024/0 faithfulness gap
(0.854 vs 0.882) is real or noise, and makes the eventual leaderboard
submission and paper credible.

1. **Generate 70+ new Q/A pairs from the VA CPG corpus**
   Current dataset has 50 questions across 17 CPGs and 5 categories, but
   distribution is uneven (hypertension: 6, osteoarthritis: 1). Generate
   new questions targeting under-represented CPGs and categories.
   - Use LLM-assisted generation: feed each CPG's source docs to gpt-oss
     and ask for factoid/treatment/procedure questions with ground-truth
     answers citing specific sections.
   - Validate each Q/A pair against the source document — the answer must
     be directly supported by the cited section.
   - Target distribution: ~8 questions per category (chronic-disease,
     mental-health, pain, rehabilitation, womens-health), balanced across
     lay and clinical registers.
   - Add to `eval/autorag/qa_dataset_draft.json`, bump version to `v2`.

2. **Add bootstrap confidence intervals to the eval pipeline**
   Modify `eval_answer_quality.py` to compute 95% bootstrap CIs on all
   aggregate metrics (context_precision, answer_relevancy, faithfulness).
   This requires running N bootstrap resamples of the per-query scores
   and reporting the 2.5th and 97.5th percentiles alongside the mean.
   Output the CIs in `summary.json` alongside the point estimates.

3. **Re-run the winner config (512/0) on the expanded set**
   Run `eval_answer_quality.py` with the full 120+ query set. Compare
   point estimates and CIs against the 30-query baseline. Use the
   `/eval-report` skill to produce the comparison report.

4. **Record results in the eval register**
   Create a new eval suite version or a new suite
   (`va-cpg-nomic-answer-quality-v2`) with the expanded results.

**Sequencing.** Step 1 (Q/A generation) is the bulk of the creative work
and should be done first. Step 2 (bootstrap CIs) is independent
engineering and can be done in parallel or after. Steps 3-4 are
sequential after 1 and 2.

**Session start protocol:**
- Premise checks (~5 min):
  - Databases up (`pg_isready -h 127.0.0.1 -p 5433` and `-p 5434`)
  - gpt-oss-120b reachable
  - Verify `idx_va_cpg_nomic_v1` table exists and is populated
  - Read `eval/autorag/qa_dataset_draft.json` to confirm current state
    (50 questions, version draft-v1)
  - Refine-tool epic running in parallel — don't modify shared retrieval
    code without checking for conflicts
- Rules with history:
  - gpt-oss-120b reasoning off via `enable_thinking=False` in `extra_body`
  - Ragas max_tokens=8192 to avoid faithfulness NaN
  - Per-condition checkpointing in scoring stage
  - **Use 127.0.0.1 not localhost** for Postgres connections
  - Q/A generation must cite specific source_doc and source_section from
    the VA CPG corpus — no hallucinated answers
- Stop-and-ask before: replacing the existing QA dataset (keep v1 as a
  separate file); modifying the eval register schema; modifying
  `eval_answer_quality.py` in ways that break existing run compatibility

## Remaining epic phases

Converge on the best retrieval configuration for the VA CPG source through
systematic experimentation, then publish results on the data card and
position for industry leaderboards. The eval infrastructure built here
serves the whole platform -- every source gets the same eval pipeline. This
epic also gates the refine tool epic's definition of done (A/B testing
refine requires this eval infrastructure).

### Phase 1: Full answer-quality eval pipeline — DONE

Built in session 2026-08-20 (morning). See Runs 1-5.

### Phase 2: EvalHub integration

Package the eval pipeline as an EvalHub task for automated sweeps on the
cluster, rather than running locally.

**Work:**
1. Define the eval task interface: parameterized inputs (chunk_size,
   overlap, embedding_model, rewriter_config, semantic_context).
2. Package as an EvalHub-compatible task (container + config).
3. Run a proof-of-concept sweep: the Tier 1 experiments from
   `eval/rewrite_lift/EVAL_PLAN.md` (expanded vocab mappings,
   register-aware rewriting).
4. Results flow back to `eval/rewrite_lift/` and the eval register.

**Definition of done:** At least two sweep experiments run on EvalHub with
results in the eval register. The sweep is repeatable without manual
intervention.

**Dependencies:** Phase 1 (need the full eval pipeline before automating it).

**Parallel-ok:** No -- sequential after Phase 1.

### Phase 3: Retrieval configuration sweep — DONE

Completed 2026-08-22. Full Ragas answer-quality evals on 3 chunk configs
(512/0, 512/64, 1024/0), 2 embedding models (PubMedBERT, Nomic v1.5).

**Winner:** 512/0 with Nomic v1.5 (no reranking). Pareto-optimal on
answer_relevancy (0.735) with competitive faithfulness (0.854). 1024/0
has higher faithfulness (0.882) but lower answer_relevancy (0.719).
512/64 is dominated on all Ragas metrics despite higher MRR.

**Results recorded:** eval register suite `va-cpg-nomic-chunking-sweep` v1
with 4 runs (256/0 retrieval-only, 512/0 + 512/64 + 1024/0 with full Ragas).
Report at `eval/reports/va-cpg-chunk-sweep-final.png`.

**Baseline metrics for refine-tool epic (Phase 5):**
- context_precision: 0.815
- answer_relevancy: 0.735
- faithfulness: 0.854

### Phase 5: Query set expansion and statistical rigor — NEXT

Expand the eval query set from 50 (30 sampled) to 120+ for statistical
power, add bootstrap confidence intervals to all metrics.

**Work:**
1. Generate additional Q/A pairs from the VA CPG corpus (LLM-assisted,
   validated against source documents).
2. Stratify by clinical category (not just register) to surface
   per-condition performance.
3. Re-run the best configuration on the expanded set.
4. Add bootstrap confidence intervals to the eval output.

**Definition of done:** 120+ query eval set with per-category stratification
and confidence intervals on all metrics. Results recorded in the eval
register.

**Dependencies:** None (running locally, not gated on EvalHub).

### Phase 2: EvalHub integration

Package the eval pipeline as an EvalHub task for automated sweeps on the
cluster, rather than running locally.

**Work:**
1. Define the eval task interface: parameterized inputs (chunk_size,
   overlap, embedding_model, rewriter_config, semantic_context).
2. Package as an EvalHub-compatible task (container + config).
3. Run a proof-of-concept sweep: the Tier 1 experiments from
   `eval/rewrite_lift/EVAL_PLAN.md` (expanded vocab mappings,
   register-aware rewriting).
4. Results flow back to `eval/rewrite_lift/` and the eval register.

**Definition of done:** At least two sweep experiments run on EvalHub with
results in the eval register. The sweep is repeatable without manual
intervention.

**Dependencies:** Phase 1 (done). Phase 5 results inform the task config.

### Phase 4: Industry leaderboards and publication

Research which retrieval/RAG leaderboards are relevant, understand their
eval protocols, and position retrieval-hub's results for submission.

**Work:**
1. Survey existing leaderboards: MTEB, BEIR, MIRACL, domain-specific
   clinical NLP benchmarks (n2c2, OHNLP, etc.). Identify which accept
   custom retrieval systems vs. only embedding models.
2. For leaderboards that accept retrieval systems: map our eval metrics to
   their protocol. Identify any gaps (different query formats, different
   corpora, different metrics).
3. Prepare a submission-ready eval run if a suitable leaderboard exists.
4. Draft the arXiv paper outline from `EVAL_PLAN.md` into a full abstract
   and methods section using the accumulated eval register data.

**Definition of done:** Leaderboard targets identified with gap analysis.
arXiv paper abstract and methods section drafted. At least one leaderboard
submission prepared (or a documented decision about why none fit yet).

**Dependencies:** Phase 5 (need expanded results with CIs for credible
submission). Phase 2 (EvalHub for reproducible runs).

---

## What this covers (and what it doesn't)

**In scope:**
- Full answer-quality eval pipeline (Ragas integration)
- EvalHub packaging and automated sweeps
- Retrieval configuration optimization (chunking, embeddings)
- Industry leaderboard positioning
- arXiv paper preparation
- Query set expansion for statistical rigor

**Out of scope (other epics own):**
- Refine tool implementation (`NEXT_SESSION-refine-tool.md`)
- Refine tool A/B testing (uses this epic's infrastructure but lives in
  the refine epic)
- New source onboarding (future epic)
- Fine-tuning / model training (future work, referenced in refine epic)

## What landed last session (2026-08-22)

Phase 3 wrap-up: full Ragas answer-quality evals on chunk configs.

- Ran full Ragas evals (context_precision, answer_relevancy, faithfulness)
  on 512/64 and 1024/0 chunk configs to break the MRR tie with 512/0.
- 512/0 confirmed as winner: best answer_relevancy (0.735), competitive
  faithfulness (0.854), Pareto-optimal on the two-axis scatter.
- Created `scripts/import_nomic_sweep_results.py` and imported all sweep
  results into the eval register (suite: `va-cpg-nomic-chunking-sweep`).
- Created `/eval-report` skill at `.claude/skills/eval-report/` for
  standardized Pareto front comparison reports.
- Final report at `eval/reports/va-cpg-chunk-sweep-final.png`.
- Baseline metrics now available for refine-tool epic Phase 5.

## What landed earlier (2026-08-21, afternoon)

Made the Nomic switch official and ran the chunk sweep:

- Updated `ingest_va_cpg.py` to use Nomic v1.5 as the production
  embedding model (was PubMedBERT). Production active index is
  `idx_va_cpg_nomic_v1` (512/0, 6,500 chunks).
- Added `--chunk-tokens` and `--overlap-tokens` flags to the
  alt-embedding script for sweep flexibility.
- Ran 4-config chunk sweep with Nomic: 256/0, 512/0, 512/64, 1024/0.
  All achieve 100% hit_rate@5. MRR: 512/64 and 1024/0 tie at 0.967,
  256/0 and 512/0 at 0.911. Results in
  `eval/va_cpg_chunking_sweep/sweep_results.json`.
- Scored faithfulness for Nomic raw: 0.854 (raw), 0.813 (rewrite).
  Results in `eval/rewrite_lift/runs/embed-nomic-faithful/`.
- Fixed all Postgres connection strings across the project from
  `localhost` to `127.0.0.1` to avoid IPv4/IPv6 ambiguity when
  `oc port-forward` runs alongside Podman containers.
- Updated docs: table references in onboarding journey.
- Added `Faithfulness` metric permanently to `eval_answer_quality.py`.

## What landed earlier (2026-08-21, morning)

Embedding model comparison (Runs 7-8) completed. Nomic v1.5 dominates
PubMedBERT on all metrics. Nomic raw (no reranking) is Pareto-optimal:
0.822 ctx_precision, 0.740 answer_relevancy. Adding hybrid_0.3 reranking
pushes ctx_precision to 0.839 but costs -5.2pts answer_relevancy.
Switched VA CPG active index to Nomic. Drafted data owner and ops
onboarding guides.

See `session-summaries/2026-08-21-eval-convergence-embedding-comparison.md`.

**Prior session (2026-08-20, evening):** Hybrid scoring (E8) resolved the
answer_relevancy trade-off. hybrid_alpha_03 is the new best reranking
config. See `session-summaries/2026-08-20-eval-convergence-hybrid-scoring.md`.

**Prior session (2026-08-20, morning):** Phase 1 complete. Answer-quality
eval pipeline built. Five eval runs (Runs 1-5). Cross-encoder reranking
+12.1% context_precision. See `session-summaries/2026-08-20-eval-convergence-reranking.md`.

## Watch out for

- **Nomic batch_size on MPS:** nomic-embed-text-v1.5 OOM'd at batch_size=32
  on Apple Silicon. Use batch_size=8 for 256- and 512-token chunks. For
  1024-token chunks, use batch_size=2. At query time the adapter only
  embeds one query at a time so this doesn't affect retrieval.
- **jina-embeddings-v3:** failed to load with current transformers version
  (`AttributeError: 'XLMRobertaLoRA' has no attribute
  'all_tied_weights_keys'`). Would need a transformers upgrade or pinned
  revision to test.
- Ragas "1 generation instead of 3" warnings appeared consistently in
  Runs 6-7. Consistent across all embedding models, so unlikely to bias
  the comparison.
- gpt-oss-120b sandbox cluster may be reprovisioned. If the endpoint
  changes, update the eval scripts.

## If blocked

- If Ragas still doesn't work with any available LLM, fall back to a
  custom LLM-as-judge implementation.
- If EvalHub isn't ready, run sweeps locally with a shell script wrapper
  around the eval script.
