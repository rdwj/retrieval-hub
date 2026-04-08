# retrieval-hub

A platform component for OpenShift AI that gives agents an easy way to connect to **retrieval sources** for building RAG-enabled agents — the same way memory-hub gives them memory layers.

The core insight: RAG today is a pile of one-off implementations. Every team rediscovers chunking, every team picks an embedding model, every team writes their own retrieval glue, and every team's agent gets handed a raw user question and tries to query a vector DB with it. Retrieval-hub is the place where datasets show up *already optimized* — chunked, embedded, recipe-documented, eval'd against multiple LLMs, and exposed to agents through MCP tools.

## Shape of the idea

- **Catalog of retrieval sources, presented as cards.** Like the RHOAI model catalog, but each card is a dataset or data connection that's been turned into a first-class retrieval surface.
- **Cards carry the recipe.** Embedding model, chunk size, overlap, embedding dimension, vector/graph backend, sample agent system prompts, eval results across LLMs, per-LLM prompts where useful.
- **MCP tools for agents.** `get`, `put`, `query`, `query_rewrite`, etc. Agents discover sources and pull from them through one consistent surface.
- **Per-dataset query rewriting.** This is the part I keep coming back to. Each retrieval source can opt into a query-rewrite capability that takes the agent's raw question and returns a *knowledge-set-specific* set of better-formed queries — informed by the dataset's own structure, vocabulary, and a tuned prompt. Rewriting can use the agent's own LLM or one running on the cluster.
- **Tabular, document, and scientific/medical sources.** Not just "chunked PDFs in a vector DB." A tabular dataset with a retrieval surface that supports filter/aggregate/reason-over is a first-class citizen. So are domain-specific corpora that have been ingested with domain-aware recipes.
- **Enterprise data management.** Ingestion is a managed workflow, sources have owners, lineage is tracked, evals are repeatable.

## Status

Brand new. We have:
- This README
- The platform-component pattern doc from memory-hub at `docs/PLATFORM_COMPONENT_PATTERN.md`
- Initial ideation in this directory

Nothing built yet. Not even a name we're sure of.

## Files in this directory

- `conversation-*.md` — Notes from each ideation session
- `problem.md` — What hurts and why
- `vision.md` — What "good" looks like
- `research.md` — GitHub/market findings, especially the RHOAI AI Hub overlap
- `requirements.md` — High-level, declarative
- `scope.md` — In and out
- `open-questions.md` — Stuff we haven't decided
- `next-steps.md` — What to think about before the next session
