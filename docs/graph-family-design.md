# Graph Family Design

Design doc for the graph data family in RetrievalHub. This is an opinionated
design that resolves the architectural questions raised in the spike plan.
It covers backend choice, chunk representation, retrieval and refinement
strategies, ingestion shape, and cross-dataset participation.

## Context

RetrievalHub has four planned data families: document, tabular, process, and
graph. The first three are implemented. Graph sources represent knowledge that
is inherently relational: ontologies (SNOMED-CT), patient records (FHIR),
drug-gene interactions, and similar datasets where entities are connected by
typed relationships and retrieval benefits from traversing those relationships.

The GraphRAG literature (Neo4j manifesto, Microsoft GraphRAG) identifies graph
retrieval as complementary to vector search, not a replacement. Vector search
finds semantically similar text (the entry point); graph traversal expands the
result set by following entity relationships (the context expansion). This
two-phase pattern maps directly to RetrievalHub's existing `retrieve()` +
`refine()` adapter contract.

## Backend choice: Memgraph

**Decision: use Memgraph Community Edition as the graph backend.**

### Why not PostgreSQL + Apache AGE

AGE is operationally simplest (runs on our existing Postgres), but it fails on
three counts that matter:

- **Incomplete Cypher.** AGE implements a subset of openCypher wrapped in SQL
  (`SELECT * FROM cypher('g', $$ ... $$) AS (r agtype)`). This is a different
  query paradigm, not portable Cypher. Core DML works, but path expressions,
  list comprehensions, and several string/list functions are missing.
- **No async Python driver.** `apache-age-python` is psycopg2-only. We would
  need a custom AGType parser over asyncpg. The MCP server is async.
- **No credibility add.** "Postgres with a graph extension" does not strengthen
  the platform story. A native graph database does.

AGE may become viable when PostgreSQL 19 ships SQL/PGQ (the ISO graph query
standard), but that is future-state.

### Why not Neo4j Community

Neo4j is the industry standard and has the strongest ecosystem. However:

- **Licensing risk.** Community Edition uses AGPLv3 + Commons Clause. The
  Commons Clause restricts "selling" the software, and there is active Ninth
  Circuit litigation (Neo4j v. Suhy) about whether these restrictions are
  enforceable alongside the AGPL. For an enterprise Red Hat deployment, this
  creates procurement and legal review overhead.
- **Offline-only backup** in Community Edition (must stop the database to
  back up). Online backup requires Enterprise ($3K-6K/core/year).
- **Single-database limitation** in Community. Fine for our scale, but a
  constraint if we ever want tenant isolation.

### Why Memgraph

- **Cypher portability.** Memgraph implements openCypher with ~95% DML
  compatibility with Neo4j. Core operations (MATCH, CREATE, MERGE, WITH,
  RETURN) are identical. If we ever need to migrate to Neo4j, the Cypher
  queries port with minor index/constraint syntax changes. The reverse
  (Neo4j to Memgraph) is harder because of Neo4j proprietary extensions
  (APOC, GDS). Starting with Memgraph keeps the exit door open.
- **Async Python via Bolt.** Memgraph speaks the Bolt protocol. The `neo4j`
  Python driver (6.2.0, native async via `AsyncGraphDatabase`) works against
  Memgraph unchanged. This is a mature, production-quality driver.
- **Built-in vector search.** Memgraph has HNSW vector indexes via USearch,
  supporting both node and edge properties. We will not use this for primary
  retrieval (pgvector handles cross-source RRF), but it is available for
  graph-internal similarity queries if needed.
- **In-memory performance.** For 1K-100K nodes, Memgraph's in-memory C++
  engine provides fast traversals with a modest memory footprint (1-2 Gi pod).
- **OpenShift deployment.** Helm chart with documented OpenShift UID/GID
  overrides. Runs non-root (UID 101). Requires disabling the `init-sysctl`
  container in restricted SCCs.
- **BSL 1.1 licensing.** Not OSI open-source, but pragmatically fine for
  internal platform use. RetrievalHub is a retrieval platform, not a
  competing graph database product. Each BSL version converts to Apache 2.0
  after four years.
- **Snapshot/WAL backup.** Online snapshots and WAL persistence to PVC.
  Set `terminationGracePeriodSeconds` high enough for on-exit snapshot.

### Operational notes

- **Container image is Debian-based**, not UBI. If strict UBI-only policy
  applies, we would need a custom build. For internal platform use, the
  official Debian image is acceptable.
- **Snapshot version coupling.** Memgraph snapshots and WAL are
  version-specific. Upgrades require dump/restore, not in-place upgrade.
  Document in ops runbook.
- **Sizing.** For our target datasets (SNOMED-CT hypertension subset: ~5K
  nodes; FHIR 50 patients: ~2K nodes), a 1 Gi pod is sufficient. Budget 2 Gi
  for headroom.

## Chunk representation: entity-centric with relationship context

Graph sources produce three types of retrievable units:

### 1. Entity chunks

Each graph node becomes a chunk. The chunk text is a rendered description of
the entity and its immediate properties:

```
Entity: Essential Hypertension (SNOMED-CT: 59621000)
Type: Clinical Finding
Properties:
  - Definition: A disorder characterized by an elevation of systolic
    and/or diastolic blood pressure
  - Finding site: Systemic arterial structure
  - Associated morphology: Hyperplasia
```

Entity chunks are embedded into pgvector and participate in vector ANN
retrieval alongside document and tabular chunks. The entity's graph identity
(node ID, entity type, source) is stored as chunk metadata.

### 2. Relationship chunks

Edges are not individually embedded. Instead, relationships are rendered as
context during `refine()`. When refine traverses from a seed entity, it
collects the entity's relationships and renders them as structured text:

```
Essential Hypertension (59621000)
  --[IS_A]--> Hypertensive disorder (38341003)
  --[FINDING_SITE]--> Systemic arterial structure (51114001)
  --[ASSOCIATED_MORPHOLOGY]--> Hyperplasia (76197007)
  <--[MAY_TREAT]-- Lisinopril (386873009)
  <--[MAY_TREAT]-- Amlodipine (386864001)
```

This keeps the embedding space clean (entity descriptions are better
embedding targets than relationship triples) while preserving full graph
structure for context expansion.

### 3. Community summaries (future enhancement)

Pre-computed summaries of densely connected subgraphs. These are generated
by running community detection on the graph and summarizing each community
into a single chunk. Useful for broad thematic queries ("What are the major
drug classes for hypertension management?"). Not in scope for the initial
implementation.

## Retrieval strategy

Graph sources use the existing `retrieve()` path with no modifications.
Entity chunks are embedded in pgvector and searched via vector ANN, exactly
like document or tabular chunks. Graph sources participate in cross-source
RRF through their entity embeddings.

The `RetrievalPattern.GRAPH_TRAVERSE_FROM_SEED` pattern applies to the
`refine()` phase, not `retrieve()`.

## Refine strategy: graph_traverse_from_seed

This is the core new capability. When an agent calls `refine()` on a graph
chunk, the GraphAdapter:

1. **Identifies the seed entity.** The chunk's metadata contains the entity
   ID (Memgraph node ID or source-native ID like SNOMED-CT concept code).

2. **Traverses N hops.** Executes a Cypher query against Memgraph:
   ```cypher
   MATCH (seed)-[r*1..2]-(neighbor)
   WHERE seed.entity_id = $seed_id AND seed.source_slug = $source_slug
   UNWIND r AS rel
   WITH DISTINCT startNode(rel) AS s, rel, endNode(rel) AS e
   RETURN s.entity_id, s.name, type(rel), e.entity_id, e.name
   ```
   The `window` parameter on `refine()` controls hop depth (default: 2).
   `UNWIND` + `DISTINCT` deduplicates nodes visited via multiple paths,
   which is common in dense graphs (Hetionet nodes can have 1000+ edges).

3. **Bounds output to token budget.** The `max_context_tokens` parameter
   on `refine()` limits the rendered subgraph size. The adapter counts
   tokens as it renders nodes and relationships, stopping when the budget
   is reached. Nodes are prioritized by hop distance (closer nodes first),
   then by edge count (hubs last, to avoid consuming the budget on a
   single high-degree node). If `max_context_tokens` is None, a default
   of 2048 tokens applies.

4. **Renders the subgraph.** The traversed subgraph is serialized as
   structured text showing the seed entity, its relationships, and
   neighboring entities with their properties.

5. **Returns RefineOutput.** The rendered subgraph becomes the `context`
   field. The `chunks` field contains the neighboring entity chunks
   (retrieved from pgvector by their entity IDs) for downstream use.

### Refine strategy: path_between (future)

A second refine strategy that finds the shortest path between two entities
identified in the initial retrieval results. Useful when the agent has two
entity hits and wants to understand how they connect:

```cypher
MATCH path = shortestPath((a)-[*..5]-(b))
WHERE a.entity_id = $entity_a AND b.entity_id = $entity_b
RETURN path
```

Not in scope for initial implementation; the `graph_traverse_from_seed`
strategy covers the primary use case.

### Interface considerations

The current `refine()` signature uses `doc_title` and `chunk_index` to
identify the seed chunk. For graph sources, `doc_title` maps to the entity
identifier (concept code, patient ID) and `chunk_index` to 0 (entities are
single-chunk). The `strategy` parameter selects `graph_traverse_from_seed`.

This is a pragmatic mapping that avoids changing the base class signature.
If the impedance mismatch becomes awkward during implementation, the base
class can be extended with an optional `entity_id` parameter.

The GraphAdapter rejects the `"adjacent"` strategy (the base class default)
with a clear error message directing callers to use
`"graph_traverse_from_seed"`. Unknown strategies also raise errors.

## Physical index architecture

A graph source has **two** physical backends:

- **pgvector** for entity chunk embeddings (used by `retrieve()` and
  cross-source RRF)
- **Memgraph** for graph structure (used by `refine()`)

The `physical_index` on the source record points to the pgvector index (this
is the existing pattern for all adapter families). The Memgraph connection is
configured as a platform-level service, not per-source -- all graph sources
share a single Memgraph instance, with source isolation via a `source_slug`
property on every node and edge.

```
physical_index (pgvector)        Memgraph
┌─────────────────────┐         ┌──────────────────────┐
│ entity chunks with  │         │ nodes with entity_id,│
│ embeddings, scored  │────────▶│ typed edges,         │
│ by vector ANN       │ refine  │ source_slug labels   │
└─────────────────────┘         └──────────────────────┘
```

The bridge between pgvector and Memgraph is the `entity_id` stored as
metadata on each chunk in pgvector and as a property on each node in
Memgraph.

### Chunk metadata schema

Entity chunks in pgvector carry these metadata fields (stored in the
chunk's JSON metadata column alongside existing fields like `doc_title`,
`doc_section`):

| Field | Type | Description |
|---|---|---|
| `entity_id` | string | Source-native identifier (SNOMED code, FHIR resource ID) |
| `entity_type` | string | Node type label (Finding, Patient, Compound) |
| `source_slug` | string | Source slug for Memgraph isolation |
| `hop_degree` | int | Number of direct edges on this entity (for ranking) |

The `entity_id` + `source_slug` pair is the join key between pgvector
and Memgraph.

### Connection management

The Memgraph async driver (`neo4j.AsyncGraphDatabase`) is initialized
once at MCP server startup, using the Bolt URI from platform
configuration (env var `MEMGRAPH_BOLT_URI`, default
`bolt://memgraph:7687`). The driver manages its own connection pool
(default pool size: 100, max connection lifetime: 1 hour).

Each `refine()` call acquires a session from the pool, runs a read
transaction, and releases the session. No long-lived sessions.

```python
async with self._driver.session(database="memgraph") as session:
    result = await session.run(cypher_query, parameters)
    records = await result.values()
```

### Split-backend failure handling

The two backends can fail independently:

- **Memgraph down, pgvector up:** `retrieve()` works normally (pgvector
  only). `refine()` raises `GraphBackendUnavailableError` with a message
  indicating the graph backend is unreachable. The MCP server returns a
  structured error; the agent can still use the retrieve results without
  graph expansion.
- **pgvector down, Memgraph up:** `retrieve()` fails (no vector search).
  `refine()` cannot be called without prior retrieve results. Standard
  pgvector error handling applies.
- **Ingestion partial write:** The ingestion pipeline writes to Memgraph
  first (graph structure), then pgvector (embeddings). If pgvector fails
  after Memgraph succeeds, the Memgraph nodes exist but have no
  corresponding embeddings. Re-running ingestion is idempotent (checks
  for existing nodes by source_slug before inserting) and will retry the
  pgvector writes.

## Cross-dataset RRF participation

Graph sources participate in multi-source RRF identically to other families:

1. **retrieve()** runs vector ANN over all sources' pgvector indexes. Entity
   chunks from graph sources compete with document chunks, tabular chunks,
   and process chunks on embedding similarity.

2. **RRF scoring** merges ranked lists from different sources using
   reciprocal rank fusion. Graph entity chunks get RRF scores like any other
   chunk.

3. **refine()** is source-specific. When the agent refines a graph chunk,
   the GraphAdapter uses Memgraph for graph traversal. When the agent refines
   a document chunk, the DocumentAdapter uses adjacent-chunk or section
   strategies. The agent does not need to know which backend each source
   uses.

This design means graph sources do not require a different retrieval pattern
at the `retrieve()` level. The graph structure only comes into play at
`refine()` time, which is already per-adapter.

### Embedding quality for entity chunks

Entity descriptions must be written to embed well. A bare concept code
("59621000") embeds poorly. A rendered description ("Essential Hypertension:
a disorder characterized by an elevation of systolic and/or diastolic blood
pressure, affecting systemic arterial structure") embeds well because it
overlaps with the natural language queries agents will send.

The `chunk_graph_data()` function must render entity descriptions that are
natural-language-rich, not just property dumps. For SNOMED-CT, this means
including the fully specified name, definition (if available), and key
relationship context. For FHIR, this means rendering patient conditions,
medications, and observations as readable clinical text.

## Ingestion shape

### Input format

Graph sources accept two input shapes:

**Structured graph files (primary).** Nodes and edges as separate CSV/TSV
files with headers. This is the format for SNOMED-CT (concepts +
relationships) and FHIR (resources + references):

```
# nodes.tsv
entity_id    entity_type    name                   properties_json
59621000     Finding        Essential Hypertension  {"definition": "...", "finding_site": "..."}

# edges.tsv
source_id    target_id    relationship_type    properties_json
59621000     38341003     IS_A                 {}
386873009    59621000     MAY_TREAT            {"evidence_level": "high"}
```

**Property graph JSON (alternative).** A single JSON file with nodes and
edges arrays. Useful for exports from existing graph databases or APIs.

### chunk_graph_data() pipeline

```
Input files (nodes.tsv, edges.tsv)
    │
    ▼
Parse nodes → create Memgraph nodes with properties
    │
    ▼
Parse edges → create Memgraph edges with types
    │
    ▼
Render entity descriptions → natural-language text per entity
    │
    ▼
Embed entity descriptions → store in pgvector as entity chunks
    │
    ▼
Write build_metadata (entity_count, edge_count, graph_density)
```

The pipeline writes to both Memgraph (graph structure) and pgvector
(entity embeddings) in a single pass. Idempotency: the pipeline checks for
existing nodes/edges by source_slug before inserting.

### Source-specific rendering

Each graph source type needs a rendering function that converts raw node
properties into embeddable text. Examples:

- **SNOMED-CT:** Fully specified name + definition + finding site + associated
  morphology, rendered as clinical text
- **FHIR Patient:** Demographics + active conditions + current medications +
  recent observations, rendered as a clinical summary
- **Drug-Gene:** Drug name + gene target + interaction type + evidence level,
  rendered as a pharmacogenomics statement

These renderers are source-specific, not adapter-generic. The GraphAdapter
provides the framework; each source's `chunk_config` specifies which
renderer to use.

## Datasets for implementation

### SNOMED-CT hypertension subset

Source: SNOMED-CT US Edition from NLM.
Subset: Hypertension concept hierarchy -- codes, descriptions, IS-A
relationships, FINDING-SITE, ASSOCIATED-MORPHOLOGY, MAY-TREAT.
Expected size: ~5,000 nodes, ~8,000 edges.
Storage: `retrieval-hub-data-sources/snomed-ct-hypertension/`

### Synthetic FHIR records

Source: Synthea-generated synthetic patients.
Scope: 50 patients with hypertension-related conditions, medications,
and observations.
Expected size: ~2,000 nodes (Patient, Condition, Medication,
Observation, Encounter), ~3,000 edges (references between resources).
Storage: `retrieval-hub-data-sources/fhir-hypertension/`

### Hetionet (backup / third dataset)

Source: https://github.com/hetio/hetionet (CC0, public domain).
A heterogeneous biomedical knowledge graph integrating 29 public sources.
47,031 nodes across 11 types (Compound, Disease, Gene, Anatomy, Biological
Process, Cellular Component, Molecular Function, Pathway, Pharmacologic
Class, Side Effect, Symptom). 2,250,197 edges across 24 relationship types
(treats, palliates, associates, upregulates, downregulates, binds, etc.).
Available as TSV node/edge files via git clone.
Storage: `retrieval-hub-data-sources/hetionet/`

Hetionet is the preferred backup because of its zero-friction download,
clean graph-native format, direct hypertension relevance, and rich
heterogeneous schema ideal for demonstrating multi-hop graph traversal.
DGIdb was too narrow (single relationship type). DisGeNET and DrugBank
have licensing barriers.

## Decisions rejected

### Embedding relationships individually

Each edge rendered as "A --[REL]--> B" and embedded as its own chunk. Rejected
because: relationship triples embed poorly (too short, too structured for
semantic similarity), and it doubles the embedding count without proportional
retrieval quality gain. Relationships are better served as context during
refine().

### Using Memgraph for primary vector search

Memgraph has USearch-based HNSW indexes, so entity embeddings could live
entirely in Memgraph. Rejected because: cross-source RRF requires all
sources' embeddings in a single vector store (pgvector). Graph-only vector
search would isolate graph sources from RRF, requiring a separate retrieval
path.

### Community detection in initial implementation

Community summaries (Microsoft GraphRAG style) require running Leiden or
Louvain on the graph, then LLM-summarizing each community. This is valuable
for broad thematic queries but adds complexity (LLM calls at ingest time,
community maintenance on graph updates). Deferred to a future enhancement
after the basic entity-centric approach is proven.

### PostgreSQL + AGE for "operational simplicity"

See backend choice section. The Cypher subset, lack of async driver, and
missing credibility story outweigh the operational benefit of staying on
existing Postgres.
