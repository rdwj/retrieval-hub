# Chunking Parameter Sweep: PubMed Hypertension Literature

## Experiment metadata

- **Date:** 2026-08-20
- **Commit:** f6bc7c4 (sweep script), results generated same session
- **Operator:** Wes Jackson
- **Epic:** data-products Phase 2

## Corpus summary

10 open-access PubMed Central review articles on hypertension management.
4 categories: management-guidelines (3 articles), pharmacotherapy (2),
lifestyle-and-adherence (3), comorbidities (2).

Articles span 2023-2025 literature. Source format: BioC JSON from NCBI
BioC API, preserving section types, passage boundaries, and citation
metadata. Baseline ingestion: 233 chunks at 512 tokens, 0 overlap,
section boundaries respected.

Evaluation dataset: 20 single-source questions (5 cross-dataset questions
excluded from sweep eval). Stratified by category and language register
(clinical vs lay).

## Infrastructure

| Component | Value |
|---|---|
| Embedding model | NeuML/pubmedbert-base-embeddings (768-dim) |
| Vector store | pgvector (local, port 5433) |
| Sweep table | idx_pubmed_hypertension_sweep |
| Production table | idx_pubmed_hypertension_v1 (untouched) |
| Eval dataset | eval/pubmed_hypertension/qa_dataset.json (20 questions) |
| Tokenizer | cl100k_base |
| Top-k | 5 |
| Metrics | hit_rate@5, MRR@5 |

## Sweep grid

9 configurations testing four dimensions: chunker method (section-aware vs
token-fixed), chunk size (256/512/1024), overlap (0/64), and section
boundary behavior (respected/ignored).

| Config ID | Chunker | Tokens | Overlap | Boundaries | Rationale |
|---|---|---|---|---|---|
| SA-512-0 | bioc_section | 512 | 0 | respected | Current baseline |
| SA-512-0-NB | bioc_section | 512 | 0 | ignored | Isolates section boundary contribution |
| SA-256-0 | bioc_section | 256 | 0 | respected | Smaller chunks for MRR |
| SA-1024-0 | bioc_section | 1024 | 0 | respected | Larger chunks for context |
| SA-512-64 | bioc_section | 512 | 64 | respected | Tests overlap with section-aware |
| SA-256-64 | bioc_section | 256 | 64 | respected | Small chunks + overlap |
| TF-512-0 | token_fixed | 512 | 0 | n/a | Method comparison at same size |
| TF-512-64 | token_fixed | 512 | 64 | n/a | Token-fixed with standard overlap |
| TF-1024-0 | token_fixed | 1024 | 0 | n/a | Large token-fixed for method effect |

## Hypothesis

*Written before running the sweep. Left unedited after results.*

**Primary prediction: SA-512-0 wins on hit_rate@5.**

Reasoning:

- The VA CPG sweep (52 documents, 50 queries) found token-512-0 optimal
  for recall (0.680). PubMed articles are structurally similar: technical,
  section-heavy, with numbered findings and recommendations.
- Section-aware chunking aligns chunks with the author's paragraph
  structure. Each BioC passage is a complete thought -- splitting by
  passage boundaries should produce chunks that match query intent better
  than arbitrary token windows.
- 512 tokens is a good fit for PubMedBERT's 512-token context window.
  Larger chunks risk diluting the embedding signal; smaller ones risk
  losing answer context.

**Secondary predictions:**

- SA-256-0 may score higher MRR@5 than SA-512-0 by providing more
  granular hits (first relevant chunk ranks higher when chunks are
  smaller). But hit_rate@5 may drop if small chunks lose answer context.
- SA-512-0-NB (no boundary respect) will score close to SA-512-0 but
  slightly lower, because crossing section boundaries mixes unrelated
  content in chunks.
- Overlap (SA-512-64, SA-256-64) will provide no benefit, consistent
  with the VA CPG finding. Structured documents have natural boundaries
  that overlap doesn't improve.
- Token-fixed configs (TF-*) will underperform section-aware configs at
  comparable sizes, because they split mid-passage and lose section type
  metadata. The effect should be larger than the VA CPG's token-vs-sentence
  gap (24pp on recall) because BioC JSON provides richer structure than
  the VA CPG markdown.
- TF-1024-0 may approach SA-512-0 on hit_rate because large chunks
  capture more content per unit, compensating for lack of structure.

**What would surprise us:**

- If token-fixed configs win or tie section-aware, it would suggest that
  PubMedBERT's embedding quality dominates chunking strategy for this
  corpus -- the model finds relevant content regardless of chunk
  boundaries.
- If overlap helps for section-aware chunking, it would contradict the
  VA CPG finding and suggest these articles have more cross-section
  continuity than clinical guidelines.
- If SA-256-0 wins on both hit_rate AND MRR, it would suggest 512 tokens
  is too large for 768-dim PubMedBERT embeddings on review article text.

---

## Results

Total sweep time: 158.1s (9 configs, 10 articles each, 20 eval questions).

| Config ID | Chunks | hit_rate@5 | MRR@5 | mean_score | Notes |
|---|---|---|---|---|---|
| **SA-256-0** | **381** | **0.950** | **0.746** | **0.634** | **winner** |
| SA-512-0 | 233 | 0.850 | 0.646 | 0.616 | baseline |
| SA-512-0-NB | 178 | 0.850 | 0.696 | 0.607 | |
| SA-1024-0 | 155 | 0.850 | 0.654 | 0.601 | |
| SA-256-64 | 458 | 0.850 | 0.654 | 0.630 | |
| TF-512-0 | 160 | 0.850 | 0.702 | 0.609 | |
| TF-1024-0 | 84 | 0.850 | 0.627 | 0.597 | |
| SA-512-64 | 261 | 0.750 | 0.629 | 0.616 | overlap hurt |
| TF-512-64 | 183 | 0.750 | 0.638 | 0.614 | overlap hurt |

SA-256-0 is the only config to break 0.90 hit_rate. It also leads on MRR
(0.746) and mean_score (0.634). The win is clear: +10pp hit_rate over every
other config, +10pp MRR over the baseline.

**Per-question analysis (SA-256-0 vs SA-512-0):**

SA-512-0 missed 3 questions: pmh007 (SGLT2 inhibitors in CKD), pmh008
(tirzepatide BP lowering), pmh020 (global burden of uncontrolled
hypertension). SA-256-0 recovered two of three -- smaller chunks surfaced
the SGLT2 passage and the WHO global burden statistic that were diluted
in larger 512-token chunks. Only pmh008 (tirzepatide, a specific drug
efficacy number embedded in results tables) remained a miss across all 9
configs.

## Effect decomposition

### Method effect (section-aware vs token-fixed)

At 512 tokens, 0 overlap: SA-512-0 (0.850) = TF-512-0 (0.850). No
hit_rate difference. TF-512-0 had slightly higher MRR (0.702 vs 0.646),
meaning it ranked the first relevant chunk higher on average.

**This contradicts the hypothesis.** Section-aware chunking did not
outperform token-fixed at the same size. PubMedBERT appears strong enough
to find relevant content regardless of chunk boundary alignment. The
"BioC structure advantage" that was paper-worthy for *ingestion* (section
type metadata, citation preservation) does not translate into a *retrieval
quality* advantage at 512-token chunks.

However, the advantage appears at smaller sizes: SA-256-0 (0.950) has no
token-fixed counterpart in the grid to compare directly. Adding TF-256-0
to a follow-up sweep would isolate whether the SA-256-0 win is from chunk
size alone or from the combination of small size + passage boundaries.

### Size effect (256 vs 512 vs 1024)

Section-aware, 0 overlap, boundaries respected:
- SA-256-0: 0.950 hit_rate, 0.746 MRR, 381 chunks
- SA-512-0: 0.850 hit_rate, 0.646 MRR, 233 chunks
- SA-1024-0: 0.850 hit_rate, 0.654 MRR, 155 chunks

256-token chunks win by 10pp on hit_rate and 10pp on MRR over both 512 and
1024. The smaller chunks create more focused embedding targets that match
query intent better. The concern that small chunks "lose answer context"
did not materialize -- for retrieval, a chunk only needs to contain enough
of the answer to be identifiable as relevant. The answer model gets the
full top-k context regardless.

512 and 1024 tied on hit_rate (0.850). Larger chunks did not improve recall
despite capturing more content per unit. This suggests the bottleneck is
embedding precision, not coverage.

### Overlap effect (0 vs 64)

Overlap *hurt* in every comparison:
- SA-512-0 (0.850) vs SA-512-64 (0.750): -10pp
- SA-256-0 (0.950) vs SA-256-64 (0.850): -10pp
- TF-512-0 (0.850) vs TF-512-64 (0.750): -10pp

This is stronger than the VA CPG finding (overlap "provided no benefit").
Here, overlap actively degraded performance. The likely mechanism: overlap
duplicates content across adjacent chunks, diluting the embedding
distinctiveness. When the embedding model sees repeated text in multiple
chunks, the similarity scores spread across those near-duplicates rather
than concentrating on the best-matching chunk. With top-k=5, this pushes
the truly relevant chunk out of the top 5 in favor of overlapping
neighbors from different documents.

### Section boundary effect (respected vs ignored)

SA-512-0 (respected, 0.850) vs SA-512-0-NB (ignored, 0.850): same
hit_rate. SA-512-0-NB had higher MRR (0.696 vs 0.646).

Section boundary respect had no hit_rate effect and slightly lower MRR.
When boundaries are ignored, adjacent passages from the same section are
merged into larger chunks (233 vs 178 chunks). These larger, denser chunks
may actually rank higher because they contain more relevant content per
embedding. The boundary-respecting config creates more granular chunks,
spreading relevance across multiple small chunks -- which helps hit_rate
(you need any one to be in top-5) but can hurt MRR (the best chunk may
rank lower because its signal is diluted by having fewer tokens).

## Comparison with VA CPG findings

| Finding | VA CPG sweep | PubMed sweep |
|---|---|---|
| Best chunk size | 512 tokens | 256 tokens |
| Overlap benefit | None (neutral) | Negative (-10pp hit_rate) |
| Method effect (at 512) | Token > Sentence by 24pp | Section-aware = Token-fixed |
| Best hit_rate@5 | 0.680 | 0.950 |
| Best MRR@5 | 0.371 | 0.746 |

**Key differences:**

1. **Smaller chunks won here but not in VA CPG.** Likely because the PubMed
   corpus is smaller (10 articles vs 52 documents) and the questions are
   more specific. With fewer total chunks, 256-token chunks create a more
   focused search space. This finding may not generalize to larger corpora.

2. **Method effect disappeared.** VA CPG found a 24pp gap between token-based
   and sentence-based chunking. Here, section-aware and token-fixed tied at
   512 tokens. The difference: VA CPG compared token vs *sentence* splitting
   (sentence boundaries are poor for structured text); we compared token vs
   *section-aware* (both are reasonable for structured text). The VA CPG
   finding was about sentence-based being bad, not token-based being good.

3. **Absolute performance is much higher.** The PubMed corpus (0.950 hit_rate)
   is dramatically easier than VA CPG (0.680). Likely factors: fewer documents
   (less noise in the search space), domain-specific embedding model
   (PubMedBERT vs Nomic for VA CPG), and the QA questions were written by the
   same person who ingested the articles (implicit alignment).

4. **Overlap is harmful, not neutral.** The VA CPG sweep found overlap provided
   no benefit; the PubMed sweep found it actively hurts. Both corpora have
   clear structure, but the PubMed corpus with BioC passages has even sharper
   passage boundaries, making overlap-induced duplication more damaging.

## Surprises

**The primary hypothesis was wrong.** SA-512-0 did not win; SA-256-0 did,
and by a large margin (10pp on both hit_rate and MRR). The hypothesis
correctly identified section-aware as the right method family and overlap
as unhelpful, but got the optimal chunk size wrong. The VA CPG prior of
"512 tokens is best" did not transfer to this smaller, more focused corpus.

**Token-fixed tied section-aware.** The hypothesis predicted a large gap
favoring section-aware chunking. Instead, they tied at 512 tokens. This is
the most paper-relevant finding: the BioC section-aware chunker's advantage
is in the metadata it preserves (section types, citations), not in raw
retrieval hit rates. For retrieval alone, PubMedBERT handles both chunk
styles equally well. The chunker choice matters for downstream use cases
(section filtering, citation grounding) rather than for embedding quality.

**Overlap was actively harmful.** Not merely neutral as in VA CPG, but -10pp
across the board. Worth investigating whether this is specific to PubMedBERT's
embedding characteristics or a general property of well-structured text.

**SA-512-0-NB (no boundaries) had higher MRR than SA-512-0.** Ignoring
section boundaries produced fewer, denser chunks that ranked higher
individually. This was not predicted -- the hypothesis expected boundary
mixing to hurt. For recall-oriented use cases the difference is zero, but
for MRR-oriented use cases, not respecting boundaries may produce better
first-result quality.

## Replication

```bash
python scripts/sweep_pubmed_chunking.py \
  --data-dir ../retrieval-hub-data-sources/pubmed-hypertension
```

## Raw data

- Per-config checkpoints: `eval/pubmed_hypertension/sweep_configs/`
- Aggregate results: `eval/pubmed_hypertension/sweep_results.json`
