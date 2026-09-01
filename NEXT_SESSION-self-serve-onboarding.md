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

- **Phase 3c (Graph): Complete.** GraphAdapter with Memgraph-backed
  refine, graph chunker with FHIR/Hetionet/default renderers, Memgraph
  deployed on OpenShift. FHIR (22,305 nodes) and Hetionet (769 nodes)
  ingested. See `session-summaries/2026-09-01-self-serve-onboarding-graph-family.md`.

- **Graph spike (design + dataset acquisition): Complete.** Design doc,
  Memgraph backend decision, datasets acquired (FHIR + Hetionet).

- **Cluster deploy automation: Complete.** `deploy/env.example`,
  `deploy/CLUSTER_DEPLOY.md`, `retrieval-hub-auth/deploy.sh`,
  enhanced `deploy-platform.sh` with env file + idempotent secrets.

## Next: SNOMED-CT graph ingest + renderer quality pass

UMLS license approved. Download SNOMED-CT US Edition, extract a
hypertension concept hierarchy, and ingest as a graph source. Also
re-ingest FHIR and Hetionet with their domain-specific renderers
(they were ingested with the default renderer before the renderer
passthrough fix landed).

1. **Re-ingest FHIR and Hetionet with correct renderers.**
   The renderer passthrough fix landed this session but existing data
   used the default renderer. Re-run `scripts/ingest_fhir_hypertension.py`
   and `scripts/ingest_hetionet.py` — they now pass `renderer="fhir"`
   and `renderer="hetionet"` respectively. Quick warmup (~15 min).
   Verify embedding quality improves (entity descriptions should be
   richer with domain-specific renderers).

2. **Download SNOMED-CT and extract hypertension subset.**
   Download the SNOMED-CT US Edition from https://uts.nlm.nih.gov.
   The full release is RF2 format (tab-delimited concept/description/
   relationship files). Extract a hypertension-centered subgraph:
   concept 59621000 (Essential hypertension) + IS_A ancestors/
   descendants, FINDING_SITE, ASSOCIATED_MORPHOLOGY, and MAY_TREAT
   relationships. Target ~5,000 nodes, ~8,000 edges per the design doc.
   Write output to `retrieval-hub-data-sources/snomed-ct-hypertension/`.

3. **Write SNOMED-CT entity renderer.**
   Add `render_snomed_entity()` to `src/retrieval_hub/ingestion/chunking/graph.py`.
   Render fully specified name + definition + finding site + associated
   morphology as natural-language clinical text. Register as `"snomed"`
   in the renderer registry. Write tests.

4. **Ingest SNOMED-CT hypertension subgraph.**
   Write `scripts/ingest_snomed_hypertension.py` following the pattern
   of the FHIR/Hetionet scripts. Use `renderer="snomed"`, `--skip-eval`.
   Verify entity chunks in pgvector, graph structure in Memgraph,
   `refine()` with `graph_traverse_from_seed` returns clinical
   relationships (IS_A hierarchy, treatments, anatomical sites).

5. **Rebuild and deploy MCP server.**
   After SNOMED-CT ingest, rebuild the MCP server so the new source
   is queryable via the live endpoint. Verify retrieve + graph refine
   for SNOMED-CT via MCP tools.

**Sequencing.** Step 1 first (quick renderer quality fix), then 2
(download + extract), then 3 (renderer), then 4 (ingest), then 5
(deploy + verify). Steps 2-3 could overlap if the download is slow.

**Constraints for the session:**
- SNOMED-CT RF2 format has multiple description files (FSN, synonyms,
  definitions). Use the Full release, not Snapshot, for complete data.
  Parse `sct2_Concept_Full_*.txt`, `sct2_Description_Full_*.txt`, and
  `sct2_Relationship_Full_*.txt`.
- Re-ingestion of FHIR/Hetionet will drop and recreate their pgvector
  tables. The Memgraph data is on emptyDir and may need reloading if
  the pod restarted since last session.
- TEI nomic embedding is CPU-only with known memory leak. Use
  batch_size=2, 10-retry backoff, self-healing port-forward.

**Session start protocol:**
- Premise checks (before step 1, ~5 min):
  - `oc get pods --context=gpt-oss-120b -n retrieval-hub` — cluster
    healthy, Memgraph pod running?
  - If Memgraph pod restarted (emptyDir lost), graph data needs
    reloading before re-ingestion can verify graph refine
  - Confirm SNOMED-CT download access at https://uts.nlm.nih.gov
  - Confirm `retrieval-hub-data-sources/` companion repo is present
- Rules with history:
  - TEI nomic pod at 32Gi with batch_size=2 and 10-retry backoff
  - Memgraph on emptyDir — data lost on pod restart, reload needed
  - Use `127.0.0.1` not `localhost` for port-forwarded Postgres
- Stop-and-ask before: any changes to the MCP server deployment,
  ingesting SNOMED-CT at full scale (start with subset), dropping
  existing pgvector tables

## Remaining epic phases

### Phase 3d -- External (federation to public API)

Integration pattern, not a new data shape. Simplest version: an adapter
that makes HTTP calls instead of pgvector queries. Participates in
multi-source RRF.

**Epic definition of done:** At least 3 of 4 families have a live source
with eval baseline. Onboarding pipeline successfully onboards at least one.
**Status: met.** Process, tabular, and graph families are live. The epic
DoD is satisfied; 3d is an extension that rounds out the platform.

## What landed last session (2026-09-01)

Graph family implementation (Phase 3c). GraphAdapter with Memgraph-backed
refine, graph chunker with domain-specific renderers, Memgraph deployed
on OpenShift, FHIR + Hetionet ingested, end-to-end verified locally and
via deployed MCP server.

**Commits:** 86ca1d6..82becf5 (main)
- `86ca1d6` — Graph data family: adapter, chunker, write_graph, Memgraph
  StatefulSet, ingestion scripts, 26 tests, pipeline + API wiring,
  RefineOutput context field, neo4j deploy dependency
- `ad14747` — CLAUDE.md testing instruction, archived eval-convergence plan
- `146a204` — README walkthrough echo updated
- `82becf5` — Session summary + lint fixes

**Deployed:** Memgraph v3.12.0 on gpt-oss-120b. MCP server rebuilt with
neo4j + MEMGRAPH_BOLT_URI. Google OAuth creds rotated.

See `session-summaries/2026-09-01-self-serve-onboarding-graph-family.md`.

## Watch out for

- TEI CPU memory leak under sustained batch embedding. See CLAUDE.md
  lesson. Use batch_size=2, self-healing port-forward, 10-retry backoff.
- Memgraph is on emptyDir (not PVC). Pod restart loses all graph data.
  Re-run `write_graph_structure()` to reload after a restart. Takes ~15s
  for current datasets but will grow with SNOMED-CT.
- SNOMED-CT RF2 files use a specific date-stamped naming convention
  (e.g., `sct2_Concept_Full_US1000124_20260301.txt`). Glob for the
  pattern rather than hardcoding filenames.
- SNOMED-CT concept hierarchy is deep (10+ levels for some branches).
  The 2-hop BFS used for Hetionet may be too shallow for IS_A traversal.
  Consider a deeper hop limit or targeted IS_A-only traversal for the
  extraction script.
- Google OAuth secret on gpt-oss-120b is manually managed. If cluster
  is reprovisioned, recreate via `deploy/CLUSTER_DEPLOY.md`.
- OpenShift Route for MCP server has no `path:` restriction (needed for
  OAuth endpoints). Don't re-add it.

## If blocked

- If SNOMED-CT download is slow or format is unexpected: skip to Phase
  3d (external adapter) and return to SNOMED-CT next session.
- If Memgraph pod is down and won't restart: fall back to local Memgraph
  via podman for development, deploy later.
- If TEI embedding is unstable: use local sentence-transformers for
  SNOMED-CT (small dataset, ~5K entities).

## Open issues this epic addresses

- #24 Keycloak realm and role allowlist example (Phase 1 stretch, deferred)
- #27 Production ingestion runners (Phase 2 via EvalHub, partially advanced)

## Open issues this epic does NOT address

- #31 MCP-level end-to-end eval (eval-convergence epic)
- #29 Elicitation (future epic)
- #25 Operator with CRDs (future)
- #23 Grafana dashboard (future)
- #17 SDK / #18 CLI (future)
