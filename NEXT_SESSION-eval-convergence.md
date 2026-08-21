# Next Session — eval-convergence

## Next: Embedding model comparison (Phase 3, step 2)

Compare the current PubMedBERT embeddings against at least one alternative
model on the full 30-query eval with hybrid_alpha_03 reranking. The goal is
to determine whether a different embedding model shifts the Pareto frontier
(better precision-relevancy trade-off) or whether PubMedBERT is already
near-optimal for clinical retrieval.

1. **Select candidate models**
   The eval plan names jina-embeddings-v3 and BioLORD-2023. Before
   committing to a long re-ingestion, verify each candidate is
   sentence-transformers compatible and fits in local memory. Check
   dimensionality (current index is 768-dim PubMedBERT); a different
   dimension means a separate pgvector index table.
   - jina-embeddings-v3: general-purpose, 1024-dim, good MTEB scores
   - BioLORD-2023: biomedical domain, 768-dim, trained on PubMed+MIMIC
   - If neither loads locally, fall back to nomic-embed-text-v1.5
     (the platform default, 768-dim) as the general-purpose baseline

2. **Re-ingest VA CPG corpus with each candidate**
   Create a new pgvector index per model (e.g., `idx_va_cpg_jina_v1`).
   Use the same chunking config (512 tokens, 0 overlap) to isolate the
   embedding variable. The ingestion pipeline already accepts a
   `model_name` parameter via `EmbeddingService`.
   - Register a new Source variant or use a temporary index table
   - Re-embed all 6,500 chunks (~10 min per model locally)

3. **Run the eval pipeline against each index**
   For each model: retrieve top-5, apply rewriting + hybrid_alpha_03
   reranking, generate answers (gpt-oss:20b), score with Ragas
   (gpt-oss-120b reasoning-off). Same 30-query set, seed 42.
   - New run directory per model under `eval/rewrite_lift/runs/`
   - Record as Run 7 (or 7a/7b) in the eval register

4. **Compare and record results**
   Build a comparison table: PubMedBERT vs candidate(s) across all
   metrics. If a candidate wins on the trade-off, it becomes the new
   recommended embedding model for the VA CPG data card.

**Sequencing.** Steps 1-2 are prerequisites. Step 3 can reuse the existing
eval scripts with a different `--vectors-db-url` or index table override.
Step 4 is analysis after the runs complete.

**Constraints for the session:**
- Same 30-query set, seed 42, same rewriter config, same answer/scoring
  LLMs as Runs 3-6. Only the embedding model changes.
- Same chunking (512/0) to isolate the embedding variable.
- gpt-oss-120b (reasoning off) for Ragas scoring. Check reachability
  before starting the long scoring runs.
- Do NOT modify the existing `idx_va_cpg_v1` index. Create new tables.

**Session start protocol:**
- Premise checks (~5 min):
  - Databases up (`pg_isready -h localhost -p 5433` and `-p 5434`)
  - gpt-oss-120b reachable
  - Check whether E3 (chunk sweep) has landed from data-products:
    `git log --oneline -10` and `ls eval/rewrite_lift/runs/` for new
    chunk-sweep directories
  - Verify candidate models download: quick
    `SentenceTransformer("jinaai/jina-embeddings-v3")` smoke test
- Rules with history:
  - gpt-oss-120b reasoning off via `enable_thinking=False` in `extra_body`
  - Ragas max_tokens=8192 to avoid faithfulness NaN
  - Per-condition checkpointing in scoring stage
  - Hybrid reranking uses `hybrid_alpha_03` (alpha=0.3) as established
    in Run 6
- Stop-and-ask before: modifying the eval register (append only);
  dropping or altering existing index tables; changing the retrieval
  pipeline or rewriter (those are separate epics)
- Close ritual: session summary, eval register update, commit + push

## Remaining epic phases

Converge on the best retrieval configuration for the VA CPG source through
systematic experimentation, then publish results on the data card and
position for industry leaderboards. The eval infrastructure built here
serves the whole platform -- every source gets the same eval pipeline. This
epic also gates the refine tool epic's definition of done (A/B testing
refine requires this eval infrastructure).

### Phase 1: Full answer-quality eval pipeline

Build the end-to-end eval that measures answer quality, not just retrieval
hit_rate. The current eval (`scripts/eval_rewrite_lift.py`) measures
whether we find the right document; this phase measures whether the
retrieved context produces a correct, complete answer.

**Work:**
1. Deploy a non-reasoning LLM on the cluster (Llama 3.1 70B or similar)
   that works with Ragas' instructor integration, or find a Ragas
   configuration that works with reasoning models.
2. Add answer generation to the eval pipeline: for each query, generate an
   answer from the retrieved context using gpt-oss-120b, then score with
   Ragas metrics (context_precision, answer_relevancy, faithfulness).
3. Extend `eval_rewrite_lift.py` (or write a new script) to run both
   retrieval-only and end-to-end answer-quality evals.
4. Run the full eval on the current best config (semantic layer + rewriter)
   and record results in the eval register.

**Definition of done:** Ragas answer_relevancy and context_precision scores
recorded in the eval register for the VA CPG source, alongside the existing
retrieval metrics.

**Dependencies:** None.

**Parallel-ok:** Yes -- independent of the refine-tool epic. The refine
epic will consume this infrastructure but doesn't need to be sequenced
after it.

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

### Phase 3: Retrieval configuration sweep

Run the Tier 2 experiments from `EVAL_PLAN.md` systematically via EvalHub.

**Work:**
1. Chunk size and overlap sweep (256/0, 256/64, 512/64, 1024/128).
   **Note:** The VA CPG chunk sweep (E3) will be run as part of the
   data-products epic's next session (dual sweep: pubmed-hypertension +
   VA CPG). Results will be recorded here in the eval register and count
   toward this phase's definition of done. See
   `NEXT_SESSION-data-products.md` Phase 2 for the session plan.
2. Embedding model comparison (PubMedBERT vs. jina-embeddings-v3 vs.
   BioLORD or similar).
3. Record all results in the eval register with the full configuration
   fingerprint.
4. Identify the Pareto-optimal configuration.

**Definition of done:** Eval register has results for at least 4 chunk
configs and 2 embedding models. Best configuration identified and recorded
on the VA CPG data card.

**Dependencies:** Phase 2 (EvalHub infrastructure) for embedding model
comparison. The chunk sweep (E3) can run without EvalHub -- the
data-products session will run it locally.

**Parallel-ok:** Yes -- chunk sweep runs via data-products epic. Embedding
comparison can run concurrently with refine-tool epic phases.

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

## What landed last session (2026-08-20, evening)

Hybrid scoring (E8) resolved the answer_relevancy trade-off from cross-
encoder reranking. hybrid_alpha_03 (30% cross-encoder, 70% cosine) is the
new best overall configuration: 0.817 context_precision, 0.729
answer_relevancy, 0.881 faithfulness, 0.961 MRR. Register-aware rewriting
(E2) was also tested but hybrid scoring dominated.

- Added 4 new reranking strategies to `scripts/eval_rerank_strategies.py`:
  `cross_encoder_register_aware`, `hybrid_alpha_03/05/07`
- Full 30-query Ragas eval (Run 6) with all 6 strategies
- Eval register updated with Run 6, cumulative progress table revised

**Commits:** `2b1a453`..`a3c22ea`

See `session-summaries/2026-08-20-eval-convergence-hybrid-scoring.md`.

**Prior session (2026-08-20, morning):** Phase 1 complete. Answer-quality
eval pipeline built. Five eval runs (Runs 1-5). Cross-encoder reranking
+12.1% context_precision. See `session-summaries/2026-08-20-eval-convergence-reranking.md`.

## Watch out for

- **Cross-epic coordination:** The VA CPG chunk sweep (E3) is being run
  in the data-products epic's next session alongside the pubmed-hypertension
  sweep. Check whether it has landed before starting this session.
- **Embedding dimension mismatch:** jina-embeddings-v3 is 1024-dim vs
  PubMedBERT's 768-dim. The pgvector index table dimensions must match
  the model. Create separate index tables per model.
- **Model download sizes:** jina-embeddings-v3 is ~2.5GB. Ensure disk
  space in `.model_cache/` before starting re-ingestion.
- Ragas API instability across versions. Pin the version and verify the
  API before building on it.
- gpt-oss-120b sandbox cluster may be reprovisioned. If the endpoint
  changes, update the eval scripts.
- **Ragas "1 generation instead of 3" warnings** appeared consistently
  in Run 6. May affect answer_relevancy scores. Monitor for consistency
  across embedding model runs.

## If blocked

- If Ragas still doesn't work with any available LLM, fall back to a
  custom LLM-as-judge implementation (simpler prompting, no instructor
  dependency).
- If EvalHub isn't ready, run sweeps locally with a shell script wrapper
  around the eval script.
