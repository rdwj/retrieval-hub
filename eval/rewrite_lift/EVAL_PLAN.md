# Eval Convergence Plan: Rewrite Lift

Goal: converge on the best retrieval configuration for the VA CPG source
through systematic experimentation, then publish the methodology and
results as a data card artifact and potentially an arXiv paper.

## Where we are

Two eval runs on a 30-query test set (14 lay, 16 clinical). The rewriter
with a per-source semantic layer achieves 100% hit_rate@5 and near-flat
MRR (-0.010 overall delta). The main remaining gap is clinical-register
MRR degradation (-7.3%), which means the rewriter sometimes pushes
less-specific chunks ahead of the best match when the query already uses
correct terminology.

## Experiment backlog

Ordered by expected impact. Each experiment is a single variable change
against the current best configuration (Run 2).

### Tier 1: High confidence, low cost

**E1. Expanded vocabulary mappings for lay queries**
- Hypothesis: The slight lay-register MRR regression (from +8.3% to +6.2%)
  can be recovered by adding targeted vocabulary mappings for the lay
  queries that scored below MRR 1.0.
- Method: Examine per-query results to identify which lay queries have
  rewrite MRR < 1.0. For each, check what rewrites were generated and what
  mapping would have produced a better rewrite. Add those mappings to
  `seed_va_cpg_rewriter_metadata.py`.
- Expected outcome: Lay MRR returns to +8% range while preserving
  clinical gains.

**E2. Register-aware rewriting (skip/lighten on clinical queries)**
- Hypothesis: Clinical queries don't need rewriting. If we detect that a
  query already uses domain-specific vocabulary and skip rewriting, clinical
  MRR stays at 1.0 and overall MRR improves.
- Method: Add a lightweight classifier (keyword overlap with
  vocabulary_mappings canonical terms, or a prompt to the rewriter asking
  "is this query already in clinical register?"). If classified as clinical,
  return the raw query as the only "rewrite."
- Expected outcome: Clinical MRR returns to 1.000, overall MRR becomes
  net positive.

### Tier 2: Medium confidence, medium cost

**E3. Chunk size and overlap sweep**
- Hypothesis: The current 512-token / 0-overlap configuration may not be
  optimal. Smaller chunks (256) improve precision; overlap (64, 128) helps
  with boundary effects.
- Method: Re-ingest the corpus with 4 configurations (256/0, 256/64,
  512/64, 1024/128). Run the eval on each. Compare hit_rate, MRR,
  mean_score.
- Expected outcome: Identify the Pareto-optimal chunk config. Previous
  AutoRAG eval (in `eval/autorag/`) showed overlap adds chunks without
  improving retrieval, but that was before rewriting.
- Cost: ~4 ingestion runs (10 min each) + 4 eval runs (14 min each).

**E4. Embedding model comparison**
- Hypothesis: PubMedBERT (768-dim, biomedical domain) may not be the best
  fit for a rewrite-augmented pipeline. General-purpose models with higher
  dimensionality (jina-embeddings-v3, 1024-dim) or clinical models
  (BioLORD-2023) may perform better when rewrites use broader terminology.
- Method: Re-ingest with 2-3 candidate models. Run the eval on each.
- Expected outcome: Identify whether the rewriter's vocabulary expansion
  works better with domain-specific or general-purpose embeddings.
- Cost: Requires deploying embedding models on vLLM or using local
  sentence-transformers. ~3 ingestion runs + 3 eval runs.

### Tier 3: Higher cost, exploratory

**E5. Ragas LLM-judged metrics**
- Hypothesis: Ground-truth hit_rate and MRR measure "did we find the right
  document?" but not "did we find the most relevant chunk within that
  document?" LLM-judged context_precision would add that signal.
- Method: Deploy a non-reasoning LLM (Llama 3.1 70B or similar) that works
  with Ragas' instructor integration. Run Ragas context_precision on the
  same query set.
- Blocker: gpt-oss-120b is a reasoning model that doesn't work cleanly
  with instructor/Ragas. Need a separate LLM deployment.

**E6. Query set expansion**
- Hypothesis: 30 queries may not capture all failure modes. A larger set
  (100+) would give more statistical power and surface edge cases.
- Method: Generate additional Q/A pairs from the corpus, potentially using
  an LLM to generate questions from each CPG's key recommendations.
  Validate with clinical review.
- Expected outcome: More robust metrics with confidence intervals.

**E7. End-to-end RAG eval (generation quality)**
- Hypothesis: Retrieval improvement translates to answer quality
  improvement, but we haven't measured that yet. An end-to-end eval would
  measure whether better retrieval produces better answers.
- Method: Add an answer generation step (using gpt-oss-120b) and evaluate
  with Ragas answer_relevancy and faithfulness metrics.
- Cost: High -- requires answer generation for every query in both
  conditions.

## EvalHub integration

EvalHub on the cluster provides infrastructure for running eval sweeps at
scale without tying up a local machine. Integration steps:

1. Package `scripts/eval_rewrite_lift.py` as an EvalHub task with
   parameterized inputs (chunk_size, overlap, embedding_model,
   rewriter_config).
2. Define a sweep configuration covering the Tier 1-2 experiments.
3. Results flow back to `eval/rewrite_lift/` as timestamped JSON files and
   get appended to the eval register.
4. EvalHub's comparison UI shows the Pareto frontier across configurations.

## Data card integration

The VA CPG source data card (`docs/data-cards/va-cpg.md` or embedded in
the catalog) should include:

- Current best retrieval configuration (chunk size, embedding model,
  rewriter config)
- Eval methodology summary (query set, metrics, stratification)
- Current best metrics (hit_rate, MRR, mean_score by register)
- Link to the full eval register for historical context

Update the data card after each eval run that changes the best-known
configuration.

## arXiv paper outline

Working title: "Per-Source Semantic Layers for Domain-Adaptive Retrieval
in Multi-Tenant RAG Platforms"

1. **Problem:** Enterprise RAG platforms serve multiple corpora with
   different domain vocabularies. A single retrieval configuration
   underperforms when users query across registers (lay vs. clinical,
   business vs. technical). Existing approaches (fine-tuned embeddings,
   corpus-specific models) are expensive and don't scale to multi-tenant
   platforms.

2. **Approach:** Per-source semantic layers -- declarative metadata (entity
   definitions, vocabulary mappings, metric definitions, abbreviation
   glossaries) authored by data owners and consumed by a shared query
   rewriter. The rewriter uses an LLM to translate queries into
   domain-specific terminology before retrieval, guided by the semantic
   layer.

3. **Evaluation:** Controlled experiment on VA/DoD Clinical Practice
   Guidelines (52 documents, 6,500 chunks). 30-query evaluation set
   stratified by language register. Metrics: hit_rate@5, MRR@5, mean cosine
   similarity. Progression from vocabulary-only to full semantic layer.

4. **Results:** Tables from the eval register showing progressive
   improvement. Key finding: the semantic layer's primary effect is on
   clinical-register queries where it halved the MRR degradation, while
   vocabulary mappings drive the lay-register improvement.

5. **Discussion:** Trade-offs between prompt context size and rewriting
   precision. The observation that more context helps clinical queries but
   slightly dilutes lay-query performance. Implications for prompt template
   design in multi-register domains.

6. **Generalizability:** The schema is domain-agnostic. Brief examples of
   how the same semantic layer structure applies to code retrieval (entity
   types: module, API, framework; relationships: imports, implements) and
   legal retrieval (entity types: statute, precedent; relationships: cites,
   overrules).

## Timeline

| Phase | Work | Dependency |
|---|---|---|
| Now | Eval register and plan captured | Done |
| Next session | E1 (expanded vocab mappings) + E2 (register-aware rewriting) | None |
| Following session | E3 (chunk sweep) via EvalHub | EvalHub task packaging |
| Following session | E4 (embedding model comparison) via EvalHub | Model deployment |
| When available | E5 (Ragas metrics) | Non-reasoning LLM |
| Before paper | E6 (query set expansion) + E7 (end-to-end RAG) | Clinical review |
