# Requirements (high-level, declarative)

These are early. They will sharpen across sessions.

## Must-have

- Must run as an application on OpenShift AI, deployable to any RHOAI cluster.
- Must present retrieval sources as a **catalog of cards**, in the spirit of the RHOAI model catalog.
- Each card must surface, at minimum: source name, owner, embedding model (if any), chunking recipe, retrieval backend, refresh status, and at least one sample agent system prompt.
- Must expose retrieval to agents through **MCP tools** (FastMCP 3, streamable-http).
- Must support, at minimum, these MCP operations: discover sources, get a source's metadata/recipe, query a source, retrieve by id.
- Must support **per-source query rewriting** as an opt-in capability, with the rewrite prompt being a curated property of the source.
- Must support multiple retrieval backends (vector, graph, structured/tabular) behind the same MCP surface.
- Must support multiple embedding models (vLLM-served).
- Must capture and display **per-LLM evaluation results** for each source.
- Must be FIPS-compatible unless an exception is granted.
- Must use Red Hat UBI base images and follow the platform-component pattern in `docs/PLATFORM_COMPONENT_PATTERN.md`.
- Must have an admin UI for source owners to inspect, configure, and curate sources.
- Must have a Python SDK for app builders who don't want to talk MCP directly.

## Should-have

- Should integrate with the RHOAI **AI Assets** catalog so retrieval sources show up alongside MCP servers and (eventually) other assets.
- Should support per-LLM-family prompt variants on a card.
- Should track lineage: where the data came from, when it was last ingested, what version of the recipe was used.
- Should support an ingestion workflow that produces a card as its output, not just an index.
- Should let query rewriting use either the agent's own LLM (caller-supplied) or an LLM running on the cluster.
- Should support tabular sources with filter/aggregate semantics, not just vector search.
- Should support domain-specialized ingestion recipes (medical, scientific, S1000D, etc.).

## Won't (yet)

- Won't be a vector database — uses pgvector and other existing backends.
- Won't replace eval frameworks — consumes their output.
- Won't be the agent runtime — agents live in LangGraph / LlamaStack / Kagenti / Claude Code etc., they just connect to retrieval-hub via MCP.
- Won't be a general-purpose data platform — focused on retrieval surfaces for agents.

## Constraints

- Enterprise / OpenShift environment assumed.
- FIPS compliance unless told otherwise.
- Must coexist with whatever Red Hat ships in AI Assets — no duplication of catalog UI if we can register *into* AI Assets instead.
