# Next Session -- Self-Serve Onboarding

## Epic: Auth, AutoRAG-style Onboarding, and New Data Families

Build the auth layer, a self-serve source onboarding pipeline, and onboard
new datasets that exercise the four unrepresented source families (tabular,
graph, process, external). The self-serve pipeline replaces the idea of
adopting an external AutoRAG framework by wrapping our own eval sweep
infrastructure into an onboarding workflow.

## What landed

- **Phase 1 (Auth): Complete.** See `session-summaries/
  2026-08-27-self-serve-onboarding-auth-and-pipeline.md`.

- **Phase 2 (Onboarding pipeline): Complete.** Full eval sweep proven
  end-to-end. `--skip-eval` fast path added. Data card auto-population
  wired: `describe_source` returns `eval_baseline` and `chunk_config`
  from `build_metadata`. Backfilled for `aircraft-sb-test`. See
  `session-summaries/2026-08-30-self-serve-onboarding-proving-run-completion.md`
  and `session-summaries/2026-08-31-self-serve-onboarding-phases-2-3a-3b.md`.

- **Phase 3a (Tabular): Complete.** 200 ClinicalTrials.gov hypertension
  studies downloaded. TabularAdapter with `table_context` refine. 307
  chunks ingested as `clinicaltrials-hypertension`, CURATED.

- **Phase 3b (Process): Complete.** ProcessAdapter with procedure-aware
  chunking. 2,456 chunks ingested as `aircraft-sb-process`, CURATED.
  Procedure refine tested on SB 1006B (17 chunks, correct step ordering).

## Next: Graph family spike -- design + dataset acquisition

A design-only spike session. No adapter code, no ingestion, no prototype.
The goal is a written design doc that resolves the architectural questions
for graph-family sources and two acquired datasets ready for the
implementation session.

1. **Read the Neo4j GraphRAG manifesto.**
   https://neo4j.com/blog/genai/graphrag-manifesto/
   Extract the key patterns: how they represent graph structure for LLM
   retrieval, entity-vs-relationship-vs-community chunking, traversal
   strategies, and where pgvector fits vs. where a native graph DB is
   needed. Summarize what applies to RetrievalHub's adapter model and
   what doesn't (we're a retrieval platform, not an agent framework).

2. **Design the GraphAdapter.**
   Resolve these questions and write a design doc at `docs/graph-family-design.md`:
   - **Chunk representation:** entity-as-chunk (each node is a chunk with
     its properties as text) vs. relationship-as-chunk (each edge rendered
     as "A --rel--> B" with context) vs. community/subgraph-as-chunk.
     Consider hybrid approaches.
   - **Refine strategy:** how does `refine` traverse the graph from a
     seed chunk? Adjacent nodes? N-hop neighborhood? Path between two
     hits? How does this map to SQL queries on pgvector (if it can), or
     does graph refine require a graph-native backend?
   - **Backend evaluation:** can graph-family sources live in pgvector
     with edge metadata (Apache AGE extension, pg_graph, or a hand-rolled
     adjacency table), or do they need a dedicated graph DB? Evaluate:
     (a) PostgreSQL + Apache AGE (graph queries on existing infra),
     (b) Memgraph (lightweight, Cypher-compatible, easy to containerize),
     (c) Neo4j (full-featured but heavier operational footprint).
     Consider what RetrievalHub actually needs: if refine only does 1-2
     hop traversals from a seed, Postgres with an adjacency table may
     suffice. If we need pathfinding or community detection, a graph DB
     earns its keep. The spike should produce a recommendation with
     tradeoffs, not just "use Neo4j."
   - **Ingestion shape:** what does the input data look like? Nodes +
     edges as separate files? A single graph export format (RDF, JSON-LD,
     property graph JSON)? How does `chunk_graph_data()` work?
   - **Cross-dataset reasoning:** how do graph sources participate in
     multi-source RRF with vector sources? Is the embedding of a rendered
     node/edge sufficient, or do graph sources need a different retrieval
     pattern entirely?

3. **Acquire SNOMED-CT dataset.**
   SNOMED-CT is available via the UMLS Metathesaurus (requires a free
   UMLS account). Download the SNOMED-CT International Edition. For
   the companion repo, extract a relevant subset: the hypertension
   concept hierarchy (codes, descriptions, relationships like IS-A,
   FINDING-SITE, ASSOCIATED-MORPHOLOGY). Store in
   `retrieval-hub-data-sources/snomed-ct-hypertension/` following the
   existing pattern (sources/, extracted/, OVERVIEW.md, download script).

4. **Acquire synthetic FHIR records.**
   Use Synthea (https://github.com/synthetichealth/synthea) or a
   pre-generated FHIR bundle to create synthetic patient records with
   hypertension-related conditions, medications, and observations. These
   are inherently graph-shaped (Patient -> Condition -> Medication ->
   Observation). Store in `retrieval-hub-data-sources/fhir-hypertension/`.

5. **Survey public graph datasets.**
   Evaluate DGIdb (Drug-Gene Interaction Database), DisGeNET, or similar
   public biomedical graphs. Pick one as a third candidate if SNOMED-CT
   or FHIR proves problematic. Document the evaluation in the design doc.

**Sequencing.** Item 1 first (the manifesto shapes the design questions).
Item 2 next (the design doc). Items 3-5 are independent of each other and
can run in parallel after the design is drafted (the design may influence
which subset of SNOMED-CT to extract).

**Constraints for the session:**
- This is a spike. No adapter code, no chunker, no ingestion run. The
  deliverables are: a design doc and two or more datasets in the
  companion repo ready for the implementation session.
- SNOMED-CT download requires a UMLS account. Check if a UMLS API key
  is already configured (memoryhub or env vars). If not, the user will
  need to authenticate manually.
- The design doc should be opinionated, not a survey of all options.
  Pick the approach that fits RetrievalHub's adapter model and explain
  why the alternatives were rejected.

**Session start protocol:**
- Premise checks: verify the 8 existing sources are still in the catalog
  (`SELECT slug, family, status FROM source`). Confirm the companion repo
  has the expected 5 datasets (va-cpg, pubmed-hypertension,
  aircraft-maintenance, tale-of-two-cities, clinicaltrials-hypertension).
  Check that no parallel session created a graph source.
- Rules with history: TEI nomic pod is at 32Gi with `--max-client-batch-size 8`.
  Batch ingestion causes OOM every ~25 minutes; use batch_size=2 with the
  self-healing port-forward watchdog and 10-retry backoff if any embedding
  is needed (it shouldn't be in a spike, but note for awareness). If the
  pod proves unworkable for future ingestion, switching to vLLM for
  embedding is approved.
- Stop-and-ask before: downloading datasets larger than 1GB, creating any
  new database tables or sources in the catalog.

## Remaining epic phases

### Phase 3c -- Graph (implementation session, after spike)

Build GraphAdapter, graph chunker, wire into pipeline and adapter factory.
Ingest SNOMED-CT and FHIR datasets using the design from the spike.
Test graph refine strategy. Use `--skip-eval` for initial ingestion;
pick chunk config from existing eval results (512/0 default).

### Phase 3d -- External (federation to public API)

Integration pattern, not a new data shape. Simplest version: an adapter
that makes HTTP calls instead of pgvector queries. Participates in
multi-source RRF.

**Epic definition of done:** At least 3 of 4 families have a live source
with eval baseline. Onboarding pipeline successfully onboards at least one.
**Status: met.** Process and tabular families are live. The epic DoD is
satisfied; 3c and 3d are extensions that round out the platform.

## What landed last session (2026-08-31)

Phases 2 (data card auto-population), 3a (tabular), and 3b (process)
all completed in one session. See
`session-summaries/2026-08-31-self-serve-onboarding-phases-2-3a-3b.md`.

**Commits:** 81656a3..19ed9bc (main)
- `81656a3` — Data card auto-population (EvalBaseline, ChunkConfig schemas)
- `0563291` — TabularAdapter + tabular chunker + embedding retry resilience
- `19ed9bc` — CLAUDE.md TEI batch embedding lesson learned

**Cluster changes:** TEI nomic pod bumped 8Gi -> 32Gi with
`--max-client-batch-size 8`.

## Watch out for

- TEI CPU memory leak under sustained batch embedding. See CLAUDE.md
  "TEI CPU has a memory leak" lesson. Use batch_size=2, self-healing
  port-forward, and 10-retry backoff for any ingestion run. Consider
  vLLM for embedding if the problem recurs.
- SNOMED-CT licensing: requires a free UMLS account and acceptance of
  the UMLS Metathesaurus License Agreement. Check before attempting
  download.
- The `test_auth_integration.py` MCP test has a pre-existing import
  error (`ModuleNotFoundError: No module named 'tests.test_auth_integration'`).
  Not blocking but should be fixed eventually.

## Open issues this epic addresses

- #24 Keycloak realm and role allowlist example (Phase 1 stretch, deferred)
- #27 Production ingestion runners (Phase 2 via EvalHub, partially advanced
  by pipeline.py)

## Open issues this epic does NOT address

- #31 MCP-level end-to-end eval (eval-convergence epic)
- #29 Elicitation (future epic)
- #25 Operator with CRDs (future)
- #23 Grafana dashboard (future)
- #17 SDK / #18 CLI (future)
