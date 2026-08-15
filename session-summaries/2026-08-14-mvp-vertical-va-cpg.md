# Session Summary — 2026-08-14 · MVP Vertical · VA CPG end-to-end on OpenShift

**Plan:** First vertical build — VA CPG data through to a working demo on cluster
**Commits:** none yet (prepare-and-ask mode)   **Branch:** main
**Deployed:** gpt-oss-120b cluster (retrieval-hub namespace)   **Model:** Opus 4.6 (1M)

## Plan vs. actual

Planned: Ingest VA CPG corpus, build MCP server, connect Claude Code. Shipped: full vertical including UI with real data, playground with LLM generation, AutoRAG chunking evaluation, and usage rules system. Scope expanded significantly from the original plan — what started as "MCP server + Claude Code" grew into a complete demo stack on OpenShift.

## Shipped

**Infrastructure (on gpt-oss-120b, retrieval-hub namespace):**
- PostgreSQL 16 + pgvector 0.8.6 (StatefulSet, 10Gi PVC)
- TEI shared PubMedBERT embedding service (cpu-1.6, 5Gi model PVC)
- MCP server (FastMCP 4.0.0b1, streamable-http, binary build)
- BFF API (FastAPI, catalog + playground with LLM generation)
- Live UI (React/PatternFly, nginx proxy to BFF)
- 6 pods running, all UBI-based, non-root

**Core library changes:**
- Configurable embedding prefixes in ChunkEmbedder/QueryEmbedder (PubMedBERT uses no prefix)
- Recursive corpus tree walker (load_corpus_tree with url_map for source URLs)
- DocumentAdapter reads query_prefix from recipe
- Source model: added usage_rules JSON column + Alembic migration
- retrieval/api.py: handles clinical_document family
- register.py: accepts family and usage_rules params

**Data pipeline:**
- 52 VA CPG documents ingested with PubMedBERT (NeuML/pubmedbert-base-embeddings, 768 dims)
- 6,500 chunks (Token-512, no overlap — AutoRAG-validated optimal config)
- Source URLs mapped to VA.gov PDFs via pdf-urls.json
- Usage rules (citation, scope disclaimer, handling) stored on Source, ride with every retrieval
- Data freshness card (source name, URL, last refreshed, cadence, staleness note)
- Eval results stored as EvalRun/EvalResult records (recall@5=0.68, MRR=0.321)

**MCP server (retrieval-hub-mcp/):**
- FastMCP 4.0.0b1 with 3 tools: list_sources, describe_source, retrieve
- Retrieve returns RetrievalResponse with hits + usage_rules + data_freshness
- Exercised via mcp-test-mcp: all tools pass, error paths correct, 1.5s warm-query latency
- Deployed on OpenShift with Route (edge TLS)

**BFF (retrieval-hub-bff/):**
- FastAPI service mapping ORM models to UI's 36-field TypeScript Source interface
- /api/sources, /api/sources/{slug}, /api/health, /api/playground/query
- Playground: retrieves via core library, generates via cluster's 120B LLM (vLLM)
- Returns MCP endpoint URL for "Copy MCP Config" button

**UI (live instance):**
- Data fetching layer: catalogApi.ts, useSources/useSource hooks with MOCK_SOURCES fallback
- 4 pages rewired: CatalogPage, SourceDetailPage, PlaygroundPage, AdminPage
- nginx-live.conf proxies /api/ to BFF service
- Separate Containerfile.live preserves existing mock demo
- Fixed CatalogPage redundant status filter hiding curated sources from admin
- ActionBar "Copy MCP Config" uses real cluster URL

**AutoRAG evaluation:**
- 50-question clinical QA dataset (17 CPGs, 5 query types, lay + clinical language)
- Swept Token/Sentence x 512/1024 x 0/64 overlap
- Token-512-0 won (recall@5=0.68); Sentence-512 scored 0.44 (24pp worse)
- Overlap provided no retrieval benefit — removed, saving 15% chunk index size

**Research:**
- FastMCP 4 and MCP 2026-07-28 stateless spec (research-fastmcp4.md)
- AutoRAG for chunking optimization (research-autorag.md)
- PubMedBERT via TEI (not vLLM) for BERT-class models

**Documentation:**
- Onboarding journey (docs/onboarding-journey-va-cpg.md) — 8-step template for future data sources
- Claude Code MVP setup guide
- 4 design principles captured in memory

## Verification & confidence

- MCP server exercised via mcp-test-mcp: 7 test scenarios (list, describe, retrieve, error paths, lay language, cross-CPG)
- Playground tested in Chrome: real retrieval + 120B LLM generation, cited clinical answers
- UI catalog card shows real data (eval score 0.68, PubMedBERT recipe, 52 docs)
- 109 unit tests pass; TypeScript compiles clean
- Confidence: **high** for MCP server and retrieval pipeline; **medium** for BFF (no unit tests deployed, manual verification only); **medium** for UI (visual verification, no e2e tests)

## Judgment calls & deviations

- FastMCP 4 Depends() doesn't resolve generators — changed to plain function + try/finally session cleanup
- BFF calls core library directly for playground (not MCP server) because MCP 2026-07-28 requires session negotiation that raw HTTP can't do
- Separate model-cache PVCs for MCP server and BFF (RWO can't share across nodes) — deployed TEI as the long-term shared service
- Dropped chunk overlap (64→0) based on AutoRAG evidence — 15% fewer chunks, no retrieval regression

## Backlog delta

Memory: project-mvp-decisions, project-embedding-portability, design-usage-rules-with-data, design-shared-model-serving
Deferred: query rewriter (by design), RAGAS e2e eval pipeline, TEI integration into QueryEmbedder, FIPS-Agents playground agent

## Drift & forward-collisions

- Backward: none (first vertical, no prior issues to decay)
- Forward: the shared TEI embedding service pattern anticipates the multi-source architecture; the usage_rules system anticipates the data governance layer

## For the reviewer

- Sanity-check: the BFF playground calls retrieval_query() in-process (needs sentence-transformers in the container). Should switch to calling TEI endpoint or MCP server once session negotiation is sorted.
- Thin verification: BFF has no deployed unit tests — only the MCP server tests exist. The BFF mapper (mappers.py) is complex and undertested.
- Wants guidance: is the `usage_rules` JSON column on Source the right home, or should it be a separate table for versioning/auditability?

## Risks / watch-fors

- FastMCP 4 is beta (4.0.0b1) — API may shift. Pin version.
- The gpt-oss-120b cluster is a sandbox — it may be reclaimed. Data is in PVCs but the namespace could be deleted.
- BFF + MCP server both load PubMedBERT in-process — wastes memory. TEI shared service deployed but not wired in yet.
