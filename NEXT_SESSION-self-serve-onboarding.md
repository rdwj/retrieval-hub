# Next Session -- Self-Serve Onboarding

## Epic: Auth, AutoRAG-style Onboarding, and New Data Families

Build the auth layer, a self-serve source onboarding pipeline, and onboard
new datasets that exercise the four unrepresented source families (tabular,
graph, process, external). The self-serve pipeline replaces the idea of
adopting an external AutoRAG framework by wrapping our own eval sweep
infrastructure into an onboarding workflow.

## What landed

- **Phase 1 (Auth): Complete.** JWT validation via FastMCP JWTVerifier,
  source-level access control on all 5 tools, `request_access` tool, auth
  service OpenShift manifests. #30 closed. See `session-summaries/
  2026-08-27-self-serve-onboarding-auth-and-pipeline.md`.

- **Phase 2 (Onboarding pipeline): Code complete, not yet proven.**
  `pipeline.py` generic ingestion, generalized `generate_qa_pairs.py` and
  `eval_answer_quality.py`, `onboard_source.py` orchestrator. Dry-run
  verified. Needs an end-to-end proving run against real databases with
  real embedding/LLM calls.

## Remaining epic phases

### Phase 2 — Proving run and polish

The pipeline code is written but hasn't been run end-to-end. This is the
gate before Phase 3 can use it.

**Work:**
1. Run `onboard_source.py` against a small real dataset (e.g., a subset
   of the Tale of Two Cities data or a fresh markdown corpus) with local
   Postgres and local/remote embedding. Fix whatever breaks.
2. Verify the full chain: ingest (3 configs) → QA gen (LLM calls) → eval
   (Ragas scoring) → winner selection → cleanup of losers → source is
   queryable via the MCP server.
3. Data card auto-population: after the proving run works, add eval
   baseline scores and chunk config to `describe_source` metadata.
4. EvalHub integration (stretch): package the sweep as an OpenShift Job.
   Overlaps with eval-convergence epic — coordinate.

**Definition of done:** A data owner can run the pipeline end-to-end and
get a working, queryable, eval-baselined source.

### Phase 3a — Tabular (ClinicalTrials.gov)

**Design questions to resolve first:**
- Row-per-chunk vs. group-of-rows-per-chunk?
- Semantic search over NL-rendered text, or structured filters?
- How does `refine` work on tabular data?

**Work:** Download extract, build TabularAdapter, ingestion script, QA +
eval. Wire into retrieval adapter factory.

### Phase 3b — Process (Aircraft maintenance procedures)

**Work:** Re-model existing Piper SB data as structured procedures. Build
ProcessAdapter (procedure context around a step, not just the chunk).
The raw data already exists. The `refine` entity-arc strategy may work for
procedure traversal.

### Phase 3c — Graph (SNOMED-CT or similar)

Most architecturally novel. May warrant a spike first. Pick a dataset,
design chunk representation (entity-as-chunk vs. relationship-as-chunk),
build GraphAdapter.

### Phase 3d — External (federation to public API)

Integration pattern, not a new data shape. Simplest version: an adapter
that makes HTTP calls instead of pgvector queries. Participates in
multi-source RRF.

**Sequencing:** 3a and 3b first (highest value, clearest path), then 3c
(spike), then 3d.

**Epic definition of done:** At least 3 of 4 families have a live source
with eval baseline. Onboarding pipeline successfully onboards at least one.

## Next session

**Focus: Phase 2 proving run + Phase 3b (process family).**

Phase 3b is the best candidate for the proving run because the raw data
already exists (`retrieval-hub-data-sources/aircraft-maintenance/`), the
document family is already supported by the pipeline, and it exercises the
onboarding workflow end-to-end. If the pipeline works for aircraft SBs as
flat documents first, re-modeling as structured procedures is a follow-on.

**Planned work:**
1. Run `onboard_source.py --slug aircraft-sb-test --data-dir
   ~/Developer/retrieval-hub-data-sources/aircraft-maintenance/ --family
   technical_document` end-to-end. Fix any issues.
2. Verify the registered source is queryable via the MCP server.
3. Start the ProcessAdapter for re-modeling aircraft SBs as structured
   procedures (the "process" family).

**Stretch:** Begin Phase 3a (tabular) design decisions.

## Open issues this epic addresses

- #24 Keycloak realm and role allowlist example (Phase 1 stretch, deferred)
- #27 Production ingestion runners (Phase 2 via EvalHub, partially advanced
  by pipeline.py — see comment on issue)

## Open issues this epic does NOT address

- #31 MCP-level end-to-end eval (eval-convergence epic)
- #29 Elicitation (future epic)
- #25 Operator with CRDs (future)
- #23 Grafana dashboard (future)
- #17 SDK / #18 CLI (future)
