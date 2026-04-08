# Open Questions

The questions worth chewing on between sessions.

## Positioning vs. RHOAI AI Hub / AI Assets

This is the biggest one. Red Hat is already building "knowledge sources for RAG" as a future AI Asset type. We need to decide:

- Are we the **reference implementation** for that asset type? (Highest leverage, highest coupling.)
- Are we a **complementary platform component** that registers itself as one or more AI Assets? (Independent, lower leverage on Red Hat's roadmap.)
- Are we **opinionated infrastructure** that lives alongside AI Assets and offers things AI Assets won't, like the per-source query rewriter? (Most flexibility, most risk of duplication.)

This decision affects naming, surface area, UI investment, and how we talk to Red Hat product about it.

## What is a "source," exactly?

A card needs a clear referent. Possibilities:
- A specific index (one embedding model, one chunking recipe, one backend)
- A logical knowledge set that may have multiple physical indexes behind it (e.g. the same medical KB embedded with two different models so you can A/B them)
- A connection to an external retrieval system (someone else's Elasticsearch, a hosted vector DB, a graph DB)

Probably all three, but the data model needs to make that explicit.

## Is `put` a real MCP operation?

Letting agents write into a retrieval source is powerful and dangerous. Options:
- Read-only MCP. All writes go through ingestion pipelines. Cleanest, most enterprise-friendly.
- Per-source policy. Some sources allow agent writes (e.g. agent scratchpads), most don't.
- Read-only by default, with a separate opt-in agent-writable surface that's clearly different.

This is partially a memory-hub vs. retrieval-hub boundary question.

## Query rewriting LLM

The rewriter needs an LLM. Three models:
- **Caller-supplied** — the agent passes its own LLM credentials, the rewriter calls back. Lowest infra cost, highest config burden.
- **Cluster-resident** — retrieval-hub uses an LLM running on the same OpenShift AI cluster. Predictable, FIPS-clean, but adds an inference dependency.
- **Both** — caller can pass one, otherwise we use a default cluster LLM.

"Both" is probably right but we should pick a default cluster LLM and document why.

## Tabular sources — what does the retrieval surface actually look like?

Vector search over chunked rows is wrong. Options worth exploring:
- Text-to-SQL with a curated schema description and examples
- A typed query DSL exposed as an MCP tool
- A "ask-as-question, return-as-table" surface backed by a structured retrieval engine
- All of the above per-source

This needs a real example before we commit.

## Domain-specialized recipes — how opinionated do we get?

Medical, legal, scientific, S1000D — each has structure that generic chunking destroys. Do we ship reference recipes for these out of the box, or do we ship the *framework* for capturing recipes and let domain teams contribute?

Probably the latter, with one or two reference recipes as proof.

## Naming

"retrieval-hub" is fine as a working name. Alternatives worth considering:
- `rag-hub` (clearer to outsiders, less precise)
- `knowledge-hub` (overloaded)
- `source-hub` (vague)
- `surface-hub` (cute, accurate, possibly confusing)
- something Red-Hat-namespaced if we end up shipping into RHOAI

Defer until positioning is decided.

## Relationship to memory-hub

memory-hub gives agents memory layers. retrieval-hub gives agents retrieval sources. The boundary feels clean — memory is per-agent/per-conversation/per-tenant scratch and recall, retrieval is shared, curated knowledge — but we should write that boundary down so the two components don't grow into each other. Especially around the `put` question above.
