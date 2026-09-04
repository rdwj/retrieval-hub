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

Issues: #40, #41, #42, #43, #44, #45, #46, #47

## EPIC COMPLETE

All definition-of-done items met. See session summary:
`session-summaries/2026-09-04-graph-quality-close-epic.md`

## Previous: Close the epic — fix Patient chunks, automate forcing-function eval, add confidence elicitation

Three items to wrap the epic. The first (#47) is the last blocker for
closing the umbrella issue. The second (#31) captures the manual
forcing-function validation as a repeatable test. The third (#29) is
an agent ergonomics improvement that rounds out the platform's
retrieve-time behavior.

1. **#47 — FHIR Patient chunk text missing conditions and medications** (code fix + re-ingestion)
   `render_fhir_entity` in `src/retrieval_hub/ingestion/chunking/graph.py`
   looks for `HAS_CONDITION`/`HAS_MEDICATION` edge types, but the FHIR
   converter produces `HAS_SUBJECT` (Condition → Patient) and
   `PRESCRIBES` instead. Fix the renderer to match actual edge types,
   then re-ingest FHIR data. After verifying Patient chunks contain
   clinical context, close #46 (umbrella).
   Files: `graph.py` lines 220-297 (`render_fhir_entity`),
   `scripts/ingest_fhir_hypertension.py`. Reference:
   `scripts/convert_fhir_to_graph.py` lines 208-226 for actual edge types.

2. **#31 — Eval pipeline: MCP-level end-to-end testing** (design + implement)
   The forcing-function query (5-source treatment plan for patient
   Charlena Brakus, UUID `596bb739-0d6a-038d-5160-7f870f9cea7a`) ran
   successfully this session with 7 retrieve calls. Capture this as a
   repeatable MCP-level eval — either as a pytest integration test
   against the live server, or as an EvalHub Job definition. The agent
   integration guide at `docs/guide-agent-integration.md` documents the
   workflow pattern to encode.

3. **#29 — Retrieve/refine: elicitation for low-confidence results** (feature)
   When retrieval scores are low, the system should surface this to the
   agent ("these results may not be relevant") rather than returning them
   silently. Design: threshold per source (embedding-model-dependent),
   injected into the retrieve response as a confidence signal. Start by
   examining score distributions across sources to pick sensible defaults.

**Sequencing.** #47 first — it's the smallest, highest-impact fix and
unblocks closing the umbrella. Start re-ingestion early so the pipeline
runs while working on #31. #31 second — the MCP eval design benefits
from the freshly re-ingested data (Patient chunks will now be richer).
#29 third if time allows.

**Constraints for the session:**
- #47 requires FHIR re-ingestion (~30 min pipeline run against cluster
  TEI endpoint). Budget for TEI pod restarts (memory leak under batch
  load — use the watchdog port-forward pattern).
- #31 design decision: pytest integration test vs. EvalHub Job. Decide
  in-session based on what's faster to get running.
- #29 needs score distribution data before picking thresholds — run a
  few queries per source and record the score ranges.

**Session start protocol:**
- Premise checks: `oc get pods --context=gpt-oss-120b -n retrieval-hub`
  (cluster healthy? embedding-nomic pod running?); `git log --oneline -5`
  (no surprise merges?); quick `describe_source` for fhir-hypertension
  (confirm enriched data cards from last session are live)
- Rules with history:
  - Use `127.0.0.1` not `localhost` for port-forwarded connections
  - TEI CPU has a memory leak under batch embedding — use small batches
    (embedding_batch_size=2), 10 retries with exponential backoff, and
    the watchdog port-forward script
  - Use `deploy.sh` for MCP server deploys, not raw `oc start-build --from-dir`
- Stop-and-ask before: any changes to the FHIR graph converter (would
  change edge structure for all future ingestions); any schema changes
  to pgvector tables
- Close ritual: session summary + update this file

## Remaining epic phases

None after this session — if #47, #31, and #29 ship, the epic is
complete and #46 can be closed. The ontology-aware doc_section
resolution (captured in memory as `design-ontology-vision`) is a
separate future epic, not part of this one.

## Definition of done

- ~~Memgraph data survives pod restart (#40)~~ done
- ~~Hetionet chunks include relationship edges (#44)~~ done
- ~~FHIR BP panel chunks include systolic/diastolic values (#41)~~ done
- ~~Graph traverse respects depth/edge-type/max-nodes bounds (#45)~~ done
- ~~Retrieve supports doc_section filtering (#43)~~ done
- ~~Entity-scope filtering designed and at least prototyped (#42)~~ done
- ~~Forcing-function query passes (5-source treatment plan)~~ done
- ~~Agent integration guidance documented (guide + data cards)~~ done
- ~~FHIR Patient chunks include conditions and medications (#47)~~ done
- ~~#46 (umbrella) closed~~ done
- ~~MCP-level end-to-end eval captured as repeatable test (#31)~~ done
- ~~Low-confidence elicitation on retrieve results (#29)~~ done

## What landed last session (2026-09-04)

Phase 3 complete + Phase 4 complete. doc_section and scope_entity_id
filters deployed, forcing-function query passed (5-source treatment
plan, 7 retrieve calls, no workarounds). Agent integration guide and
enriched data cards shipped.
See `session-summaries/2026-09-04-graph-quality-phase3-4.md`.

**Closed:** #43 — doc_section filter, #42 — scope_entity_id filter

**Follow-ups filed:** #47 — FHIR Patient renderer mismatch (edge type
mismatch between converter and renderer). mcp-test-mcp#10 — auth support.

## Watch out for

- TEI pod OOM restarts during re-ingestion. The watchdog port-forward
  pattern from 2026-09-03 handles this — see CLAUDE.md lessons learned.
- Port-forwards: Memgraph uses 17687 (7687 taken by local Podman gvproxy).
  TEI embedding-nomic uses port 8080, not 80.
- The `_neighbors_by_rel` function in graph.py supports direction-aware
  matching — use `outbound=False` to find inbound HAS_SUBJECT edges
  from Conditions/MedicationRequests to Patient.
- deploy.sh creates a filtered build context (core-lib/ + mcp-server/).
  Do not use `oc start-build --from-dir=<repo-root>` directly — the
  Containerfile's COPY directives expect the prepared directory layout.

## If blocked

- If TEI endpoint is down or cluster is unavailable, #31 (MCP eval
  design) and #29 (confidence elicitation) are both local code + tests.
  Can develop and test without cluster access.
- If #47 fix is more complex than expected (edge direction logic in
  `_neighbors_by_rel`), defer re-ingestion and focus on #31/#29.
