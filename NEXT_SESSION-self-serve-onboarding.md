# Next Session -- Self-Serve Onboarding

## Epic: Auth, AutoRAG-style Onboarding, and New Data Families

Build the auth layer, a self-serve source onboarding pipeline, and onboard
new datasets that exercise the four unrepresented source families (tabular,
graph, process, external). The self-serve pipeline replaces the idea of
adopting an external AutoRAG framework by wrapping our own eval sweep
infrastructure into an onboarding workflow.

## What landed

- **Phase 1 (Auth): Complete.** Machine-to-machine OAuth 2.1
  (client_credentials) + Google OAuth for interactive human login.
  Email-domain-based access control (@redhat.com). See
  `session-summaries/2026-08-27-self-serve-onboarding-auth-and-pipeline.md`
  and `session-summaries/2026-09-01-self-serve-onboarding-google-oauth.md`.

- **Phase 2 (Onboarding pipeline): Complete.** Full eval sweep proven
  end-to-end. `--skip-eval` fast path. Data card auto-population.

- **Phase 3a (Tabular): Complete.** TabularAdapter, 307 chunks as
  `clinicaltrials-hypertension`, CURATED.

- **Phase 3b (Process): Complete.** ProcessAdapter, 2,456 chunks as
  `aircraft-sb-process`, CURATED.

- **Graph spike (design + dataset acquisition): Complete.** Design doc,
  Memgraph backend decision, datasets acquired (FHIR + Hetionet).

- **Cluster deploy automation: Complete.** `deploy/env.example`,
  `deploy/CLUSTER_DEPLOY.md`, `retrieval-hub-auth/deploy.sh`,
  enhanced `deploy-platform.sh` with env file + idempotent secrets.

## Next: Graph family implementation (Phase 3c)

Build GraphAdapter, deploy Memgraph on OpenShift, wire into pipeline and
adapter factory. Ingest FHIR and Hetionet datasets using the design from
the spike (`docs/graph-family-design.md`).

There is partially-written code in the working tree from the prior session
(graph adapter, chunker, ingestion scripts, memgraph manifests, tests).
Start by reviewing what exists before writing new code.

1. **Review uncommitted graph code.**
   Check `git status` for the in-flight graph files: `src/retrieval_hub/adapters/graph.py`,
   `src/retrieval_hub/ingestion/chunking/graph.py`, `src/retrieval_hub/ingestion/write_graph.py`,
   `deploy/memgraph/openshift.yaml`, `scripts/ingest_fhir_hypertension.py`,
   `scripts/ingest_hetionet.py`, `tests/test_adapters/test_graph.py`,
   `tests/test_ingestion/test_graph_chunker.py`. Assess completeness and
   correctness against the design doc before extending.

2. **Deploy Memgraph on OpenShift.**
   Apply `deploy/memgraph/openshift.yaml`. Verify Bolt connectivity from
   the MCP server pod. Add `MEMGRAPH_BOLT_URI` env var to MCP deployment.

3. **Complete GraphAdapter and wire into adapter factory.**
   `retrieve()` delegates to pgvector; `refine()` does N-hop Cypher
   traversal via Memgraph. Wire into `adapters/__init__.py`.

4. **Complete graph chunker and entity renderer.**
   Entity-centric chunks rendered as natural language, embedded into
   pgvector. Graph structure loaded into Memgraph.

5. **FHIR-to-graph converter + ingest.**
   Parse Synthea FHIR R4 bundles into nodes/edges. Ingest with
   `--skip-eval`. Verify entity chunks in pgvector, graph in Memgraph,
   refine() returns traversal context.

6. **Hetionet ingest (hypertension subgraph).**
   Extract hypertension-relevant subgraph first (full graph is 47K nodes,
   2.2M edges). Ingest with `--skip-eval`.

7. **SNOMED-CT if UMLS license approved.** Otherwise defer.

**Sequencing.** Step 1 first (what already exists?), then 2 (Memgraph
deploy), then 3-4 (adapter + chunker), then 5-6 (ingest). Step 7 is
opportunistic.

**Constraints for the session:**
- The uncommitted graph files may be incomplete or stale. Review before
  building on top of them.
- MCP server now has Google OAuth — the `RETRIEVAL_HUB_GOOGLE_BASE_URL`
  env var must be set correctly after any redeployment.

**Session start protocol:**
- Premise checks (before step 1, ~5 min):
  - `git status` to inventory uncommitted graph files
  - Verify design doc at `docs/graph-family-design.md` still matches intent
  - Confirm datasets at `retrieval-hub-data-sources/fhir-hypertension/`
    (57 files) and `retrieval-hub-data-sources/hetionet/` (47K nodes)
  - Check UMLS license approval at https://uts.nlm.nih.gov/uts/profile
  - `oc get pods --context=gpt-oss-120b -n retrieval-hub` — cluster healthy?
- Rules with history:
  - TEI nomic pod at 32Gi with batch_size=2 and 10-retry backoff for
    any embedding run
  - Memgraph image is Debian-based (not UBI) — acceptable for internal use
  - Use `127.0.0.1` not `localhost` for port-forwarded Postgres connections
- Stop-and-ask before: creating Memgraph StatefulSet, ingesting Hetionet
  at full scale, any changes to the MCP server deployment

## Remaining epic phases

### Phase 3c -- Graph (this session)

Build GraphAdapter, graph chunker, wire into pipeline and adapter factory.
Ingest FHIR and Hetionet datasets using the design from the spike.
Test graph refine strategy. Use `--skip-eval` for initial ingestion.

### Phase 3d -- External (federation to public API)

Integration pattern, not a new data shape. Simplest version: an adapter
that makes HTTP calls instead of pgvector queries. Participates in
multi-source RRF.

**Epic definition of done:** At least 3 of 4 families have a live source
with eval baseline. Onboarding pipeline successfully onboards at least one.
**Status: met.** Process and tabular families are live. The epic DoD is
satisfied; 3c and 3d are extensions that round out the platform.

## What landed last session (2026-09-01)

Pivoted from planned graph implementation to Google OAuth — a demo was
blocked because the MCP server had no interactive login flow.

**Commits:** c62a1df..1bbcbf9 (main)
- `c62a1df` — Google OAuth via FastMCP GoogleProvider + MultiAuth.
  Identity model gains email field, email-based access control for
  restricted sources, @redhat.com domain gating.
- `1bbcbf9` — End-to-end cluster deploy automation. env.example,
  CLUSTER_DEPLOY.md runbook, auth deploy.sh, enhanced deploy-platform.sh.

**Deployed:** Google OAuth verified end-to-end on gpt-oss-120b cluster.
User authenticated with @redhat.com account, got sourced clinical
guidelines answer via Claude Code.

See `session-summaries/2026-09-01-self-serve-onboarding-google-oauth.md`.

## Watch out for

- TEI CPU memory leak under sustained batch embedding. See CLAUDE.md
  lesson. Use batch_size=2, self-healing port-forward, 10-retry backoff.
- SNOMED-CT: UMLS license submitted 2026-08-31, approval expected
  ~2026-09-03. Check status at https://uts.nlm.nih.gov/uts/profile.
- Memgraph image is Debian-based (not UBI). Acceptable for internal use.
- Memgraph snapshots/WAL are version-specific. Upgrades require
  dump/restore. Set `terminationGracePeriodSeconds` high enough.
- Hetionet is large. Extract hypertension subgraph for first test.
- Synthea generated general population. FHIR converter should extract
  all conditions, not assume hypertension-only.
- Google OAuth secret on gpt-oss-120b is manually managed. If cluster
  is reprovisioned, recreate via `deploy/CLUSTER_DEPLOY.md`.
- OpenShift Route for MCP server no longer has `path: /mcp` restriction
  (needed for OAuth endpoints). Don't re-add it.

## If blocked

- If Memgraph deploy fails on OpenShift (SCC issues, image pull): fall
  back to local Memgraph via podman for development, deploy later.
- If FHIR/Hetionet datasets are missing from companion repo: re-generate
  FHIR with Synthea, re-download Hetionet from GitHub (CC0, public).

## Open issues this epic addresses

- #24 Keycloak realm and role allowlist example (Phase 1 stretch, deferred)
- #27 Production ingestion runners (Phase 2 via EvalHub, partially advanced)

## Open issues this epic does NOT address

- #31 MCP-level end-to-end eval (eval-convergence epic)
- #29 Elicitation (future epic)
- #25 Operator with CRDs (future)
- #23 Grafana dashboard (future)
- #17 SDK / #18 CLI (future)
