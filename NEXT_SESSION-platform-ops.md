# Next Session -- Platform Ops

## Epic: Operational reliability and deployment catchup

Ship the accumulated features to the deployed MCP server, fix the
recurring TEI/ingestion pain points, and set up production ingestion
runners. The quick win (#70) unblocks agents from using everything
built in the ontology and graph-quality epics.

Issues: #27, #66, #67, #70

## Next: Deploy MCP server and apply CronJob (#70)

Rebuild and deploy the MCP server to pick up all ontology and
graph-quality features (shipped Sep 4-Sep 9, never deployed). Also
apply the ontology doctor CronJob manifest.

1. **#70 — Deploy MCP server with latest features**
   Run `retrieval-hub-mcp/deploy.sh retrieval-hub --context=gpt-oss-120b`.
   Last successful build was Sep 4 (build 19). Two subsequent builds
   failed due to node ephemeral-storage pressure (BuildPodEvicted),
   not code issues — a retry should succeed.

   After deploy, smoke test:
   - `describe_ontology` with `include_hierarchy=true` and
     `include_relationships=true`
   - `retrieve` with an ontology-assisted query (verify doc_section
     expansion works)
   - Confidence elicitation on a low-relevance query

2. **Apply ontology doctor CronJob**
   `oc apply -f deploy/openshift/retrieval-hub/ontology-doctor-cronjob.yaml --context=gpt-oss-120b -n retrieval-hub`
   Verify the first scheduled run completes (or trigger manually:
   `oc create job ontology-doctor-manual --from=cronjob/ontology-doctor --context=gpt-oss-120b -n retrieval-hub`).

**Sequencing.** Deploy MCP server first (it's the image the CronJob
uses). Then apply the CronJob manifest.

**Constraints for the session:**
- Build may fail again if the node is under storage pressure. If so,
  check node capacity (`oc describe node`) and retry after cleanup.
- The deploy script creates a filtered build context (core-lib/ +
  mcp-server/). Do NOT use `oc start-build --from-dir=<repo-root>`.
- The CronJob uses the same MCP server image — it must be the freshly
  built one, not the stale Sep 4 image.

**Session start protocol:**
- Premise checks: `oc get pods --context=gpt-oss-120b -n retrieval-hub`
  (cluster healthy? DB pod running?). `oc get builds --context=gpt-oss-120b
  -n retrieval-hub --sort-by=.metadata.creationTimestamp | tail -3`
  (any in-progress builds?). `git log --oneline -3` (no surprise merges?).
- Rules with history: use `deploy.sh` for MCP builds, not raw
  `oc start-build`. Use `127.0.0.1` not `localhost` for any port-
  forwarded verification. Build failures on this cluster have been
  node-pressure related, not code-related — retry before investigating.
- Stop-and-ask before: any changes to the Containerfile or build
  config; any `oc delete` of existing deployments or services.
- Close ritual: session summary + `/plan-next-session platform-ops`

## Remaining epic phases

### Phase 2: TEI memory leak mitigation (#66)

Evaluate vLLM embedding endpoint (v0.8.5, `--task embed`) as an
alternative to the leaky TEI CPU container for batch embedding.

**Definition of done:** Batch ingestion of 1000+ chunks completes
without pod OOM restarts, or the limitation is documented with a
viable workaround.

**Dependencies:** None. Parallel-ok with Phase 1.

### Phase 3: Ingestion checkpoint-resume (#67)

Add checkpoint-resume to the ingestion pipeline so long runs survive
interruptions.

**Definition of done:** An ingestion run interrupted at 50% resumes
from the checkpoint without re-embedding completed chunks.

**Dependencies:** Benefits from Phase 2 (stable embedding endpoint).

### Phase 4: Production ingestion runners (#27)

Deploy ingestion as Tekton pipelines or Kubernetes Jobs in-cluster.

**Definition of done:** At least one source can be re-ingested via
`oc create job` without local port-forwards.

**Dependencies:** Phase 2 + Phase 3.

## What landed last session (2026-09-09)

Ontology epic closed. Doctor (9 checks, CLI, 22 tests), all 11
sources onboarded, CronJob manifest written, retro completed. Three
completed epics archived. Six new issues filed (#65-70). Three new
epic files bootstrapped (platform-ops, ontology-v2, platform-quality).

**Commits:** 10b0a3b..961a64b (main)
**Closed:** #48 (umbrella), #56, #58, #59, #60

## Watch out for

- Build failures on gpt-oss-120b have been ephemeral-storage related
  (builds 20, 21, 22 all BuildPodEvicted). Retry before investigating.
- The deploy.sh script (~34 min for build 19) takes significant time.
  Start the build early in the session.
- OpenShift route path must NOT have a trailing slash for FastMCP
  (path: /mcp, not /mcp/). Current manifest is correct.
- The CronJob runs weekly (Mon 06:23 UTC). First scheduled run after
  applying will be the next Monday.

## If blocked

- If the cluster is down or builds keep failing, work on Phase 2
  (TEI evaluation) or Phase 3 (ingestion checkpointing) locally —
  both are code-only work that doesn't need the cluster.
- If the MCP server deploys but smoke tests fail, check the
  `FastMCP cache_ttl` behavior — stale tool lists from the prior
  image can persist (#37, closed but the caching behavior is still
  relevant post-deploy).
