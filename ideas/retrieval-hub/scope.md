# Scope

## In scope

- The **catalog**: cards, metadata, recipes, owners, eval results, lineage.
- The **MCP server**: the retrieval surface agents connect to.
- The **per-source query rewriter**: a curated rewrite prompt per source, callable as an MCP tool.
- The **admin UI** for source owners.
- The **SDK** for Python consumers who want a typed client instead of raw MCP.
- A small set of **reference ingestion pipelines** that demonstrate good recipes: a chunked-document corpus, a tabular dataset, and one domain-specific example (likely medical or S1000D depending on what data we can reach).
- Integration with the RHOAI **AI Assets** surface so retrieval sources are discoverable in the same place as MCP servers and models.
- **Enterprise governance** primitives: ownership, refresh status, lineage, access control hooks.

## Out of scope (for v1)

- Building a new vector database. We use pgvector and other existing backends.
- Building a new embedding model serving stack. vLLM via OpenShift AI handles this.
- Building a new eval framework. We consume eval output (e.g. SDG Hub) and display it.
- Building agent runtimes. Agents are external — they connect via MCP.
- Building a general document parser. Docling / xml-analysis-framework do this.
- Multi-cluster federation of catalogs. Single-cluster first.
- Replacing the RHOAI AI Assets UI. We integrate; we don't compete.
- Write-back to source-of-truth systems. Retrieval-hub serves retrieval; data updates flow through ingestion, not through agents.

## Edges to figure out

- How much of the **ingestion pipeline orchestration** is in scope vs. assumed to live in KubeFlow / Tekton with retrieval-hub just consuming the outputs.
- Whether the catalog UI is a retrieval-hub-owned surface or *only* an AI Assets registration. (Likely both early — own it, then collapse into AI Assets when that integration matures.)
- Whether `put` is a real MCP operation or whether all writes go through ingestion pipelines and the MCP surface is read-only for agents.
