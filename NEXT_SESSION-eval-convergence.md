# Next Session — eval-convergence

## Next: Register-aware rewriting + hybrid scoring (E2 + E8)

Close the answer_relevancy gap from cross-encoder reranking. The cross-
encoder delivers +12.1% context_precision but costs -7.9% answer_relevancy.
Two interventions to test:

1. **Register-aware rewriting (E2)**
   Clinical queries already use correct terminology -- rewriting them adds
   noise. Detect clinical register (keyword overlap with vocabulary_mappings
   canonical terms) and skip rewriting for those queries. Apply cross-
   encoder reranking on the original query's results only.
   - Modify `scripts/eval_rerank_strategies.py` to add a `cross_encoder_register_aware` strategy
   - Use cached expanded retrieval data (no new retrieval needed)
   - Expected outcome: clinical answer_relevancy recovers toward 0.804
     (the cosine_dedup baseline) while cross-encoder precision holds

2. **Hybrid scoring (E8)**
   Blend cross-encoder score (precision) with cosine similarity score
   (answer-model affinity). Sweep alpha in [0.3, 0.5, 0.7]:
   `final_score = alpha * cross_encoder_score + (1-alpha) * cosine_score`
   - Add a `hybrid_alpha_N` strategy to the reranking script
   - No new retrieval or answer generation needed -- just re-score and
     re-rank the existing candidate pool
   - Expected outcome: find a blend that recovers most of the
     answer_relevancy while keeping most of the context_precision

3. **Run full eval on best configuration**
   Whichever of E2/E8 (or combination) produces the best trade-off, run
   the full 30-query eval with all 3 Ragas metrics and record in the
   eval register.

**Sequencing.** E2 and E8 are independent -- can test both and pick the
winner. Step 3 runs after the winner is identified.

**Constraints for the session:**
- Reuse cached retrieval data from `eval/rewrite_lift/runs/rerank-full-30/`
  where possible. No need to re-retrieve or re-call the rewriter.
- Same 30-query set, seed 42, for comparability with prior runs.
- gpt-oss-120b (reasoning off) for Ragas scoring, gpt-oss:20b for answer
  generation. Same models as Runs 3-5.

**Session start protocol:**
- Premise checks (~5 min):
  - Databases up (`pg_isready -h localhost -p 5433` and `-p 5434`)
  - gpt-oss-120b reachable
  - Cached data exists: `ls eval/rewrite_lift/runs/rerank-full-30/retrieval_expanded.json`
  - Parallel session changes merged: `git log --oneline -5` should show
    refine-tool commits from the parallel session
- Rules with history:
  - gpt-oss-120b reasoning off via `enable_thinking=False` in `extra_body`
  - Ragas max_tokens=8192 to avoid faithfulness NaN
  - Per-condition checkpointing in scoring stage
- Stop-and-ask before: modifying the eval register (append only); changing
  the retrieval pipeline or rewriter (those are separate epics)
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
2. Embedding model comparison (PubMedBERT vs. jina-embeddings-v3 vs.
   BioLORD or similar).
3. Record all results in the eval register with the full configuration
   fingerprint.
4. Identify the Pareto-optimal configuration.

**Definition of done:** Eval register has results for at least 4 chunk
configs and 2 embedding models. Best configuration identified and recorded
on the VA CPG data card.

**Dependencies:** Phase 2 (EvalHub infrastructure).

**Parallel-ok:** Yes -- can run concurrently with refine-tool epic phases.

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

## What landed last session (2026-08-20)

Phase 1 complete. Answer-quality eval pipeline built and used. Five eval
runs covering rewriting lift, Ragas answer quality, and reranking strategies.
Headline result: cross-encoder reranking +12.1% context_precision.

- Answer-quality eval pipeline (`scripts/eval_answer_quality.py`): three-
  stage caching (retrieve, generate, score), Ragas integration with
  gpt-oss-120b reasoning-off, per-condition checkpointing, parallel workers
- Reranking strategy comparison (`scripts/eval_rerank_strategies.py`): five
  strategies tested, cross-encoder wins on precision + faithfulness
- Eval register updated with Runs 3-5, eval plan revised with leaderboard
  analysis and arXiv outline
- Filed #28 (entity-arc retrieval), #29 (elicitation), #30 (auth), #31
  (MCP-level eval)
- README positioning sharpened

**Commits:** `0aea548`..`3bcecf8`

See `session-summaries/2026-08-20-eval-convergence-reranking.md`.

## Watch out for

- Ragas API instability across versions. Pin the version and verify the
  API before building on it.
- gpt-oss-120b sandbox cluster may be reprovisioned. If the endpoint
  changes, update the eval scripts.
- EvalHub integration details are TBD -- may need to adapt the packaging
  to whatever EvalHub's task interface looks like.

## If blocked

- If Ragas still doesn't work with any available LLM, fall back to a
  custom LLM-as-judge implementation (simpler prompting, no instructor
  dependency).
- If EvalHub isn't ready, run sweeps locally with a shell script wrapper
  around the eval script.
