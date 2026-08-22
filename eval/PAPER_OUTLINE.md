# Multi-Source Retrieval for Enterprise AI Agents: Chunking, Routing, and Scale

## Paper Outline

---

### Abstract (~150 words, draft)

Enterprise retrieval systems increasingly serve multiple data products to
autonomous AI agents, yet most RAG evaluation focuses on single-corpus
pipelines. We present findings from RetrievalHub, a multi-source retrieval
platform that exposes heterogeneous data products to agents via the Model
Context Protocol (MCP). Across three corpora spanning clinical guidelines,
biomedical literature, and aviation maintenance documents, we show that
optimal chunking parameters are corpus-specific, with interactions between
chunk size, embedding model domain specificity, and document structure that
resist transfer. We evaluate agent-driven source selection at scales of 4 to
54 sources, finding that recall remains robust (0.925+) but precision
collapses 38% when confuser sources with overlapping domain descriptions are
introduced. The degradation is driven by domain-overlap count, not catalog
size. We propose an 8-step repeatable methodology for per-corpus chunking
refinement and discuss implications for catalog design, source descriptions,
and the boundary between agent-driven and platform-level routing.

---

### 1. Introduction

**Content:**
- Enterprise AI agents need retrieval across multiple knowledge domains, each
  with distinct document structures, embedding models, and quality profiles.
- Single-corpus RAG optimization does not transfer: parameters tuned on one
  corpus degrade on another. This creates a per-source configuration problem
  that grows with the catalog.
- When the catalog grows, agents must select which sources to query. This
  source selection problem has no established methodology or known scaling
  behavior.
- We address three questions: (1) How do chunking parameters interact with
  corpus structure and embedding models? (2) Can agents reliably select
  sources from a catalog using only metadata descriptions? (3) At what scale
  does agent-driven source selection break down, and what drives the failure?

**Figures/Tables:**
- Figure 1: RetrievalHub architecture diagram showing catalog, physical
  indexes, MCP server, and agent interaction pattern
- Table 1: Summary of the three corpora (document count, format, embedding
  model, optimal config)

**Metrics cited:**
- Three corpora, three different optimal chunk sizes (256, 512, 512)
- Source selection recall 0.95 at 4 sources, precision drop from 0.86 to 0.53
  at 14 sources with confusers

---

### 2. Related Work

**Content:**
- RAG evaluation frameworks (Ragas, AutoRAG) and their single-corpus
  assumptions. Most benchmarks evaluate one retrieval pipeline at a time; we
  extend to comparative evaluation across corpora.
- Multi-source retrieval and federated search literature. Traditional
  federated search uses query routing or collection selection algorithms;
  agent-driven source selection is a new variant where the routing decision is
  made by an LLM via tool use.
- MCP and tool-use agents. The Model Context Protocol provides a standard
  interface for agent-tool interaction. Source selection becomes a tool
  selection problem, with the catalog as the tool registry.
- Chunking strategies in retrieval. Prior work on fixed-size vs.
  structure-aware chunking, overlap effects, and the interaction with
  embedding model capacity. Most findings are single-corpus; cross-corpus
  comparison is sparse.

**Figures/Tables:**
- None (narrative section)

**Metrics cited:**
- Reference Ragas metric definitions (context_precision, answer_relevancy,
  faithfulness) as used in our evaluation

---

### 3. System Design

**Content:**
- RetrievalHub architecture: a single MCP server exposing multiple data
  products. Each source has a physical pgvector index, per-source embedding
  model, chunking configuration, and semantic metadata (usage rules, data
  freshness, scope description).
- Per-source configuration: embedding model selection is a data-owner
  decision. The platform hosts shared model endpoints; data owners choose
  which model best serves their content. Three models in production: Nomic
  v1.5 (general-purpose), PubMedBERT (biomedical domain), Snowflake Arctic
  Embed M v1.5 (general-purpose).
- Agent interaction pattern: `list_sources` returns catalog metadata and
  short descriptions; `describe_source` returns full metadata including
  sample prompts, document counts, and usage rules; `retrieve` executes
  vector search against a specific source; `refine` expands context around a
  retrieved chunk.
- The agent sees only the MCP tool interface. It has no knowledge of the
  underlying embedding models, chunk sizes, or index structures. Source
  selection is driven entirely by the catalog descriptions returned by
  `list_sources`.

**Figures/Tables:**
- Figure 2: Sequence diagram of the agent interaction pattern
  (list_sources -> describe_source -> retrieve -> refine)
- Table 2: Per-source configuration summary (source, embedding model,
  dimensionality, chunk method, chunk size, overlap, chunk count)

| Source | Embedding Model | Dims | Method | Size | Overlap | Chunks |
|--------|----------------|------|--------|------|---------|--------|
| VA CPG | Nomic v1.5 | 768 | token-fixed | 512 | 0 | 6,500 |
| PubMed Hypertension | PubMedBERT | 768 | section-aware | 256 | 0 | 381 |
| Aircraft Maintenance | Snowflake Arctic M v1.5 | 768 | token-fixed | 512 | 0 | 2,098 |

---

### 4. Chunking Parameter Optimization

**Content:**
- Methodology: the 8-step chunking refinement process. (1) Understand source
  format; (2) form starting hypothesis from prior corpora; (3) build 20-50
  question evaluation set with passage-level ground truth; (4) define sweep
  grid across method, size, and overlap dimensions; (5) run parametric sweep
  with re-ingestion and re-embedding per config; (6) analyze with hit_rate@5
  as primary metric and MRR@5 as tiebreaker; (7) validate top candidates with
  Ragas answer quality; (8) record in data card.
- Results across three corpora:
  - VA CPG (52 clinical guideline documents): Token-512-0 wins. 1024/0 has
    higher faithfulness (0.882 vs. 0.854) but lower answer_relevancy
    (0.719 vs. 0.735). Overlap (512/64) is Pareto-dominated.
  - PubMed Hypertension (10 biomedical review articles): SA-256-0 wins.
    Section-aware chunking at 256 tokens achieves 0.950 hit_rate@5 vs. 0.850
    for the 512-token baseline, a 10pp improvement. Overlap uniformly harmful
    (-10pp hit_rate across all size comparisons).
  - Aircraft Maintenance (269 PDF service bulletins): TF-512-0 wins. Overlap
    at 512 tokens causes a 17pp MRR penalty (0.749 to 0.580) with no
    hit_rate benefit. At 256 tokens, overlap helps (+5pp hit_rate), suggesting
    overlap compensates for undersized chunks.
- Cross-domain findings: (1) Optimal chunk size does not transfer. PubMedBERT
  discriminates well at 256 tokens; general-purpose models (Nomic, Snowflake
  Arctic) need 512. (2) Overlap is consistently harmful or neutral at the
  optimal chunk size. It helps only when chunks are undersized. (3) Absolute
  performance converges: all three corpora reach 0.950 hit_rate@5 at their
  optimal configuration.

**Figures/Tables:**
- Table 3: Full sweep results for PubMed Hypertension (9 configs, 3 metrics)
- Table 4: Full sweep results for Aircraft Maintenance (6 configs, 4 metrics)
- Table 5: VA CPG Nomic chunk sweep (3 configs, 5 metrics)
- Figure 3: Pareto front plots for each corpus (context_precision vs.
  answer_relevancy, faithfulness as bubble size)
- Figure 4: Overlap effect comparison across corpora (bar chart showing
  delta hit_rate and delta MRR for overlap vs. no-overlap at each chunk size)

**Key metrics cited:**

VA CPG (Nomic v1.5, 30 queries):

| Config | ctx_precision | answer_relevancy | faithfulness | hit_rate | MRR |
|--------|-------------|-----------------|-------------|----------|-----|
| 512/0 | 0.815 | 0.735 | 0.854 | 1.000 | 0.911 |
| 512/64 | 0.804 | 0.724 | 0.825 | 1.000 | 0.967 |
| 1024/0 | 0.824 | 0.719 | 0.882 | 1.000 | 0.967 |

PubMed Hypertension (PubMedBERT, 20 queries):

| Config | hit_rate@5 | MRR@5 | mean_score |
|--------|-----------|-------|------------|
| SA-256-0 | 0.950 | 0.746 | 0.634 |
| SA-512-0 | 0.850 | 0.646 | 0.616 |
| TF-512-0 | 0.850 | 0.702 | 0.609 |

Aircraft Maintenance (Snowflake Arctic, 20 queries):

| Config | Chunks | hit_rate@5 | MRR@5 |
|--------|--------|-----------|-------|
| TF-512-0 | 2,098 | 0.950 | 0.749 |
| TF-512-64 | 2,330 | 0.950 | 0.580 |
| TF-256-0 | 4,064 | 0.850 | 0.692 |

---

### 5. Cross-Dataset Reasoning and Source Selection

**Content:**
- Experimental setup: 20-question evaluation set spanning three question
  categories. Cross-dataset questions require information from 2+ sources.
  Single-source-control questions have a known single source. Ad-hoc probes
  test edge cases (out-of-scope queries, ambiguous domain boundaries).
- Each question runs as a fresh conversation. The agent has no memory of
  prior questions. The agent uses `list_sources` to see the catalog, then
  decides which sources to query. Scoring compares the agent's source
  selection against ground-truth source sets using precision, recall, and
  exact match.
- Baseline results (v0): Precision 0.858, Recall 0.950, Exact Match 0.550.
  High recall means the agent almost always queries the right sources, but
  also queries unnecessary ones. Cross-dataset questions show the within-
  domain conflation problem: the agent queries both VA CPG and PubMed for
  hypertension questions even when only one is relevant.
- Prompt iteration (v1): Hypothesis that making the agent more selective
  would improve precision. Added disambiguation guidance to the system
  prompt. Result: Recall dropped 12.5pp (0.950 to 0.825), Precision unchanged
  (0.842), Exact Match unchanged (0.550). The agent became more conservative
  but cut the wrong sources. Hypothesis rejected.
- Finding: at small catalog scale (3-4 real sources), the over-query default
  is safer than selective querying. The cost of a false negative (missed
  relevant source) exceeds the cost of a false positive (unnecessary query).

**Figures/Tables:**
- Table 6: v0 vs. v1 source selection scores (precision, recall, exact
  match, avg iterations, input tokens)
- Table 7: v0 scores by question category (cross-dataset, single-source,
  ad-hoc)
- Figure 5: Precision-recall scatter comparing v0 and v1

**Key metrics cited:**

| Variant | Precision | Recall | Exact Match | Avg Iterations | Input Tokens |
|---------|-----------|--------|-------------|----------------|-------------|
| v0 | 0.858 | 0.950 | 0.550 | 4.05 | 722K |
| v1 | 0.842 | 0.825 | 0.550 | 4.55 | 779K |

By category (v0):

| Category | n | Precision | Recall | Exact Match |
|----------|---|-----------|--------|-------------|
| cross-dataset | 10 | 0.900 | 0.900 | 0.500 |
| single-source-control | 5 | 0.700 | 1.000 | 0.400 |
| ad-hoc-probe | 5 | 0.933 | 1.000 | 0.800 |

---

### 6. Source Selection at Scale

**Content:**
- Synthetic confuser methodology: 50 synthetic sources registered in the
  catalog with realistic descriptions and CURATED status but no physical
  indexes. Three deliberate domain-overlap confusers designed to mimic each
  real source (e.g., "87 clinical practice guidelines from WHO covering
  chronic disease management" overlapping VA CPG). The remaining 47 are
  non-overlapping domains (maritime law, seismology, quantum computing).
- Scale curve: evaluated at 4, 14, and 54 total sources. Recall remained
  robust (0.950, 0.950, 0.925). Precision collapsed from 0.858 to 0.526
  when confusers were introduced at 14 sources, and stayed flat at 0.537
  going to 54 sources.
- Control experiments at 13, 23, and 53 sources without confusers showed
  stable precision (0.850-0.858) and recall (0.900-0.925). This confirms the
  degradation is driven by domain-overlap confusers, not catalog size.
- Of 50 synthetic sources, only 5 were ever queried by the agent. The
  confuser set is bounded: agents do not spray queries across all sources.
  The failure mode is within-domain conflation (querying a confuser source
  alongside the correct real source), not catalog-wide spray.
- Finding: agent-driven source selection via unstructured descriptions works
  for cross-domain routing but fails for within-domain discrimination. When
  two sources have overlapping domain descriptions, the agent cannot
  distinguish them based on metadata alone.

**Figures/Tables:**
- Table 8: Scale curve results (catalog size, precision, recall, exact match)
- Table 9: Confuser vs. no-confuser comparison at matched catalog sizes
- Figure 6: Precision and recall vs. catalog size (line chart, with confuser
  and no-confuser series)
- Figure 7: Heatmap of which synthetic sources were queried per question
  (showing the bounded confuser set)

**Key metrics cited:**

With confusers:

| Catalog Size | Precision | Recall | Exact Match |
|-------------|-----------|--------|-------------|
| 4 (baseline) | 0.858 | 0.950 | 0.550 |
| 14 | 0.526 | 0.950 | 0.100 |
| 54 | 0.537 | 0.925 | 0.050 |

Without confusers (control):

| Catalog Size | Precision | Recall | Exact Match |
|-------------|-----------|--------|-------------|
| 13 | 0.850 | 0.925 | 0.550 |
| 23 | 0.858 | 0.900 | 0.500 |
| 53 | 0.858 | 0.900 | 0.500 |

---

### 7. Discussion

**Content:**
- When agent-driven source selection suffices: cross-domain catalogs where
  sources occupy distinct semantic spaces. At 53 non-overlapping sources,
  precision holds at 0.858 and recall at 0.900. This is the common case for
  early enterprise deployments with a handful of distinct data products.
- When platform-level routing is needed: catalogs with domain overlap.
  Unstructured descriptions cannot disambiguate "VA/DoD clinical practice
  guidelines" from "WHO clinical practice guidelines." Structured scope
  signals (document types, date ranges, organizational provenance) could
  provide the disambiguation that free-text descriptions cannot. This
  connects to the CDC contextual fidelity work's approach of encoding scope
  metadata as structured signals rather than relying on natural language
  descriptions.
- Implications for catalog design: source descriptions should maximize
  cross-domain distinctiveness. When domain overlap exists, descriptions
  should emphasize distinguishing attributes (organizational provenance,
  document format, date range) rather than domain topic. The current
  `list_sources` interface returns `description_short`; a richer structured
  metadata response could improve discrimination.
- The over-query default and cost: querying unnecessary sources has a
  measurable cost in tokens (722K input tokens per 20 questions at 4 sources)
  but retrieval latency is parallelizable. The cost of a missed source is
  an incorrect or incomplete answer. At current token prices and catalog
  scales, the over-query default is economically rational.
- Comparison with CDC structured scope signals: the CDC contextual fidelity
  framework proposes structured scope metadata (topic codes, population
  descriptors, temporal ranges) as part of the retrieval context. Our
  findings support this direction: unstructured descriptions provide
  sufficient routing signal only when domains are distinct. Structured
  signals would address the within-domain conflation that unstructured
  descriptions cannot resolve.
- Embedding model selection as a per-source decision: Nomic v1.5
  (general-purpose) outperformed PubMedBERT (domain-specific) on VA CPG
  content even on clinical text (context_precision 0.822 vs. 0.809,
  answer_relevancy 0.740 vs. 0.646). This suggests that general-purpose
  embedding models with larger training corpora may offset domain-specific
  pretraining advantages, at least for retrieval over structured clinical
  documents.

**Figures/Tables:**
- Figure 8: Decision tree for source selection strategy (agent-driven vs.
  platform-routed, based on domain overlap and catalog size)
- Table 10: Embedding model comparison on VA CPG (Nomic v1.5 vs. PubMedBERT
  vs. BioLORD-2023)

| Model | ctx_precision | answer_relevancy | hit_rate |
|-------|-------------|-----------------|----------|
| Nomic v1.5 | 0.822 | 0.740 | 1.000 |
| PubMedBERT | 0.809 | 0.646 | 0.967 |
| BioLORD-2023 | 0.511 | 0.655 | 1.000 |

---

### 8. Conclusion and Future Work

**Content:**
- Summary of contributions: (1) A repeatable 8-step methodology for
  per-corpus chunking refinement, validated across three domains. (2)
  Empirical evidence that chunking parameters are corpus-specific, with
  interactions between chunk size, embedding model domain specificity, and
  document structure. (3) First measurement of agent-driven source selection
  scaling behavior, showing that precision degrades with domain overlap count
  rather than catalog size. (4) Evidence that the over-query default
  outperforms selective querying at small catalog scales.
- Limitations: three corpora represent a narrow slice of enterprise data
  diversity. The source selection evaluation used a single LLM (the model
  powering the agent); different models may show different selection behavior.
  Synthetic confusers lack physical indexes, so the cost of false-positive
  source selection is artificially zero in our experiments.
- Future work: (1) A multi-source search tool (issue #34) that queries
  multiple sources in parallel, removing source selection from the agent's
  responsibility. (2) Structured scope signals in the catalog metadata,
  following the CDC contextual fidelity approach. (3) Scale testing beyond
  50 sources with physical indexes to measure the real cost of over-querying.
  (4) Cross-model evaluation of source selection behavior.

**Figures/Tables:**
- None (narrative section)

**Metrics cited:**
- Recap: three optima (SA-256-0, TF-512-0, TF-512-0), 0.950 hit_rate
  convergence, 38% precision drop with confusers, recall stability at 0.925+

---

### Appendices

**A. Evaluation Question Sets**
- Full 20-question cross-dataset evaluation set with ground-truth source
  assignments and question categories
- 20-question per-corpus evaluation sets used in chunking sweeps

**B. Synthetic Confuser Descriptions**
- Full list of 50 synthetic source descriptions, with the 3 deliberate
  domain-overlap confusers highlighted

**C. Reranking Strategy Comparison**
- Table: 6 reranking strategies on VA CPG (cosine_dedup, cross_encoder,
  hybrid_0.3, hybrid_0.5, hybrid_0.7, register_aware)
- Finding: cross-encoder delivers +12.1% context_precision but -7.9%
  answer_relevancy; hybrid_0.3 is the best trade-off

| Config | ctx_precision | answer_relevancy | faithfulness | MRR |
|--------|-------------|-----------------|-------------|-----|
| cosine_dedup | 0.738 | 0.734 | 0.838 | 0.903 |
| cross_encoder | 0.859 | 0.655 | 0.837 | 0.906 |
| hybrid_0.3 | 0.817 | 0.729 | 0.881 | 0.961 |
| hybrid_0.5 | 0.824 | 0.682 | 0.878 | 0.928 |
| hybrid_0.7 | 0.869 | 0.687 | 0.854 | 0.900 |
| register_aware | 0.845 | 0.680 | 0.838 | 0.933 |
