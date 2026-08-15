# Research: AutoRAG for Chunking Strategy Optimization

**Date:** 2026-08-14

## Summary

AutoRAG (Marker-Inc-Korea) is an AutoML-style framework that systematically evaluates RAG pipeline configurations — including chunking strategies, retrieval methods, and rerankers — against your own evaluation data. It directly supports ms-marco cross-encoder rerankers and can evaluate different chunking methods (token, sentence, semantic) with varying sizes and overlaps. However, it does **not** natively support pgvector; its supported vector stores are Chroma, Milvus, Weaviate, Pinecone, Couchbase, and Qdrant. For RetrievalHub's VA CPG use case, AutoRAG is well-suited for **offline experimentation** to find the optimal chunking strategy, after which the winning configuration feeds into the production pgvector-based ingestion pipeline.

**Recommendation:** Use AutoRAG with Chroma (its default, local vector store) for chunking strategy evaluation. Once the optimal chunking config is identified, implement it in RetrievalHub's existing ingestion pipeline that writes to pgvector. This separation keeps AutoRAG as a development/experimentation tool, not a production dependency.

## What AutoRAG Does

[AutoRAG](https://github.com/Marker-Inc-Korea/AutoRAG) (v0.3.24, Apache 2.0, latest release 2026-07-22) is a RAG optimization framework that:

1. Takes your corpus and a QA evaluation dataset (questions with known answers)
2. Sweeps across combinations of chunking, retrieval, and reranking configurations
3. Scores each combination using deterministic retrieval metrics (no LLM calls needed for retrieval evaluation)
4. Outputs the winning configuration as a YAML file

The [Red Hat Developer article](https://developers.redhat.com/articles/2026/08/04/autorag-optimizing-rag-small-models) (August 2026) demonstrates AutoRAG optimizing RAG for small models, achieving 88% reduction in context word count while maintaining the same answer retrieval accuracy.

**Key insight from the Red Hat article:** "The best RAG pipeline is a function of your data and your queries" — no universal default exists, optimization must be discovered per dataset.

### Important Version Note

AutoRAG has two branches:
- **AutoRAG 0.x (Python)** — the original, currently at v0.3.24. This is what we want. In maintenance mode but stable and feature-complete for evaluation.
- **AutoRAG 2.0 (Node/TypeScript)** — a complete reimagining as an agent framework (`@autorag/librarian`). Different purpose, different codebase. Not what we need.

## AutoRAG Pipeline Architecture

AutoRAG structures evaluation across eight sequential nodes:

| Node | Purpose | Modules |
|---|---|---|
| 1. Query Expansion | Reformulate queries | Query Decompose, HyDE, Multi Query |
| 2. Retrieval | Find relevant passages | BM25, VectorDB, Hybrid (RRF, CC) |
| 3. Passage Augmentation | Expand context | Prev/Next Augmenter |
| 4. **Passage Reranking** | Re-score passages | **15+ rerankers including ms-marco cross-encoders** |
| 5. Passage Filtering | Remove low-quality | Similarity threshold, recency, cutoff |
| 6. Passage Compression | Reduce context | Tree summarization, Refine, LLMLingua |
| 7. Prompt Engineering | Format for LLM | F-string, Chat, Long Context Reorder |
| 8. Generation | Produce answers | LlamaIndex LLM, vLLM, OpenAI |

For chunking optimization, we primarily care about nodes 1-4: chunking strategy (pre-pipeline), retrieval method, and reranking.

## Chunking Methods

AutoRAG supports two chunking backends with multiple methods each:

### LlamaIndex Chunk (`llama_index_chunk`)

```yaml
modules:
  - module_type: llama_index_chunk
    chunk_method: [Token, Sentence, Semantic_llama_index, SemanticDoubling, SentenceWindow]
    chunk_size: [256, 512, 1024]
    chunk_overlap: [0, 24, 50]
    add_file_name: en
```

Methods:
- **Token** — Fixed token-count chunks (baseline, fastest)
- **Sentence** — Split on sentence boundaries
- **Semantic_llama_index** — Groups semantically similar sentences using embeddings
- **SemanticDoubling** — Double-merge variant of semantic chunking
- **SentenceWindow** — Individual sentences with surrounding window context

### LangChain Chunk (`langchain_chunk`)

Supports LangChain text splitters including:
- `RecursiveCharacterTextSplitter`
- `CharacterTextSplitter`
- `MarkdownTextSplitter` (relevant for our markdown-extracted CPGs)
- Custom splitters via registration

### Relevance for VA CPGs

The clinical guidelines are extracted markdown with clear section structure. The most promising methods to evaluate:

1. **Token** (baseline) — what RetrievalHub currently has
2. **Sentence** — respects sentence boundaries, important for clinical recommendations
3. **Semantic** — groups related clinical content, may preserve procedure steps
4. **MarkdownTextSplitter** (via LangChain) — respects markdown heading hierarchy

Chunk sizes to sweep: 256, 512, 1024 tokens (2026 research shows factoid queries prefer 256-512, analytical queries need 1024+; clinical queries will likely be mixed).

## Reranker Support

AutoRAG supports 15+ reranker modules. The ones relevant to our stack:

### Sentence Transformer Reranker (ms-marco)

```yaml
- module_type: sentence_transformer_reranker
  batch: 32
  model_name: cross-encoder/ms-marco-MiniLM-L-6-v2
  max_length: 512
```

Default model: `cross-encoder/ms-marco-MiniLM-L-2-v2`. We'd want to evaluate `cross-encoder/ms-marco-MiniLM-L-6-v2` (better quality, recommended default for production).

### Other Available Rerankers

- Flag Embedding LLM Reranker (`BAAI/bge-reranker-v2-gemma`)
- ColBERT Reranker
- Jina Reranker
- Cohere Reranker
- FlashRank
- MonoT5
- OpenVINO Reranker

## Evaluation Metrics

AutoRAG calculates three retrieval metrics per configuration (no LLM needed):

- **Context Recall** — did we retrieve the chunk containing the answer?
- **MRR (Mean Reciprocal Rank)** — how high up is the first relevant chunk?
- **Average Context Words** — how much text was passed to the model?

Composite score: `context_recall + 0.05 * mrr - 0.00002 * avg_ctx_words`

Recall dominates; a small penalty rewards configs that find answers in less text.

## Workflow for VA CPGs

### Step 1: Prepare Corpus

Convert the 52 extracted markdown files to AutoRAG's parquet format:

```python
from autorag.chunker import Chunker

# AutoRAG expects parsed data as parquet with doc_id, contents, path, metadata columns
chunker = Chunker.from_parquet(parsed_data_path="path/to/parsed_corpus.parquet")
chunker.start_chunking("chunk_config.yaml")
```

### Step 2: Create QA Evaluation Dataset

This is the most critical step. AutoRAG needs question-answer pairs grounded in the corpus. Options:

1. **Manual creation** — write 20-50 clinical questions with known answers from the CPGs (highest quality, most effort)
2. **LLM-generated** — use AutoRAG's QA generation to create synthetic QA pairs from the corpus (faster, good enough for chunking evaluation)
3. **Hybrid** — LLM-generate, then manually curate a subset

For clinical content, manual curation of at least a core set is recommended — LLM-generated questions may miss domain-specific query patterns (lay language, abbreviations, multi-step clinical reasoning).

### Step 3: Configure Evaluation Sweep

```yaml
# chunk_eval_config.yaml
modules:
  - module_type: llama_index_chunk
    chunk_method: [Token, Sentence, Semantic_llama_index]
    chunk_size: [256, 512, 1024]
    chunk_overlap: [0, 24]
    add_file_name: en

  - module_type: langchain_chunk
    chunk_method: [MarkdownTextSplitter]
    chunk_size: [512, 1024]
    chunk_overlap: [0, 50]
```

### Step 4: Run Evaluation

```python
from autorag.evaluator import Evaluator

evaluator = Evaluator(
    qa_data_path="path/to/qa_dataset.parquet",
    corpus_data_path="path/to/corpus.parquet",
    project_dir="./autorag_results"
)
evaluator.start_trial("eval_config.yaml")
```

### Step 5: Analyze Results

AutoRAG produces `summary.csv` with scores for each configuration. The winning chunking strategy (method, size, overlap) is then implemented in RetrievalHub's ingestion pipeline.

## Vector Store Limitation

AutoRAG does **not** support pgvector. Supported backends:
- Chroma (default, local, no setup)
- Milvus
- Weaviate
- Pinecone
- Couchbase
- Qdrant

**This is fine for our use case.** AutoRAG is an evaluation/experimentation tool. The chunking strategy it discovers is independent of the vector store — we apply the winning chunk method/size/overlap to RetrievalHub's existing pgvector-based ingestion pipeline. The vector store only matters for AutoRAG's internal retrieval evaluation, where Chroma (the default) works fine.

## Embedding Model Evaluation

AutoRAG can evaluate different embedding models as part of the retrieval sweep. This means we could compare PubMedBERT vs all-MiniLM-L6-v2 during the same evaluation run, though AutoRAG uses embeddings via LlamaIndex/LangChain integrations rather than vLLM. For evaluation purposes this is fine — we're measuring retrieval quality, not serving throughput.

## Integration with RetrievalHub

```
AutoRAG (experimentation)          RetrievalHub (production)
─────────────────────────          ──────────────────────────
VA CPG markdown                    VA CPG markdown
    ↓                                  ↓
Chunk with N strategies            Chunk with WINNING strategy
    ↓                                  ↓
Embed (sentence-transformers)      Embed (PubMedBERT via TEI)
    ↓                                  ↓
Store in Chroma (temp)             Store in pgvector (permanent)
    ↓                                  ↓
Evaluate retrieval quality         Serve via MCP server
    ↓
Output: optimal config YAML
    ↓
Feed into RetrievalHub ingestion
```

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| AutoRAG 0.x in maintenance mode | Low | Stable, feature-complete for evaluation. We're using it as a tool, not a runtime dependency |
| QA dataset quality | Medium | Start with LLM-generated, manually curate clinical subset |
| No pgvector support | None | Not needed — evaluation uses Chroma; production uses pgvector |
| Python 3.10-3.12 restriction | Low | Use separate venv for AutoRAG evaluation |
| Chunking results may not transfer across embedding models | Medium | Evaluate with the same embedding model we'll use in production, or re-run with production model |

## Alternatives Considered

| Tool | Fit | Notes |
|---|---|---|
| **AutoRAG (Marker-Inc-Korea)** | Best | Purpose-built for this exact problem. Systematic, metrics-driven |
| **RAGAS** | Partial | Focuses on generation quality metrics, less on chunking optimization |
| **Manual A/B testing** | Viable | More control, but slower and less systematic |
| **Adaptive Chunking (LREC 2026)** | Research | Academic approach; no production framework yet |

## Sources

- [AutoRAG GitHub Repository](https://github.com/Marker-Inc-Korea/AutoRAG)
- [AutoRAG Documentation](https://marker-inc-korea.github.io/AutoRAG/index.html)
- [AutoRAG on PyPI](https://pypi.org/project/AutoRAG/) — v0.3.24
- [AutoRAG: Optimizing RAG for Small Models (Red Hat Developer)](https://developers.redhat.com/articles/2026/08/04/autorag-optimizing-rag-small-models)
- [AutoRAG Chunking Documentation](https://marker-inc-korea.github.io/AutoRAG/data_creation/chunk/chunk.html)
- [AutoRAG Sentence Transformer Reranker](https://marker-inc-korea.github.io/AutoRAG/nodes/passage_reranker/sentence_transformer_reranker.html)
- [5 RAG Chunking Methods (AutoRAG Blog)](https://medium.com/@autorag/5-rag-chunking-methods-706d0a1e9a8d)
- [MS MARCO Cross-Encoders (SBERT)](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html)
- [Adaptive Chunking: Optimizing Chunking-Method Selection for RAG (ACL 2026)](https://aclanthology.org/2026.lrec-1.903/)
- [Best Chunking Strategies for RAG in 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)
