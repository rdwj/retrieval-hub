# Session Summary: Embedding Model Comparison + Reranking (E4, E8)

**Date:** 2026-08-21
**Epic:** eval-convergence (Phase 3, steps 2-3)

## What happened

Compared three embedding models for the VA CPG clinical guidelines source:
PubMedBERT (current baseline), BioLORD-2023 (biomedical domain), and
nomic-embed-text-v1.5 (general-purpose, platform default). Then tested
hybrid_0.3 reranking on top of Nomic embeddings to see if gains stack.

## Key results

### Run 7: Embedding model comparison (no reranking)

| Model (raw) | ctx_precision | ans_relevancy | hit_rate |
|---|---|---|---|
| PubMedBERT | 0.809 | 0.646 | 29/30 |
| BioLORD-2023 | 0.511 | 0.655 | 30/30 |
| **Nomic v1.5** | **0.822** | **0.740** | **30/30** |

### Run 8: Nomic v1.5 + reranking

| Config | ctx_precision | ans_relevancy | faithfulness | MRR |
|---|---|---|---|---|
| Nomic raw (Run 7) | 0.822 | **0.740** | -- | -- |
| Nomic + cosine_dedup | 0.794 | 0.710 | 0.830 | 0.928 |
| Nomic + hybrid_0.3 | **0.839** | 0.688 | 0.845 | 0.944 |
| PubMedBERT + hybrid_0.3 (Run 6) | 0.817 | 0.729 | 0.881 | 0.961 |

**Nomic raw is Pareto-optimal.** It beats every PubMedBERT configuration on
both context_precision and answer_relevancy. Adding hybrid_0.3 reranking
pushes ctx_precision higher (+1.7pts) but costs -5.2pts answer_relevancy.

## What shipped

- `scripts/ingest_va_cpg_alt_embedding.py` — parameterized re-ingestion
- `--prior-retrieval` flag added to `eval_rerank_strategies.py`
- pgvector tables: `idx_va_cpg_biolord_v1`, `idx_va_cpg_nomic_v1`
- Eval run data: `runs/embed-biolord/`, `runs/embed-nomic/`,
  `runs/embed-nomic-rerank/`
- Updated `EVAL_REGISTER.md` with Runs 7-8, cumulative progress revised
- Updated `NEXT_SESSION-eval-convergence.md`
- PubMedBERT restored as active index (pending decision to switch)

## Surprising findings

1. A general-purpose embedding model (Nomic v1.5) outperformed a
   domain-specific biomedical model (PubMedBERT) on a clinical corpus.

2. Nomic raw (no rewriting, no reranking) beats PubMedBERT + rewriting +
   hybrid_0.3 reranking. The simpler configuration wins.

3. BioLORD-2023 ranks chunks poorly despite perfect hit_rate. Domain-
   specific training does not guarantee domain-specific retrieval quality.

4. Rewriting and reranking add less value with better base embeddings,
   suggesting these techniques partially compensate for embedding weakness.

## Decision: switch to Nomic v1.5

Recommendation: switch the VA CPG source to Nomic v1.5 without hybrid
reranking. The raw Nomic config is both simpler and higher-quality.
