# Next Session -- Graph Quality and Usability

## Epic: Make graph sources as useful as SNOMED-CT

Feedback from a multi-source hypertension treatment plan session revealed
that SNOMED-CT chunks work well (rich, self-contained, retrieve-only) while
FHIR and Hetionet chunks require workarounds (multiple refine calls, timeouts,
post-processing). This epic brings all graph sources up to SNOMED-CT's
quality standard, adds the API features needed for targeted graph queries,
and makes the whole platform ergonomic for agents doing multi-source work.

**Forcing-function query:** "Pick a patient from the list of hypertension
patients, write up a treatment plan based on the VA CPGs, enrich it with
SNOMED-CT and PubMed data, and produce a nice report." An agent should be
able to answer this from RetrievalHub alone, without fighting the tools.

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

## Phase 4 — Agent ergonomics

Make the platform easy for agents to use for multi-source synthesis
without trial-and-error. The forcing function is the treatment plan
query above: it touches 5 sources and requires scoping, cross-source
bridging, and formatted output.

### 4a. Data card enrichment for agent discoverability
Each source's `description_long` and `sample_prompts` should tell an
agent *when* to use it, *what* it contains, and *how* to query it
effectively. Current descriptions are factual but don't guide
multi-source workflows. Add sample prompts that demonstrate
cross-source patterns (e.g., "retrieve a FHIR patient, then look up
their conditions in SNOMED-CT, then find treatment guidelines in
VA CPG").

### 4b. CLAUDE.md / agent integration guidance
Write RetrievalHub-specific guidance that an agent consumes at session
start. Content: source catalog overview, which sources to use for which
question types, multi-source workflow patterns, common pitfalls (e.g.,
use doc_section filter for FHIR, use graph refine for relationship
traversal). Start by manually testing what guidance an agent needs,
then consider a `retrieval-hub config init` CLI tool that writes the
guidance to the consuming project's CLAUDE.md.

### 4c. Multi-source workflow patterns
Document and test the canonical multi-source workflows:
- Patient-centered clinical report (FHIR + VA CPG + SNOMED-CT + PubMed)
- Drug interaction lookup (Hetionet + SNOMED-CT)
- Evidence-based treatment plan (VA CPG + PubMed + ClinicalTrials)

Test these against the live MCP server and iterate on the guidance
until an agent can complete them without workarounds.

## Sequencing

Phase 1 first (1a → 1b → 1c, sequential because of re-ingestion).
Phase 2 can start after 1a (Memgraph PVC). Phase 3 is independent
of 1 and 2 but benefits from 1b/1c (better chunks reduce the need
for filtering workarounds). Phase 4 comes last — it's the validation
layer that proves the earlier phases actually made the agent experience
good. Run the forcing-function query after each phase to measure
progress.

**Next session:** Re-run FHIR re-ingestion (1c data op — code is
committed, just needs embedding). Then Phase 3 (retrieve filtering).
Phase 2 code is also committed and deployed.

### Checkpoint (2026-09-02)

Phase 1 and Phase 2 code changes committed. Hetionet re-ingested and
verified via MCP retrieve (chunks now include relationships). FHIR
re-ingestion needs one more run — first attempt used stale Python
bytecode, producing chunks without component values. Command:

    PYTHONDONTWRITEBYTECODE=1 MEMGRAPH_BOLT_URI=bolt://127.0.0.1:17687 \
      python -B scripts/ingest_fhir_hypertension.py \
      --embedding-endpoint http://127.0.0.1:8090

Needs port-forwards: Memgraph (17687→7687), Postgres catalog (5434),
Postgres vectors (5433), TEI embedding (8090). Takes ~21 min.

Key finding: Hetionet renderer was completely broken — abbreviated
edge type codes ("CtD") never matched the full-description data
("Compound - treats - Disease"), so zero relationships were rendering.
Fixed and verified.

## Definition of done

- Memgraph data survives pod restart (#40)
- Hetionet chunks include relationship edges (#44)
- FHIR BP panel chunks include systolic/diastolic values (#41)
- Graph traverse respects depth/edge-type/max-nodes bounds (#45)
- Retrieve supports doc_section filtering (#43)
- Entity-scope filtering designed and at least prototyped (#42)
- #46 (umbrella) closeable because individual issues are resolved
- An agent can complete the forcing-function query (treatment plan
  from 5 sources) using only RetrievalHub MCP tools, without
  workarounds, timeouts, or data gaps
- Agent integration guidance tested and documented (CLAUDE.md
  entries or equivalent)

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
