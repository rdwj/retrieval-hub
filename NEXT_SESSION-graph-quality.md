# Next Session -- Graph Quality and Usability

## Epic: Make graph sources as useful as SNOMED-CT

Feedback from a multi-source hypertension treatment plan session revealed
that SNOMED-CT chunks work well (rich, self-contained, retrieve-only) while
FHIR and Hetionet chunks require workarounds (multiple refine calls, timeouts,
post-processing). This epic brings all graph sources up to SNOMED-CT's
quality standard and adds the API features needed for targeted graph queries.

Issues: #40, #41, #42, #43, #44, #45, #46

## Phase 1 — Infrastructure + chunk quality (data layer)

Fix the foundation: make Memgraph reliable and make chunk text
self-sufficient so retrieve alone covers 80%+ of use cases.

### 1a. Memgraph PVC migration (#40)
Replace emptyDir with PVC. Small, high-value reliability fix.
Must be done first since phases 1b-1c require re-ingestion.

### 1b. Hetionet chunk text enrichment (#44, #46)
Update `render_hetionet_entity()` to include immediate edges and neighbor
names in chunk text. Currently renders "Compound: Hydrochlorothiazide."
with no relationships. Should render like SNOMED-CT: entity name +
treats + palliates + targets + resembles + anatomy. Re-ingest after.

### 1c. FHIR Observation component promotion (#41, #46)
Two options from the issue: promote each component to its own graph node
(more flexible) or include component values inline in the panel node text
(simpler). The simpler approach (inline values in chunk text) fits the
"retrieve-sufficient" pattern better and doesn't require graph schema
changes. Update `convert_fhir_to_graph.py` to extract component values
and `render_fhir_entity()` to include them. Re-ingest after.

## Phase 2 — Bounded graph traversal (#45)

Add `max_depth`, `edge_types`, and `max_nodes` parameters to
`graph_traverse_from_seed`. Currently returns the entire reachable
subgraph regardless of the `window` parameter. The Hetionet timeout
is a direct consequence of unbounded traversal on a dense graph.

This is a GraphAdapter + Memgraph query change. The MCP refine tool
already accepts arbitrary kwargs that pass through to the adapter.

## Phase 3 — Retrieve filtering (#42, #43)

Add metadata filtering to the retrieve API. Two complementary filters:

- **doc_section filter** (#43): restrict by entity type (Observation,
  Condition, MedicationRequest, etc.). Already stored in chunks as
  `doc_section`. Needs pgvector WHERE clause on the existing column.

- **Entity-scope filter** (#42): restrict to a specific subgraph
  (e.g., one patient's data). Could use `doc_title` prefix matching
  or a new metadata column. Needs design — this is the hardest issue
  in the epic.

## Sequencing

Phase 1 first (1a → 1b → 1c, sequential because of re-ingestion).
Phase 2 can start after 1a (Memgraph PVC). Phase 3 is independent
of 1 and 2 but benefits from 1b/1c (better chunks reduce the need
for filtering workarounds).

**Next session:** Phase 1 (all three parts). 1a is ~30 min, 1b is
~1-2 hours (renderer + re-ingest), 1c is ~1-2 hours (converter +
renderer + re-ingest). If time permits, start Phase 2.

## Definition of done

- Memgraph data survives pod restart (#40)
- Hetionet chunks include relationship edges (#44)
- FHIR BP panel chunks include systolic/diastolic values (#41)
- Graph traverse respects depth/edge-type/max-nodes bounds (#45)
- Retrieve supports doc_section filtering (#43)
- Entity-scope filtering designed and at least prototyped (#42)
- #46 (umbrella) closeable because individual issues are resolved

## Session start protocol

- `oc get pods --context=gpt-oss-120b -n retrieval-hub` — cluster healthy?
- `oc get pvc --context=gpt-oss-120b -n retrieval-hub` — existing PVCs?
- `oc get statefulset memgraph -o yaml --context=gpt-oss-120b -n retrieval-hub`
  — read current manifest before modifying
- Port-forwards: Memgraph (7687), Postgres catalog (5434), Postgres
  vectors (5433), TEI embedding (8090)
- Rules with history:
  - TEI batch_size=2, 10-retry backoff, self-healing port-forward
  - Use `127.0.0.1` not `localhost` for port-forwarded connections
  - Metadata-only changes use SQL UPDATEs, not full re-ingestion

## Watch out for

- Re-ingestion of FHIR (22K nodes) takes 30-60 min through TEI. Plan
  this for the end of the session or run it in background.
- Hetionet re-ingestion is fast (~5 min, 769 nodes).
- Memgraph StatefulSet change will delete the existing pod. Graph data
  must be reloaded after PVC is attached.
- The `window` parameter in graph_traverse_from_seed may already be
  wired but not implemented in the Cypher query — check before adding
  new parameters.
- FHIR component promotion may increase the node count significantly
  if each component becomes its own node. Consider the inline approach
  first.

## If blocked

- If PVC provisioning fails: check StorageClasses with `oc get sc`,
  try a different class or smaller size
- If TEI is unstable during re-ingestion: use local sentence-transformers
  for Hetionet (769 nodes fits easily in local memory)
- If FHIR component data is not in the existing graph source files:
  need to re-run `convert_fhir_to_graph.py` from the raw FHIR bundles
