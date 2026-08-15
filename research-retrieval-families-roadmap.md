# RetrievalHub Retrieval Family Roadmap

RetrievalHub supports multiple retrieval families, each with its own chunking, embedding, and query strategy. This document captures the current state, planned families, retrieval pattern taxonomy, build order, and demo dataset candidates as decided on 2026-08-14.

## Current State

| Family | Status | Details |
|---|---|---|
| **clinical_document** | Shipped | VA CPG: 52 docs, 6.5K chunks, PubMedBERT embeddings, deployed on gpt-oss-120b |
| **code** | In progress | AST chunker + jina-code-embeddings validated locally; live file fetch not built; not deployed to cluster |
| **document** | Scaffolded | Adapter and pipeline code exist, Red Hat AI docs ingestion script exists, but no actively maintained/deployed source |
| **tabular** | Enum only | `SourceFamily.TABULAR` exists in `enums.py`, no adapter |
| **graph** | Enum only | `SourceFamily.GRAPH` exists in `enums.py`, no adapter |
| **external** | Enum only | `SourceFamily.EXTERNAL` exists in `enums.py`, no adapter |

**New enum to add:** `PROCESS = "process"` in `SourceFamily` for BPMN and workflow process documents. Planned after graph.

## Retrieval Patterns Inventory

Retrieval patterns fall into three tiers: source-family patterns that define how a family retrieves, cross-cutting enhancements that improve any family, and agent-level concerns that belong outside RetrievalHub.

### Source-Family Patterns

Each family uses a fundamentally different retrieval mechanism.

- **Vector ANN** (document, clinical_document, code) -- Semantic similarity search over embedded chunks. The baseline pattern for unstructured text.
- **Text-to-SQL** (tabular) -- Natural language translated to SQL, executed against a database, rows returned. Requires schema awareness and query validation.
- **Graph traversal** (graph) -- SPARQL or Cypher queries over a knowledge graph. Entity lookup, relationship traversal, path finding.
- **Process reasoning** (process) -- BPMN-aware structural queries. Parse XML into a process graph, traverse flows/gateways/swimlanes. Answers questions like "what happens after task X?" or "who owns this step?"
- **External proxy** (external) -- Forward queries to an upstream service, wrap responses with usage rules and provenance. RetrievalHub adds the metadata layer without owning the retrieval.

### Cross-Cutting Enhancements

These improve any family that uses vector ANN. They are not families themselves.

- **Hybrid search (BM25 + vector)** -- Lexical exact match alongside semantic similarity. The single biggest quality improvement for existing families. pgvector supports tsvector for BM25. Should happen alongside or before new families.
- **Reranking** -- Cross-encoder second stage. Retrieve top-50 cheaply, rerank to top-5. Configured at the recipe level.
- **Query rewriting** -- Transform ambiguous queries into optimized retrieval queries. Already planned as issue #15.
- **Parent-child / hierarchical retrieval** -- Embed small chunks, return parent section for context. Recipe-level option.
- **Multimodal** -- Images, diagrams, tables extracted from documents. Extension of the document family or a future family.

### Agent-Level Concerns (Not RetrievalHub's Job)

- **Agentic RAG** -- Multi-step query decomposition. The agent orchestrates multiple retrieve calls; RetrievalHub provides the tools.
- **Federated RAG** -- Distributed retrieval across edge nodes. Different product entirely.
- **Long-document memory** -- Session context management. Agent concern, not retrieval concern.

## Build Order

1. **graph** -- Most general-purpose of the remaining families. Serves dependency graphs, ontologies, org charts. Foundation for process family. Use Neo4j or pgvector with adjacency lists. Adapter pattern: SPARQL/Cypher query construction from natural language, or entity-centric vector search with relationship expansion.

2. **process** -- Specialization of graph for BPMN 2.0 workflow documents. Parse BPMN XML into a process graph (tasks, gateways, sequence flows, swimlanes). Support structural queries. Uses graph adapter infrastructure with BPMN-specific semantics. Relevant to Red Hat ecosystem (jBPM, Kogito, Drools).

3. **tabular** -- Text-to-SQL over structured data. Different enough from vector search to be a strong demo differentiator. Requires schema-aware query generation and result formatting.

4. **document** (proper demo dataset) -- Stand up a non-clinical document source (OpenShift docs, public RFCs, or similar) to demonstrate the platform isn't clinical-only.

5. **Hybrid search** -- BM25 + vector for all families that use vector ANN. Highest-impact quality improvement. Should happen alongside or before new families where practical.

## Demo Dataset Candidates

### document
- **OpenShift/Kubernetes documentation** -- resonates with target audience, large corpus, well-structured
- **Public RFCs** -- keyword-heavy, good hybrid search test case
- **arXiv abstracts subset** -- academic corpus, demonstrates breadth

### code
- **This repository** -- already done, self-referential demo
- **A well-known OSS project** (FastAPI, LangChain) -- demonstrates indexing third-party code

### tabular
- **HuggingFace model metadata** -- model names, sizes, benchmarks. Agents asking "which embedding model has the best MTEB score?"
- **PyPI package metadata** -- name, version, dependencies, downloads. Natural fit for developer-facing agents.
- **Public Census/WHO health data** -- large, well-understood, connects to clinical story

### graph
- **PyPI dependency graph** -- packages depend on packages. "What depends on requests?", "Show the dependency chain for langchain."
- **Wikidata subset** -- entities + relationships, standard benchmark
- **SNOMED-CT or medical ontology subset** -- connects to the clinical_document story

### process
- **Public BPMN process models from GitHub** -- thousands available per mining research
- **ITIL process definitions** -- IT service management, enterprise-relevant
- **Red Hat Process Automation / Kogito examples** -- first-party alignment

## Architecture: Tool Count Stability

As families grow, the MCP tool count stays at three: `list_sources`, `describe_source`, `retrieve`. The `retrieve` tool is polymorphic and dispatches to the right adapter based on `Source.family`. New families add adapters, not tools.

For families that need different query parameters (tabular might want `sql_hint`, graph might want `entity`), the options are:

1. **Optional parameters on `retrieve`** -- current approach (`file_path` for code). Works until the parameter list gets unwieldy.
2. **Generic `options: dict` parameter** -- adapters interpret per-family. Cleaner for many families.
3. **FastMCP tag filtering** -- expose family-specific tools only when relevant. More complex, breaks the three-tool invariant.

Current recommendation: stay with optional parameters for the next 1-2 families, then migrate to `options: dict` if the parameter list grows beyond 5-6 optional fields.

## Sources

- [20 Advanced RAG Types to Know in 2026](https://www.turingpost.com/p/ragtypes)
- [Architectural Patterns for Graph-Enhanced RAG (VentureBeat)](https://venturebeat.com/orchestration/architectural-patterns-for-graph-enhanced-rag-moving-beyond-vector-search-in-production)
- [RAG Beyond the Basics: Five Retrieval Patterns](https://pub.towardsai.net/rag-beyond-the-basics-five-retrieval-patterns-that-turn-chatbots-into-knowledge-engines-d4d227f0f5e4)
- [sBPMN: Semantic BPMN for Dynamic Knowledge Graphs](https://dl.acm.org/doi/10.1145/3731443.3771361)
- [BPMN Graph Transformation: Multi-Format Parser Library](https://www.sciencedirect.com/science/article/pii/S2352711026000427)
- [Structured Extraction from BPMN Diagrams Using VLMs](https://arxiv.org/html/2511.22448)
- [H2A-BPMN: Hierarchical Agent Framework](https://link.springer.com/chapter/10.1007/978-3-032-21171-2_10)
- [Enterprise RAG Guide 2026](https://www.synvestable.com/enterprise-rag.html)
