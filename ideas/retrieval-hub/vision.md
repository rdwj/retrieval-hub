# Vision

Picture an AI engineer who wants to build an agent that can answer questions about, say, an internal medical knowledge base.

**Today** they spend two weeks picking a vector DB, picking an embedding model, writing an ingestion script, tuning chunk size by guessing, wiring up a retrieval call, and then watching the agent return mediocre results because user questions don't match how the corpus is written.

**With retrieval-hub** they open the catalog in OpenShift AI, find a card titled "Internal Medical Knowledge Base — RAG-optimized," and the card tells them:

- It's embedded with `nomic-embed-text-v1.5` at 768 dimensions
- It was chunked at 512 tokens with 64-token overlap, using semantic-boundary chunking
- It's stored in pgvector
- Here is a sample agent system prompt that works well with this source
- Here are eval scores for Granite-3, Llama-3.3-70B, Mistral-Large, and GPT-4o
- For Granite-3 specifically, here's the prompt that performed best
- It supports **query rewriting**: send the user's raw question, get back 3-5 reformulated queries that match this corpus's vocabulary and structure
- It's owned by the Clinical Informatics team, refreshed nightly, last refreshed 6 hours ago

They point their agent's MCP client at retrieval-hub, the agent discovers the source automatically, and the first query already performs well — because all of the hard work was done once, by the people who actually know the domain, and is now reusable.

## What becomes possible

- **Reusable retrieval surfaces.** The medical KB is built once and consumed by every agent in the org that needs it.
- **Domain experts ship retrieval, not just data.** A scientist can publish a "ready to RAG" surface for their corpus and version it like a model.
- **Query rewriting becomes a property of the dataset, not the agent.** The dataset knows best how to be queried; that knowledge lives next to the data.
- **Honest evaluation.** Every source carries reproducible eval scores against multiple LLMs, so picking a source for an agent is a data-driven decision.
- **Tabular sources are first-class.** "Retrieval" stops meaning "vector search over chunks" and starts meaning "any structured way to get a relevant slice of a dataset to an LLM."
- **Enterprise governance for free.** Because everything goes through one substrate, lineage, ownership, refresh cadence, and access control are answerable questions.

## What success looks like

- An agent builder picks a source from the catalog and gets useful retrieval *on the first try*, without tuning.
- Two different agents use the same source and neither one had to know anything about chunking or embeddings.
- A domain expert publishes a new source and the recipe is captured in a way another team can audit and reproduce.
- Query rewriting demonstrably improves retrieval quality for at least one source where the user-language vs. corpus-language gap is real (e.g. lay → clinical terminology).
