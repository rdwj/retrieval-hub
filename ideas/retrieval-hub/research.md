# Research

Quick scan of the landscape before going deep. The headline finding: **Red Hat is already building something adjacent inside OpenShift AI itself**, which makes positioning the most important early decision.

## The big one: RHOAI 3 "AI Hub" / "AI Assets" catalog

Red Hat shipped (or is shipping) an **AI Hub and gen AI Studio** in OpenShift AI 3 — described as "the new command center for enterprise gen AI." Approved MCP servers already appear in an **AI Assets** listing. The published roadmap explicitly says:

> AI assets are expected to expand MCP Server management and include other high-priority components like **agents, knowledge sources for RAG, and safety guardrails**.

That last bullet is *exactly* the retrieval-hub idea.

**What this means for us:**
- We are not inventing a category — Red Hat agrees this should exist.
- We have a real positioning question: are we **(a)** the reference implementation that fills the "knowledge sources for RAG" slot in AI Assets, **(b)** a complementary platform component that registers itself *as* an AI Asset, or **(c)** something more opinionated that lives alongside it?
- If we're going to be useful inside RHOAI, we should design from day one to integrate with the AI Assets surface, not duplicate it.

Sources:
- https://www.redhat.com/en/blog/introducing-ai-hub-and-genai-studio-new-command-center-enterprise-generative-ai-red-hat-openshift-ai
- https://www.redhat.com/en/products/ai/openshift-ai/mcp-servers

## Adjacent projects

**RAGFlow** (https://github.com/infiniflow/ragflow) — open-source RAG engine with dataset management, configurable embedding models, visualization of chunking. Probably the closest existing OSS to "retrieval-hub" in spirit. Worth evaluating whether parts of it could be used directly vs. whether its assumptions clash with the OpenShift AI integration we want.

**RAGExplorer** (PacificVis 2026) — academic visual analytics tool for *comparing* RAG configurations across embedding models, chunking, reranking, plus dataset management. Not a platform, but the eval/comparison surface is exactly what each retrieval-hub card should expose.

**reconsidered_rag** (https://github.com/rkttu/reconsidered_rag) — semantic chunking tool with git-friendly artifacts for versioning the pipeline. Notable because the "recipe is a versioned artifact" idea aligns with how cards should work.

**Wanaku MCP Router** (https://wanaku.ai) — MCP routing infra; relevant if we want agents to discover retrieval sources through a router rather than connecting directly.

**Red Hat SDG Hub** — referenced in the synthetic-data-for-RAG-eval article; provides repeatable benchmarks across embedding models / chunking / LLM configs. This is a likely upstream for the eval-results part of each card.

## Query rewriting as a first-class capability

There's a growing body of work on per-dataset query rewriting (see: "Query Rewrite in RAG Systems," RAG-MCP paper at arxiv.org/abs/2505.03275, LangChain retrieval docs). But almost everyone treats it as something the *agent* does. The retrieval-hub angle — making rewriting a *property of the source*, with a per-dataset rewrite prompt that the source's owner curates — is a real differentiator and aligns with the broader thesis that retrieval expertise should live next to the data.

Sources:
- https://arxiv.org/html/2505.03275v1 (RAG-MCP)
- https://next.redhat.com/2025/11/26/tool-rag-the-next-breakthrough-in-scalable-ai-agents/
- https://docs.langchain.com/oss/python/langchain/retrieval

## What we should *not* rebuild

- Vector database (use pgvector by default per the platform pattern)
- Embedding model serving (already in OpenShift AI / vLLM)
- Eval frameworks (use SDG Hub or similar)
- Generic MCP infrastructure (FastMCP 3, scaffolded from the fips-agents template)
- Document parsing (Docling, or xml-analysis-framework for S1000D)

retrieval-hub is the **glue and the catalog**, not the substrate.
