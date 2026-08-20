# Eval Convergence Plan: Retrieval Quality

Goal: converge on the best retrieval configuration for the VA CPG source,
publish results that position RetrievalHub's per-source semantic layer
approach against established benchmarks, and produce material for an arXiv
paper.

## Where we are (after 5 runs)

The eval register (`EVAL_REGISTER.md`) tracks 5 runs covering three
dimensions: rewriting lift (Runs 1-2), answer quality with Ragas (Run 3),
and reranking strategies (Runs 4-5). Key findings:

- **Rewriting** improves lay-register retrieval (+7.1% hit_rate) but
  degrades clinical MRR. The semantic layer halved the clinical degradation.
- **Cross-encoder reranking** produces the largest single improvement:
  +12.1% context_precision while maintaining faithfulness. Trade-off:
  -7.9% answer_relevancy.
- **Faithfulness** is stable across strategies (~0.84), suggesting answer
  grounding is more about the answer model than the retrieval ranking.

## Remaining experiments

### Tier 1: High impact, low cost

**E2. Register-aware rewriting**
- Hypothesis: skipping rewriting on clinical queries preserves their high
  answer_relevancy (0.804) while cross-encoder still provides precision.
  This should close the answer_relevancy gap without losing context_precision
  gains.
- Method: detect clinical register (keyword overlap with vocabulary
  mappings canonical terms), skip rewriting, apply cross-encoder reranking
  on the original query's results only.
- Cost: one code change + one eval run (~2 hours).

**E8. Hybrid ranking (cross-encoder + cosine blend)**
- Hypothesis: a weighted blend of cross-encoder score (precision) and
  cosine similarity score (answer-model affinity) could recover
  answer_relevancy while keeping most of the context_precision gain.
- Method: blend scores with a tunable alpha, sweep alpha in [0.3, 0.5, 0.7].
- Cost: three short eval runs, no new retrieval needed (reuse cached
  candidates).

### Tier 2: Medium cost, valuable for the paper

**E3. Chunk size and overlap sweep**
- Configurations: 256/0, 256/64, 512/64, 1024/128.
- Requires re-ingestion per config (~10 min each) + full eval per config.
- Cost: ~1 day total. Best run on EvalHub when available.

**E4. Embedding model comparison**
- Candidates: PubMedBERT (current), jina-embeddings-v3, BioLORD-2023.
- Requires re-ingestion per model + full eval.
- The May 2026 JMIR clinical benchmark study found that clinical context
  variables explain as much variance as model choice. Our semantic layer
  is the "clinical context variable" -- the paper story is that platform
  metadata closes the gap without changing the embedding model.

**E9. BM25 hybrid retrieval**
- T2-RAGBench (2026) found hybrid retrieval (BM25 + dense) + neural
  reranking is the best-performing strategy (Recall@5=0.816, MRR@3=0.605).
  Adding BM25 as a retrieval channel alongside vector search would test
  whether this holds for our corpus.
- Requires pgvector full-text search or a separate BM25 index.

### Tier 3: Statistical rigor and publication

**E6. Query set expansion to 100+**
- Generate additional Q/A pairs from the corpus (LLM-assisted, validated).
- Add per-clinical-category stratification (not just lay vs. clinical).
- Add bootstrap confidence intervals to all metrics.

**E10. Cross-validation**
- Split the query set into train/test folds to measure overfitting to the
  current 30-query set. The vocabulary mappings and semantic context were
  authored with knowledge of these queries, so there's a risk of
  data leakage.

**E11. Inter-judge agreement**
- Score the same run with multiple judge LLMs (gpt-oss-120b, Gemini Flash,
  granite3.3:8b) and measure correlation. This validates that our Ragas
  scores are stable across judges.

## Leaderboard positioning

**There is no standard RAG system leaderboard.** MTEB and BEIR evaluate
embedding models, not retrieval systems. No leaderboard accepts a full
pipeline submission (rewriting + semantic layer + reranking).

The paper angle is stronger than a leaderboard placement:

1. **The clinical benchmark argument.** A May 2026 JMIR Medical Informatics
   study found that clinical context variables explain as much variance in
   retrieval performance as embedding model choice (49% vs 48%), and that
   MTEB rankings are not portable to clinical domains. Our per-source
   semantic layer is the systematic way to inject those context variables.
   We demonstrate this on the VA CPG corpus.

2. **Platform vs. model contribution.** We don't make a new embedding model.
   We show that platform-level metadata (vocabulary mappings, entity
   definitions, abbreviation glossaries) plus cross-encoder reranking
   against the original query produces +12.1% context_precision on top of
   an off-the-shelf embedding model (PubMedBERT). The improvement comes
   from data-owner-declared knowledge, not model training.

3. **Reproducibility.** All eval infrastructure, query sets, and results are
   in the repo. The eval register tracks every run with methodology and
   configuration. Anyone can re-run with different corpora.

**Benchmarks to reference (not submit to):**
- MTEB/BEIR: cite as the general-domain baseline our embedding model was
  evaluated on, note the domain portability limitation
- T2-RAGBench: cite for the hybrid + reranking finding that aligns with
  our cross-encoder results
- JMIR clinical benchmark: cite for the clinical context variables finding
  that motivates our semantic layer

## arXiv paper outline

Working title: "Per-Source Semantic Layers for Domain-Adaptive Retrieval
in Multi-Tenant RAG Platforms"

1. **Problem:** Enterprise RAG platforms serve multiple corpora with
   different domain vocabularies. General-domain embedding models and
   retrieval benchmarks don't transfer to specialized domains. Each corpus
   currently needs bespoke retrieval engineering.

2. **Approach:** Per-source semantic layers -- declarative metadata
   (entity definitions, vocabulary mappings, metric definitions,
   abbreviation glossaries) authored by data owners and consumed by a
   shared query rewriter + cross-encoder reranker. The platform provides
   domain-adapted retrieval without domain-specific model training.

3. **Evaluation:** Controlled experiment on VA/DoD Clinical Practice
   Guidelines (52 documents, 6,500 chunks). 30-query evaluation set
   stratified by language register. Five reranking strategies compared
   across three Ragas metrics (context_precision, answer_relevancy,
   faithfulness).

4. **Results:**
   - Vocabulary mappings + semantic layer: +7.1% hit_rate on lay queries
   - Cross-encoder reranking: +12.1% context_precision, +16.2% on clinical
   - Faithfulness stable across all strategies (~0.84)
   - Trade-off: answer_relevancy -7.9% with cross-encoder (addressable
     via register-aware rewriting or hybrid scoring)

5. **Discussion:** The semantic layer's value is encoding domain expertise
   as platform metadata rather than model weights. The cross-encoder's
   precision gain comes from separating recall (rewrites cast a wide net)
   from precision (rerank against original intent). The answer_relevancy
   trade-off suggests that retrieval precision and answer-model affinity
   are different optimization targets.

6. **Generalizability:** The schema is domain-agnostic. The same semantic
   layer structure applies to code retrieval, legal corpora, and enterprise
   documentation. Brief examples of how entity_type and relationship_type
   adapt to non-clinical domains.

## Timeline

| Phase | Work | Dependency |
|---|---|---|
| Next session | E2 (register-aware rewriting) + E8 (hybrid scoring) | None |
| Following | E3 (chunk sweep) + E4 (embedding comparison) | EvalHub or patience |
| Pre-paper | E6 (query expansion) + E10 (cross-validation) | E3/E4 results |
| Pre-paper | E11 (inter-judge agreement) | None |
| Paper draft | Abstract + methods from eval register data | All above |

## References

- [MTEB Leaderboard (HuggingFace)](https://huggingface.co/spaces/mteb/leaderboard)
- [BEIR Benchmark](https://github.com/beir-cellar/beir)
- [T2-RAGBench](https://arxiv.org/pdf/2604.01733)
- [Clinical Context Variables (JMIR 2026)](https://pubmed.ncbi.nlm.nih.gov/42097608/)
- [Ragas](https://docs.ragas.io/)
