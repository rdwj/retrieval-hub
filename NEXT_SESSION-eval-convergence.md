# Next Session — eval-convergence

## Next: Phase 2 — EvalHub integration

Package the eval pipeline as an EvalHub task for automated sweeps on the
cluster. The 7.1-hour wall time for a single 107-query eval run makes local
iteration expensive; cluster-based parallelized scoring is the unlock for
both faster experimentation and reproducible automated sweeps.

1. **Define the eval task interface**
   Parameterized inputs: chunk_size, overlap, embedding_model, qa_dataset,
   rewriter_config, semantic_context, refine_strategy. The existing
   `eval_answer_quality.py` CLI flags already cover most of this.

2. **Package as an EvalHub-compatible task (container + config)**
   Build a container that runs `eval_answer_quality.py` with the parameterized
   inputs. Needs access to the catalog DB and vectors DB on the cluster, plus
   the gpt-oss-120b scoring LLM endpoint.

3. **Run a proof-of-concept sweep**
   The Tier 1 experiments from `eval/rewrite_lift/EVAL_PLAN.md` (expanded
   vocab mappings, register-aware rewriting). Use the v2 107-query dataset.

4. **Results flow back to the eval register**
   Sweep results should be importable into the eval register automatically,
   not via one-off import scripts.

**Session start protocol:**
- Premise checks (~5 min):
  - Databases up (`pg_isready -h 127.0.0.1 -p 5433` and `-p 5434`)
  - gpt-oss-120b reachable
  - Check if EvalHub infra exists or needs to be built
  - Read `eval/rewrite_lift/EVAL_PLAN.md` for the Tier 1 experiment list
- Rules with history:
  - gpt-oss-120b reasoning off via `enable_thinking=False` in `extra_body`
  - gpt-oss-120b has ~60s HAProxy idle timeout — use streaming for long requests
  - Ragas max_tokens=8192 to avoid faithfulness NaN
  - **Use 127.0.0.1 not localhost** for Postgres connections
  - Container builds need `--platform linux/amd64` and 644 file permissions
- Stop-and-ask before: modifying the eval register schema; modifying
  `eval_answer_quality.py` in ways that break existing run compatibility;
  deploying containers to the cluster

## Remaining epic phases

Converge on the best retrieval configuration for the VA CPG source through
systematic experimentation, then publish results on the data card and
position for industry leaderboards. The eval infrastructure built here
serves the whole platform — every source gets the same eval pipeline. This
epic also gates the refine tool epic's definition of done (A/B testing
refine requires this eval infrastructure).

### Phase 1: Full answer-quality eval pipeline — DONE

Built in session 2026-08-20 (morning). See Runs 1-5.

### Phase 3: Retrieval configuration sweep — DONE

Completed 2026-08-22. Full Ragas answer-quality evals on 3 chunk configs
(512/0, 512/64, 1024/0), 2 embedding models (PubMedBERT, Nomic v1.5).

**Winner:** 512/0 with Nomic v1.5 (no reranking). Pareto-optimal on
answer_relevancy (0.735) with competitive faithfulness (0.854). 1024/0
has higher faithfulness (0.882) but lower answer_relevancy (0.719).
512/64 is dominated on all Ragas metrics despite higher MRR.

### Phase 5: Query set expansion and statistical rigor — DONE

Completed 2026-08-22 (evening). Expanded eval from 50 (30 sampled) to 107
queries covering all 26 VA/DoD CPGs. Added bootstrap 95% CIs.

**v2 results (n=107, raw retrieval, 512/0 Nomic v1.5):**
- context_precision: 0.738 [0.682, 0.792]
- answer_relevancy: 0.723 [0.686, 0.759]
- faithfulness: 0.806 [0.752, 0.858]

Results recorded in eval register as suite `va-cpg-nomic-answer-quality-v2`.
Report: see `session-summaries/2026-08-22-eval-convergence-phase5-expanded-dataset.md`.

### Phase 2: EvalHub integration — NEXT

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

**Dependencies:** Phase 1 (done), Phase 5 (done). Results inform task config.

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

**Dependencies:** Phase 5 (done). Phase 2 (EvalHub for reproducible runs).

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

## What landed last session (2026-08-22, evening)

Phase 5 complete: expanded eval dataset and bootstrap CIs.

- Created `scripts/generate_qa_pairs.py` for LLM-assisted Q/A generation
  from VA CPG clinician summaries using gpt-oss-120b with streaming.
- Generated 57 new Q/A pairs across 19 CPGs, merged into `qa_dataset_v2.json`
  (107 questions total, covering all 26 CPGs).
- Added bootstrap 95% CIs, checkpoint resume, retry logic, and CLI flags
  to `eval_answer_quality.py`.
- Ran full eval on expanded set: ctx_prec 0.738, ans_rel 0.723, faith 0.806.
- Recorded results in eval register (suite `va-cpg-nomic-answer-quality-v2`).

See `session-summaries/2026-08-22-eval-convergence-phase5-expanded-dataset.md`.

## What landed earlier (2026-08-22, afternoon)

Phase 3 wrap-up: full Ragas answer-quality evals on chunk configs.
512/0 confirmed as winner. Pareto report at
`eval/reports/va-cpg-chunk-sweep-final.png`.

## Watch out for

- **gpt-oss-120b HAProxy timeout:** ~60s idle timeout on the OpenShift
  route. Use streaming for any request that might take longer. The
  generation script and eval pipeline already handle this.
- **Nomic batch_size on MPS:** use batch_size=8 for 512-token chunks,
  batch_size=2 for 1024-token chunks.
- **Faithfulness NaN rate:** 12% of queries (13/107) produced NaN
  faithfulness scores in the v2 run. Bootstrap CIs exclude NaN values.
  May need investigation if the rate increases.
- **Ragas "1 generation instead of 3" warnings:** consistent across all
  runs, unlikely to bias comparisons.
- gpt-oss-120b sandbox cluster may be reprovisioned. If the endpoint
  changes, update the eval scripts.

## If blocked

- If EvalHub isn't ready, run sweeps locally with a shell script wrapper
  around the eval script (slow but functional).
- If gpt-oss-120b becomes unreliable, consider a local scoring LLM
  (Ollama with a capable model).
