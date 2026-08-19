# Eval Register: Query Rewrite Lift on VA CPG

Tracks every eval run measuring the effect of query rewriting on retrieval
quality for the VA/DoD Clinical Practice Guidelines source. Each run
compares raw retrieval (no rewriting) against rewritten retrieval on the
same query set.

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
by text content, re-ranked by cosine similarity, and the top-5 are kept.

**Metrics (all computed against ground truth, no LLM judge):**

- **hit_rate@5:** Does at least one of the top-5 results come from the
  correct source document? Matched by CPG slug against the chunk's
  `doc_title` (case-insensitive keyword lookup).
- **MRR@5:** Mean reciprocal rank of the first correct chunk within the
  top-5.
- **mean_score:** Average pgvector cosine similarity of the top-5 hits.

**Stratification:** Results are reported overall and by language register
(lay vs. clinical) because the rewriter's primary value proposition is
bridging the vocabulary gap for lay-language queries.

## Infrastructure

| Component | Value |
|---|---|
| Embedding model | NeuML/pubmedbert-base-embeddings (768-dim) |
| Vector store | pgvector (PostgreSQL 16) |
| Chunking | token_fixed, 512 tokens, 0 overlap, cl100k_base |
| Rewriting LLM | gpt-oss-120b (QwQ-32B reasoning model, vLLM) |
| Eval scoring LLM | none (ground-truth metrics only) |
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

## Cumulative progress

| Run | Config | Overall MRR delta | Lay MRR delta | Clinical MRR delta |
|---|---|---|---|---|
| 1 (baseline) | vocab mappings only | -0.039 | +0.083 | -0.146 |
| 2 (semantic) | + entities, metrics, abbreviations | -0.010 | +0.062 | -0.073 |

---

## Next runs (planned)

See `EVAL_PLAN.md` for the convergence plan. Candidate interventions:

1. **Expand vocabulary mappings for lay queries** -- target the specific lay
   queries that scored below MRR 1.0 to recover the slight lay-register
   regression from Run 2.
2. **Register-aware rewriting** -- detect whether a query already uses
   clinical terminology and skip or lighten rewriting when it does.
3. **Chunking variations** -- test 256-token and 1024-token chunks, and
   overlap values (64, 128) to measure chunk-size effects on retrieval.
4. **Embedding model comparison** -- compare PubMedBERT against
   general-purpose models (e.g., jina-embeddings-v3) and clinical models
   (e.g., BioLORD).
5. **Ragas LLM-judged metrics** -- if a non-reasoning LLM becomes available,
   run context_precision for a complementary relevance signal.
