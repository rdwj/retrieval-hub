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

## Next: Phase 3 — retrieve filtering + forcing-function validation

Add metadata filtering to the retrieve API so agents can scope queries
to specific entity types and patient subgraphs. Then run the forcing-
function query end-to-end to validate that Phases 1-3 together make the
agent experience good.

1. **#43 — doc_section filtering** (mechanical)
   Add a `doc_section` parameter to the MCP `retrieve` tool that becomes
   a WHERE clause on the existing `doc_section` column in pgvector. Same
   threading pattern as `edge_types`/`max_nodes` from Phase 2: MCP tool
   param → `api.py` `query()` → `DocumentAdapter.retrieve()` → SQL.
   Files: `server.py`, `api.py`, `adapters/document.py`, tests.
   FHIR entity types stored in doc_section: Patient, Condition,
   MedicationRequest, Observation, Encounter, Procedure, etc.

2. **#42 — entity-scope filtering** (needs design)
   Restrict retrieve to a specific subgraph (e.g., one patient's data).
   Design options: (a) `doc_title` prefix matching (cheap but fragile),
   (b) new `doc_scope` metadata column populated during ingestion with a
   scope key like patient UUID, (c) graph-based scoping via Memgraph
   traversal to find all entity_ids connected to a seed, then filter
   pgvector by those IDs. Option (c) is the most powerful but crosses
   adapter boundaries. Start by examining FHIR edge structure to see
   which option fits the data.

3. **Forcing-function query** (validation gate)
   After #43 and #42, run the treatment plan query against the live MCP
   server. This touches 5 sources (FHIR, VA CPG, SNOMED-CT, Hetionet,
   PubMed) and requires scoping, cross-source bridging, and formatted
   output. The result tells us whether Phase 4 (agent ergonomics) is
   needed or if the tools are already good enough.

**Sequencing.** #43 first (straightforward, unblocks testing of scoping
patterns). #42 design second (informed by what #43 reveals about the
query patterns agents actually use). Forcing-function query last.

**Constraints for the session:**
- No re-ingestion needed — this is API-layer work on existing data
- #42 design should be decided in-session, not deferred to the file

**Session start protocol:**
- Premise checks: `oc get pods --context=gpt-oss-120b -n retrieval-hub`
  (cluster healthy?); `git log --oneline -5` (no surprise merges?);
  quick MCP `retrieve` query against fhir-hypertension to confirm the
  re-ingested data is live and includes component values
- Rules with history:
  - Use `127.0.0.1` not `localhost` for port-forwarded connections
  - Metadata-only changes use SQL UPDATEs, not full re-ingestion
- Stop-and-ask before: any schema changes to pgvector tables (adding
  columns affects all sources); any changes to the FHIR graph converter
  that would require re-ingestion
- Close ritual: session summary + update this file

## Remaining epic phases

### Phase 4 — Agent ergonomics

Make the platform easy for agents to use for multi-source synthesis
without trial-and-error. The forcing function is the treatment plan
query above: it touches 5 sources and requires scoping, cross-source
bridging, and formatted output.

#### 4a. Data card enrichment for agent discoverability
Each source's `description_long` and `sample_prompts` should tell an
agent *when* to use it, *what* it contains, and *how* to query it
effectively. Current descriptions are factual but don't guide
multi-source workflows.

#### 4b. CLAUDE.md / agent integration guidance
Write RetrievalHub-specific guidance that an agent consumes at session
start. Content: source catalog overview, which sources to use for which
question types, multi-source workflow patterns, common pitfalls.

#### 4c. Multi-source workflow patterns
Document and test the canonical multi-source workflows:
- Patient-centered clinical report (FHIR + VA CPG + SNOMED-CT + PubMed)
- Drug interaction lookup (Hetionet + SNOMED-CT)
- Evidence-based treatment plan (VA CPG + PubMed + ClinicalTrials)

## Definition of done

- ~~Memgraph data survives pod restart (#40)~~ done
- ~~Hetionet chunks include relationship edges (#44)~~ done
- ~~FHIR BP panel chunks include systolic/diastolic values (#41)~~ done
- ~~Graph traverse respects depth/edge-type/max-nodes bounds (#45)~~ done
- Retrieve supports doc_section filtering (#43)
- Entity-scope filtering designed and at least prototyped (#42)
- #46 (umbrella) closeable because individual issues are resolved
- An agent can complete the forcing-function query (treatment plan
  from 5 sources) using only RetrievalHub MCP tools, without
  workarounds, timeouts, or data gaps
- Agent integration guidance tested and documented (CLAUDE.md
  entries or equivalent)

## What landed last session (2026-09-03)

Phase 1 complete + Phase 2 complete. All code committed, Hetionet and
FHIR re-ingested with enriched chunk text, bounded traversal deployed.
See `session-summaries/2026-09-03-graph-quality-phase1-2.md`.

**Closed:** #40 — Memgraph PVC, #41 — FHIR Observation components,
#44 — Hetionet chunk enrichment, #45 — bounded graph traversal

**Follow-ups filed:** none (bugs found during re-ingestion were fixed
in-session: httpx.ReadError retry, TEI port-forward watchdog pattern)

## Watch out for

- The `doc_section` filter for #43 needs to work for ALL source families,
  not just graph — document sources also have doc_section (section headers).
  Make it a general retrieve parameter, not graph-specific.
- #42 entity-scope filter design has three options with different tradeoffs.
  Don't start implementing before choosing — pick the option in a design
  discussion, then build.
- Port-forwards: Memgraph uses 17687 (7687 taken by local Podman gvproxy).
  TEI embedding-nomic uses port 8080, not 80.

## If blocked

- If #42 design is unclear after examining the FHIR edge structure, skip
  to the forcing-function query first — it will reveal what scoping an
  agent actually needs, which informs the design.
- If cluster is down, Phase 3 work is all local code + tests. Can develop
  and test without cluster access, then deploy later.
