# Next Session -- Platform Ops

## Epic: Operational reliability and deployment catchup

Ship the accumulated features to the deployed MCP server, fix the
recurring TEI/ingestion pain points, and set up production ingestion
runners. The quick win (#70) unblocks agents from using everything
built in the ontology and graph-quality epics.

Issues: #27, #66, #67, #70

## Next: Deploy MCP server (#70)

Build and deploy the MCP server with all accumulated features from the
ontology and graph-quality epics. Verify with a smoke test.

## Remaining epic phases

### Phase 1: Deploy MCP server (#70)

Rebuild and redeploy the MCP server image to pick up ontology discovery,
hierarchy, relationships, confidence elicitation, and all other features
that shipped since the last deploy.

**Work:**
1. Run `deploy.sh` to build and push a new image
2. Verify the deployed server exposes `describe_ontology` with `include_hierarchy` and `include_relationships`
3. Smoke test: `retrieve` with ontology-assisted doc_section expansion
4. Verify confidence elicitation on low-score results

**Definition of done:** Deployed MCP server returns ontology-enriched
responses. An agent can call `describe_ontology` and get the full
concept hierarchy.

**Dependencies:** None.

### Phase 2: TEI memory leak mitigation (#66)

Evaluate alternatives to the leaky TEI CPU container for batch embedding.

**Work:**
1. Benchmark vLLM embedding endpoint (v0.8.5, `--task embed`) for Nomic v1.5
2. Compare throughput and memory stability against TEI under batch load
3. If vLLM is viable, deploy alongside or replace TEI
4. If not, document the workaround pattern and accept the limitation

**Definition of done:** Batch ingestion of 1000+ chunks completes
without pod OOM restarts, or the limitation is documented with a
viable workaround.

**Dependencies:** None. Parallel-ok with Phase 1.

### Phase 3: Ingestion checkpoint-resume (#67)

Add checkpoint-resume to the ingestion pipeline so long runs survive
interruptions.

**Work:**
1. Save intermediate embeddings to disk after each batch
2. Resume from last completed batch on restart
3. Add retry logic for DB writes
4. Test with a simulated port-forward drop

**Definition of done:** An ingestion run interrupted at 50% resumes
from the checkpoint without re-embedding completed chunks.

**Dependencies:** Benefits from Phase 2 (stable embedding endpoint
reduces the need for checkpointing) but not gated on it.

### Phase 4: Production ingestion runners (#27)

Deploy ingestion as Tekton pipelines or Kubernetes Jobs running
in-cluster.

**Work:**
1. Write Job manifests for each ingestion script
2. Configure in-cluster DB and embedding endpoint connections
3. Add CronJob triggers for sources with refresh cadence
4. Test with one source end-to-end

**Definition of done:** At least one source can be re-ingested via
`oc create job` without local port-forwards.

**Dependencies:** Phase 2 (embedding endpoint must be stable for
in-cluster use). Phase 3 (checkpoint-resume for long jobs).

## What this covers (and what it doesn't)

**In scope:**
- #27 Production ingestion runners
- #66 TEI memory leak
- #67 Ingestion checkpoint-resume
- #70 Deploy MCP server

**Out of scope (other epics own):**
- Ontology v2 (NEXT_SESSION-ontology-v2.md): #61-64, #68
- Platform quality (NEXT_SESSION-platform-quality.md): #65
- Auth (#24, #69), SDK (#17), CLI (#18), Grafana (#23), Operator (#25): future/unepiced
