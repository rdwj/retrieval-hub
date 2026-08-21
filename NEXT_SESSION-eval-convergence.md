# Next Session — eval-convergence

## Next: Make the Nomic switch official + chunk sweep (Phase 3, step 4)

The embedding comparison (Run 7) and reranking test (Run 8) are done.
Nomic v1.5 raw is Pareto-optimal. Two things remain to close out Phase 3:

1. **Update `ingest_va_cpg.py` to use Nomic v1.5**
   Change `EMBEDDING_MODEL`, `DOCUMENT_PREFIX`, `QUERY_PREFIX`, and
   `DESCRIPTION_LONG` in the base ingestion script. Re-ingest to create a
   clean `idx_va_cpg_v2` table as the production index. This makes the
   switch permanent and reproducible.

2. **Run chunk sweep with Nomic embeddings**
   The VA CPG chunk sweep (E3) was planned in the data-products epic but
   hasn't landed yet. Now that the embedding model is decided, run the
   sweep with Nomic: 256/0, 512/0 (current), 512/64, 1024/0. Use the
   `ingest_va_cpg_alt_embedding.py` script with different chunking params
   (needs `--chunk-tokens` and `--overlap-tokens` flags added).

3. **Score faithfulness for Nomic raw**
   Run 7 scored context_precision and answer_relevancy but not
   faithfulness. Fill this gap so the eval register has complete metrics
   for the winning configuration.

4. **Update docs**
   Add a note to `docs/onboarding-journey-va-cpg.md` step 3 that the
   embedding comparison (Run 7) superseded the PubMedBERT choice. Update
   the onboarding guides if needed after review.

**Session start protocol:**
- Premise checks (~5 min):
  - Databases up (`pg_isready -h localhost -p 5433` and `-p 5434`)
  - gpt-oss-120b reachable
  - Verify `idx_va_cpg_nomic_v1` table exists and is populated
- Rules with history:
  - gpt-oss-120b reasoning off via `enable_thinking=False` in `extra_body`
  - Ragas max_tokens=8192 to avoid faithfulness NaN
  - Per-condition checkpointing in scoring stage
  - Nomic v1.5 with batch_size=8 on MPS to avoid OOM
  - Nomic requires `search_query: ` / `search_document: ` prefixes
- Stop-and-ask before: modifying the eval register (append only);
  dropping existing index tables

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

### Phase 3: Retrieval configuration sweep — IN PROGRESS

Run the Tier 2 experiments from `EVAL_PLAN.md` systematically.

**Work:**
1. Chunk size and overlap sweep (256/0, 256/64, 512/64, 1024/128).
   **Note:** The VA CPG chunk sweep (E3) will be run as part of the
   data-products epic's next session (dual sweep: pubmed-hypertension +
   VA CPG). Results will be recorded here in the eval register and count
   toward this phase's definition of done. See
   `NEXT_SESSION-data-products.md` Phase 2 for the session plan.
2. ~~Embedding model comparison~~ — **DONE** (Runs 7-8, 2026-08-21). Nomic
   v1.5 dominates PubMedBERT and BioLORD-2023. Nomic raw (no reranking)
   is Pareto-optimal.
3. Record all results in the eval register with the full configuration
   fingerprint.
4. Identify the Pareto-optimal configuration.

**Definition of done:** Eval register has results for at least 4 chunk
configs and 2 embedding models. Best configuration identified and recorded
on the VA CPG data card.

**Status:** 2/2 embedding models tested (BioLORD-2023, Nomic v1.5). Chunk
sweep pending from data-products epic.

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

**Dependencies:** Phase 3 (need the converged results to publish).

**Parallel-ok:** The research (step 1-2) can run concurrently with Phase 3.
The submission (step 3-4) is sequential after Phase 3.

### Phase 5: Query set expansion and statistical rigor

Expand the eval query set from 30 to 100+ for statistical power, add
confidence intervals to all metrics.

**Work:**
1. Generate additional Q/A pairs from the VA CPG corpus (LLM-assisted,
   validated against source documents).
2. Stratify by clinical category (not just register) to surface
   per-condition performance.
3. Re-run the best configuration on the expanded set.
4. Add bootstrap confidence intervals to the eval output.

**Definition of done:** 100+ query eval set with per-category stratification
and confidence intervals on all metrics. Results recorded in the eval
register.

**Dependencies:** Phase 2 (EvalHub for running larger eval sets efficiently).

**Parallel-ok:** Yes -- the query set expansion (step 1-2) can happen
concurrently with Phase 3's config sweep.

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

## What landed last session (2026-08-21)

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
  on Apple Silicon. Use batch_size=8 for ingestion. At query time the
  adapter only embeds one query at a time so this doesn't affect retrieval.
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
