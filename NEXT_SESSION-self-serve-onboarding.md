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

- **Phase 2 (Onboarding pipeline): Mostly proven.** Fixed 6 bugs
  blocking end-to-end execution. Ingestion (3 configs), QA generation
  (156 questions), and retrieval all working against cluster databases.
  Eval paused at answer generation (30/156) due to LLM contention.
  Retrieval and ingestion results cached; eval can be resumed.
  See `session-summaries/2026-08-27-self-serve-onboarding-proving-run.md`.

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

**Focus: Complete Phase 2 proving run + deploy fixes + start Phase 3b.**

**Planned work:**
1. Resume eval answer generation for `aircraft-sb-test` (retrieval.json
   cached; just needs LLM time for answers + Ragas scoring). Run all 3
   configs to get summary.json files. Set model registry endpoint to
   `http://127.0.0.1:8180` and port-forward the nomic embedding service.
2. Run winner selection and promotion (the final pipeline steps).
3. Deploy MCP server with the bug fixes: technical_document adapter,
   unhealthy-model fallback, LLM None content handling.
4. Verify `aircraft-sb-test` is queryable via the deployed MCP server.
5. Fix QA generation overshoot: `_build_generation_targets()` generates
   1 question per document regardless of `--num-qa-pairs`. Should
   distribute the requested count across a subset of documents.
6. Start Phase 3b: ProcessAdapter for structured procedure navigation.

**Infrastructure notes for resuming eval:**
- Port-forward DB: `scripts/port_forward_cluster_pg.sh` (5434→catalog, 5433→vectors)
- Port-forward embedding: `oc port-forward --context=gpt-oss-120b -n retrieval-hub svc/retrieval-hub-embedding-nomic 8180:8080`
- Set model registry: `UPDATE model_endpoint SET endpoint_url='http://127.0.0.1:8180', status='healthy' WHERE model_name='nomic-ai/nomic-embed-text-v1.5'`
- Run eval: use the inline Python script pattern from the proving run session, with `logging.basicConfig()` configured

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
