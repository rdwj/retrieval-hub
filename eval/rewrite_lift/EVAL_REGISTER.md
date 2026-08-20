# Eval Register: Retrieval Quality on VA CPG

Tracks every eval run measuring retrieval and answer quality for the
VA/DoD Clinical Practice Guidelines source. Runs compare configurations
(rewriting, semantic layer, reranking strategies) against baselines.

## Methodology

**Query set:** 30 queries drawn from `eval/autorag/qa_dataset_draft.json`
(14 lay-register, 16 clinical-register, fixed seed 42). Lay-register
queries use everyday language ("high blood pressure"); clinical-register
queries use professional terminology ("first-line pharmacologic options for
treating hypertension").

**Retrieval pipeline:** `retrieval_hub.retrieval.api.query()` against the
VA CPG pgvector index (6,500 chunks, PubMedBERT 768-dim embeddings,
512-token chunks, no overlap). Top-5 results per query.

**Rewriting pipeline:** `RewriterService.rewrite()` produces up to 5
rewritten queries per input via the gpt-oss-120b reasoning model. Each
rewrite is run through the same retrieval pipeline; results are deduplicated
by text content, re-ranked by cosine similarity, and the top-5 are kept
(unless a different reranking strategy is specified).

**Metrics:**

*Ground-truth (no LLM judge):*
- **hit_rate@5:** Does at least one top-5 result come from the correct
  source document?
- **MRR@5:** Mean reciprocal rank of the first correct chunk.
- **mean_score:** Average pgvector cosine similarity of the top-5 hits.

*LLM-judged (Ragas 0.4.3, added Run 3+):*
- **context_precision:** Are the retrieved chunks relevant to answering the
  question given the reference answer? (Ragas `ContextPrecision`)
- **answer_relevancy:** Is the generated answer relevant to the question?
  (Ragas `AnswerRelevancy`)
- **faithfulness:** Is the generated answer grounded in the retrieved
  context? (Ragas `Faithfulness`)

**Stratification:** Results are reported overall and by language register
(lay vs. clinical).

## Infrastructure

| Component | Value |
|---|---|
| Embedding model | NeuML/pubmedbert-base-embeddings (768-dim) |
| Vector store | pgvector (PostgreSQL 16) |
| Chunking | token_fixed, 512 tokens, 0 overlap, cl100k_base |
| Rewriting LLM | gpt-oss-120b (QwQ-32B reasoning model, vLLM) |
| Answer generation LLM | gpt-oss:20b (local Ollama, added Run 3+) |
| Eval scoring LLM | gpt-oss-120b reasoning-off (added Run 3+) |
| Cross-encoder reranker | ms-marco-MiniLM-L-6-v2 (added Run 5+) |
| Corpus | 52 VA/DoD CPG documents, 5 clinical categories |

---

## Run 1: Baseline (vocabulary mappings only)

**Date:** 2026-08-19
**Commit:** `865d689`
**Rewriter config:** 49 vocabulary mappings, 8 sample query examples,
domain notes. No semantic layer.
**Raw data:** `results_baseline.csv`, `summary_baseline.json`

### Results

| | hit_rate@5 | | | MRR@5 | | | mean_score | | |
|---|---|---|---|---|---|---|---|---|---|
| **Cohort** | **Raw** | **Rewrite** | **Delta** | **Raw** | **Rewrite** | **Delta** | **Raw** | **Rewrite** | **Delta** |
| Overall (n=30) | 0.967 | 1.000 | +0.033 | 0.944 | 0.906 | -0.039 | 0.597 | 0.699 | +0.102 |
| Lay (n=14) | 0.929 | 1.000 | +0.071 | 0.881 | 0.964 | +0.083 | 0.572 | 0.689 | +0.117 |
| Clinical (n=16) | 1.000 | 1.000 | +0.000 | 1.000 | 0.854 | -0.146 | 0.619 | 0.708 | +0.089 |

**Queries that changed:** q024 (lay, MDD) flipped from miss to hit.

### Observations

- Lay-register queries benefit across all three metrics. The rewriter's
  vocabulary mappings successfully translate lay terminology into clinical
  terms that PubMedBERT embeddings match better.
- Clinical-register MRR degraded significantly (-14.6%). When the query
  already uses correct clinical terminology, rewrites add breadth at the
  cost of precision, pushing less-specific chunks into the top-5.
- Mean score improved for both registers, indicating the rewriter
  consistently finds chunks with higher semantic similarity even when
  ranking accuracy drops.

---

## Run 2: With semantic layer

**Date:** 2026-08-19
**Commit:** `8eeeacd`
**Rewriter config:** Same 49 vocabulary mappings and 8 sample queries as
Run 1, plus semantic context: 25 entity definitions, 15 relationship hints,
12 metric definitions, 39 abbreviation expansions, domain context string.
Prompt template v2.
**Raw data:** `results_with_semantic.csv`, `summary_with_semantic.json`

### Results

| | hit_rate@5 | | | MRR@5 | | | mean_score | | |
|---|---|---|---|---|---|---|---|---|---|
| **Cohort** | **Raw** | **Rewrite** | **Delta** | **Raw** | **Rewrite** | **Delta** | **Raw** | **Rewrite** | **Delta** |
| Overall (n=30) | 0.967 | 1.000 | +0.033 | 0.944 | 0.934 | -0.010 | 0.597 | 0.704 | +0.107 |
| Lay (n=14) | 0.929 | 1.000 | +0.071 | 0.881 | 0.943 | +0.062 | 0.572 | 0.680 | +0.108 |
| Clinical (n=16) | 1.000 | 1.000 | +0.000 | 1.000 | 0.927 | -0.073 | 0.619 | 0.724 | +0.106 |

**Queries that changed:** Same as Run 1 (q024 flipped from miss to hit).

### Observations

- The semantic layer's primary effect was on clinical-register MRR: the
  degradation dropped from -14.6% to -7.3% (cut in half). Entity
  definitions and abbreviation tables gave the rewriter more precise
  terminology to work with, reducing noisy expansions on clinical queries.
- Overall MRR delta improved from -0.039 to -0.010, nearly eliminating the
  ranking penalty of rewriting.
- Lay-register MRR dropped slightly from +8.3% to +6.2%. The additional
  prompt context (entities, abbreviations, metrics) may have slightly
  diluted the rewriter's focus on vocabulary mapping, which is the primary
  mechanism for lay queries.
- Mean score improved marginally across both registers compared to baseline.

### Delta vs. Run 1 (improvement from semantic layer)

| Cohort | MRR delta improvement | mean_score delta improvement |
|---|---|---|
| Overall | +0.029 (from -0.039 to -0.010) | +0.005 |
| Lay | -0.021 (from +0.083 to +0.062) | -0.009 |
| Clinical | +0.073 (from -0.146 to -0.073) | +0.017 |

---

## Run 3: Answer-quality baseline (Ragas metrics)

**Date:** 2026-08-20
**Commit:** `0aea548`
**Config:** Same as Run 2 (semantic layer + rewriter). First run with
Ragas LLM-judged metrics. Answer generation by gpt-oss:20b (local Ollama),
scoring by gpt-oss-120b (reasoning off, max_tokens=8192).
**Raw data:** `runs/9084a31205273246/`

### Results

| | context_precision | | | answer_relevancy | | |
|---|---|---|---|---|---|---|
| **Cohort** | **Raw** | **Rewrite** | **Delta** | **Raw** | **Rewrite** | **Delta** |
| Overall (n=30) | 0.809 | 0.740 | -0.068 | 0.646 | 0.700 | +0.054 |
| Lay (n=14) | 0.821 | 0.804 | -0.017 | 0.634 | 0.629 | -0.005 |
| Clinical (n=16) | 0.798 | 0.684 | -0.114 | 0.657 | 0.763 | +0.106 |

### Observations

- Rewriting improves answer relevancy (+5.4% overall, +10.6% clinical) but
  reduces context precision (-6.8% overall, -11.4% clinical). This confirmed
  the trade-off seen in Runs 1-2: rewrites find better answers but rank
  chunks by rewrite similarity rather than original-query relevance.
- This trade-off motivated the reranking strategy experiments in Runs 4-5.

---

## Run 4: Reranking strategy comparison (10-query subset)

**Date:** 2026-08-20
**Commit:** `0877b37`
**Config:** Same retrieval config as Run 2. Five reranking strategies
compared on a 10-query subset. All three Ragas metrics.
**Raw data:** `runs/rerank-subset-10/`

### Results (overall, n=10)

| Metric | cosine_dedup | rrf | cross_encoder | cosine_original | llm_rerank |
|---|---|---|---|---|---|
| context_precision | 0.758 | 0.742 | **0.849** | 0.773 | 0.754 |
| answer_relevancy | **0.720** | 0.654 | 0.721 | 0.584 | 0.612 |
| faithfulness | 0.862 | 0.697 | **0.863** | 0.760 | 0.786 |
| hit_rate | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| MRR | 0.883 | **1.000** | 0.883 | **1.000** | **1.000** |

### Observations

- Cross-encoder dominated context_precision and faithfulness while matching
  the baseline on answer_relevancy. Selected for full-run validation.
- RRF had perfect MRR but worst faithfulness -- finds the right document
  but answer grounding suffers.
- Cosine-on-original and LLM rerank underperformed the simple cosine_dedup
  baseline on most metrics.

---

## Run 5: Cross-encoder vs. baseline (full 30-query run)

**Date:** 2026-08-20
**Commit:** `0877b37`
**Config:** Same retrieval config as Run 2. Cross-encoder reranking
(ms-marco-MiniLM-L-6-v2) against the original query, compared to
cosine_dedup baseline. All three Ragas metrics.
**Raw data:** `runs/rerank-full-30/`

### Results

| Metric | cosine_dedup | cross_encoder | Delta |
|---|---|---|---|
| context_precision | 0.738 | **0.859** | **+0.121** |
| answer_relevancy | **0.734** | 0.655 | -0.079 |
| faithfulness | 0.838 | 0.837 | ~0 |
| hit_rate | 1.000 | 1.000 | 0 |
| MRR | 0.903 | 0.906 | +0.003 |

### By register

| Metric | cosine_dedup (clinical) | cross_encoder (clinical) | Delta |
|---|---|---|---|
| context_precision | 0.707 | **0.869** | **+0.162** |
| answer_relevancy | **0.804** | 0.714 | -0.090 |
| MRR | 0.849 | **0.885** | +0.036 |

| Metric | cosine_dedup (lay) | cross_encoder (lay) | Delta |
|---|---|---|---|
| context_precision | 0.774 | **0.848** | **+0.074** |
| answer_relevancy | **0.653** | 0.587 | -0.067 |
| MRR | **0.964** | 0.929 | -0.036 |

### Observations

- Cross-encoder delivers +12.1% context_precision (+16.2% clinical) with
  equivalent faithfulness. The reranking against the original query recovers
  the precision lost by rewrite-based ranking.
- Answer relevancy drops -7.9%. The answer model (gpt-oss:20b) produces
  slightly less relevant answers from cross-encoder-ranked chunks. This may
  improve with a better answer model or prompt tuning.
- Faithfulness is essentially tied (0.838 vs 0.837), confirming that
  cross-encoder's different chunk selection doesn't harm answer grounding.
- Lay-register faithfulness was NaN for both strategies (Ragas issue with
  shorter lay answers).

---

## Cumulative progress

| Run | Config | Overall ctx_prec | Overall ans_rel | Overall faith | Overall MRR |
|---|---|---|---|---|---|
| 1 | vocab mappings, cosine dedup | -- | -- | -- | 0.906 (rewrite) |
| 2 | + semantic layer, cosine dedup | -- | -- | -- | 0.934 (rewrite) |
| 3 | Run 2 config, Ragas scoring | 0.740 | 0.700 | -- | -- |
| 5 | Run 2 + cross-encoder rerank | **0.859** | 0.655 | 0.837 | 0.906 |

The cross-encoder reranking is the single largest improvement to
context_precision (+12.1%), recovering the precision cost of query
rewriting while maintaining faithfulness. The trade-off is a -7.9% drop
in answer_relevancy, likely addressable through answer model or prompt
improvements.

---

## Next runs (planned)

See `EVAL_PLAN.md` for the convergence plan. Priorities given current
results:

1. **Answer model / prompt tuning** -- investigate why cross-encoder-ranked
   chunks produce lower answer_relevancy. The chunks are more precisely
   relevant (higher context_precision), so the answer model should be able
   to produce better answers from them.
2. **Expand vocabulary mappings for lay queries** -- target lay queries that
   scored below MRR 1.0.
3. **Chunking variations** -- test 256-token and 1024-token chunks.
4. **Embedding model comparison** -- PubMedBERT vs. general-purpose models.
5. **MCP-level eval** -- run the same eval through the MCP tools to measure
   end-to-end system performance (#31).
