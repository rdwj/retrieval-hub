# Next Session -- Platform Ops

## Epic: Operational reliability and deployment catchup

Ship the accumulated features to the deployed MCP server, fix the
recurring TEI/ingestion pain points, and set up production ingestion
runners. The quick win (#70) unblocks agents from using everything
built in the ontology and graph-quality epics.

Issues: #27, #66, #67, #70

## Next: Ingestion config update + TEI retirement path (#66 remainder)

vLLM is deployed and tested. Remaining work from #66:

1. **Update ingestion scripts to default to vLLM endpoint**
   The ingestion scripts currently require `--endpoint` to use remote
   embedding. Update the default endpoint in ingestion scripts to
   point to `http://vllm-nomic-embedding:8000` when running in-cluster,
   or document the port-forward command for local runs.

2. **Replace worker nodes with 200GB gp3 disks**
   MachineSet is already updated to 200GB gp3 for new nodes, but
   existing nodes still have 100GB gp2. Plan a maintenance window
   to do rolling node replacement (scale to 3, drain old, delete,
   repeat). This requires coordinating with PostgreSQL and Memgraph
   StatefulSet downtime.

3. **TEI retirement path**
   TEI (CPU) is still running for query-time embedding. Options:
   - Switch MCP server's query-time embedding to vLLM (same endpoint)
   - Keep TEI as CPU fallback if GPU node is scaled down for cost
   - Document the migration path in deploy/openshift/retrieval-hub/embedding/README.md

**Session start protocol:**
- Premise checks: `oc get pods --context=gpt-oss-120b -n retrieval-hub`
  (vLLM still running?). Check GPU node and embedding pod health.
- vLLM serves on `http://vllm-nomic-embedding:8000` (in-cluster) or
  `http://127.0.0.1:18000` via port-forward.
- The g6e.xlarge GPU node costs ~$1.25/hr. Scale to 0 when not needed.
- Close ritual: session summary + `/plan-next-session platform-ops`

## Remaining epic phases

### Phase 2: vLLM embedding + worker node scale-up (#66) — IN PROGRESS

vLLM deployed and batch-tested (2000 chunks, 78.5 chunks/sec, 0
restarts). Worker MachineSet config updated to 200GB gp3 for future
nodes. Remaining: replace existing 100GB nodes (maintenance window),
update ingestion defaults, document TEI retirement path.

**Definition of done:** vLLM serves nomic-embed-text-v1.5 on
gpt-oss-120b, batch ingestion of 1000+ chunks completes without
OOM, worker nodes have 200GB EBS (no more BuildPodEvicted).

**Dependencies:** None.

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

## What landed last session (2026-09-09, second session)

Platform-ops Phase 2 in progress. Deployed vLLM v0.8.5 with
nomic-embed-text-v1.5 on a new single-GPU g6e.xlarge node (separate
from the quad-GPU LLM node). Batch embedding tested: 2000 chunks in
25.5s (78.5 chunks/sec), zero restarts. Worker MachineSet updated
to 200GB gp3 for future nodes (existing nodes unchanged). Fixed
vLLM NomicBert rope_scaling crash with `--hf-overrides
'{"rotary_scaling_factor": 1.0}'`.

**See:** session-summaries/2026-09-09-platform-ops-vllm-deploy.md

## Watch out for

- Worker node replacement (when done) causes pod evictions. Plan
  the scale-down/up when other workloads can tolerate disruption.
  PostgreSQL and Memgraph are StatefulSets with PVCs — they survive
  rescheduling, but verify data integrity after node replacement.
- The g6e.xlarge GPU node costs ~$1.25/hr. Scale to 0 when not
  actively needed for embedding: `oc scale machineset
  gpu-g6e1-cluster-z9hbt-2hdjl-worker-us-east-2c --replicas=0
  -n openshift-machine-api --context=gpt-oss-120b`
- vLLM requires `--hf-overrides '{"rotary_scaling_factor": 1.0}'`
  for nomic-embed-text-v1.5 (see CLAUDE.md lesson).
- `truncate_prompt_tokens: 512` must be set in vLLM embedding
  requests (see CLAUDE.md lesson on tokenizer mismatch).

## If blocked

- If the GPU node is unavailable or vLLM won't start, TEI (CPU)
  is still running as a fallback. The TEI resilience workaround
  (batch_size=2, 10 retries, watchdog port-forward) is documented
  in CLAUDE.md.
- If worker node replacement causes issues, the MachineSet is
  already updated — just scale to 3, drain one old node at a time.
