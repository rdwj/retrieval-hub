# The Problem

RAG is everywhere and almost nobody is doing it well. The pattern repeats:

- A team picks a vector DB, picks an embedding model (often the first one they read about), picks a chunk size that "sounds right," ingests their corpus, hands the agent a raw user question, and is disappointed by the retrieval quality.
- The next team over does exactly the same thing, with different choices, and gets different (also disappointing) results. None of the work is reusable.
- The dataset itself is treated as a blob of text. No one captures *how* it was prepared, *why* those parameters were chosen, or *which LLMs* it was actually evaluated against. Six months later nobody can answer "what embedding model is this index using?"
- The agent is the dumbest part of the pipeline. It gets a user question and forwards it verbatim to a vector search, even though the user's phrasing is often the worst possible query for that particular knowledge set.
- Tabular and structured data get shoved through the same chunked-document pipeline as PDFs, badly. Or they get a bespoke API that nothing else can use.
- Specialized corpora (medical, scientific, legal, technical maintenance) have domain-specific structure that generic ingestion throws away.
- Enterprise governance — who owns this index, when was it last refreshed, what's the lineage, who's allowed to query it — is mostly absent.

The cost shows up at the end: agents that "kind of work" on demos and fall over on real questions, with no shared way to figure out *which part* of the retrieval pipeline is the weak link.

## Who feels this

- **AI engineers / app builders** — building agents that need RAG, currently rebuilding the wheel each time.
- **Data owners / domain experts** — have valuable corpora, no good way to expose them to agents in a way that does justice to the domain.
- **Platform teams** — fielding "can you help me set up a vector DB" requests over and over, with no shared substrate to point at.
- **Enterprise governance / compliance** — no consistent answer to "what data is reachable from which agent."
