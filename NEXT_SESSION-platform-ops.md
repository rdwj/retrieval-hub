# Next Session -- Platform Ops

## Epic: Operational reliability and deployment catchup

Ship the accumulated features to the deployed MCP server, fix the
recurring TEI/ingestion pain points, and set up production ingestion
runners. The quick win (#70) unblocks agents from using everything
built in the ontology and graph-quality epics.

Issues: #27, #66, #67, #70

## Next: vLLM embedding deployment + worker node scale-up (#66)

Replace the leaky TEI CPU embedding with vLLM on the GPU node, and
increase worker node EBS to stop build evictions. Goal: a cluster
that can run batch ingestion (1000+ chunks) without OOM restarts and
build without ephemeral-storage evictions.

1. **Deploy vLLM v0.8.5 with nomic-embed-text-v1.5 on the GPU node**
   We deployed this same model on vLLM on agent-security-dev-3 in
   August (session 2026-08-21). That cluster was reclaimed but the
   recipe is proven. Apply it to gpt-oss-120b.

   Create a Deployment manifest for vLLM with:
   - Image: `vllm/vllm-openai:v0.8.5` (latest doesn't support
     `--task embed`)
   - Args: `vllm serve nomic-ai/nomic-embed-text-v1.5 --task embed`
   - GPU toleration for `nvidia.com/gpu` NoSchedule taint
   - `enableServiceLinks: false` (avoids env var collisions)
   - `HF_HOME` pointing to a PVC or emptyDir (non-root can't use
     `/root/`)
   - Resource request: 1 GPU, 16Gi memory
   - Service: `vllm-nomic-embedding` on port 8000

   Smoke test: `curl http://vllm-nomic-embedding:8000/v1/embeddings`
   with a short text. Verify 768-dim vector returned.

2. **Batch embedding test through vLLM (1000+ chunks)**
   Port-forward the vLLM service and run a batch embedding test
   using the existing `embed.py` `_remote_embed()` path. Target:
   1000+ chunks without pod OOM restarts.

   Compare with TEI: same 1000 chunks, same batch size. TEI should
   OOM within ~25 min; vLLM should complete cleanly.

3. **Scale worker node EBS from 100GB to 200GB**
   The 3 worker nodes (m6a.4xlarge) have 100GB gp2 EBS. Docker layer
   cache from builds fills this up, causing BuildPodEvicted. Increase
   to 200GB on the us-east-2b MachineSet (2 replicas — this is where
   builds land).

   `oc edit machineset cluster-z9hbt-2hdjl-worker-us-east-2b -n openshift-machine-api --context=gpt-oss-120b`
   Change `blockDevices[0].ebs.volumeSize` from 100 to 200. Then
   scale down/up to get new nodes with the larger disks. This is
   disruptive — pods on those nodes will be evicted and rescheduled.

4. **If vLLM works: retire TEI for batch, update ingestion config**
   Update `embed.py` to use the vLLM endpoint for batch embedding.
   Keep TEI running for now (query-time fallback) but document the
   migration path.

**Sequencing.** Deploy vLLM first (item 1) — if it doesn't work,
the TEI workaround from CLAUDE.md is still viable and the session
pivots to worker node scaling only. Worker node scaling (item 3) is
independent and can run in parallel with items 1-2. Item 4 only
happens if items 1-2 succeed.

**Constraints for the session:**
- vLLM v0.8.5 is required; v0.27.1 (latest tag) does not support
  `--task embed`. Pin the image tag explicitly.
- The GPU node (g6e.12xlarge, us-east-2c) has 1 GPU. vLLM will
  claim it — no other GPU workloads can run simultaneously.
- Worker node scaling (item 3) causes pod evictions on the replaced
  nodes. Schedule this after verifying all other services are healthy.
- Use `127.0.0.1` not `localhost` for port-forwarded connections.

**Session start protocol:**
- Premise checks: `oc get pods --context=gpt-oss-120b -n retrieval-hub`
  (cluster healthy?). `oc get nodes --context=gpt-oss-120b` (GPU node
  ready?). `oc get machineset -n openshift-machine-api --context=gpt-oss-120b`
  (current replica counts). `git log --oneline -3` (no surprise merges?).
- Rules with history: vLLM requires `--task embed`, `enableServiceLinks:
  false`, non-root `HF_HOME`, and GPU toleration — all four, every time
  (see CLAUDE.md lesson). Use `127.0.0.1` for port-forwards. Don't
  switch oc context or project.
- Stop-and-ask before: scaling down MachineSets (causes pod evictions);
  deleting existing TEI deployments; any changes to the PostgreSQL
  StatefulSet or PVCs.
- Close ritual: session summary + `/plan-next-session platform-ops`

## Remaining epic phases

### Phase 2: vLLM embedding + worker node scale-up (#66) — NEXT

Deploy vLLM on the GPU node as the batch embedding endpoint, scale
worker node EBS to 200GB. Merges the original Phase 2 (TEI
mitigation) with cluster resource scaling.

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

## What landed last session (2026-09-09)

Platform-ops Phase 1 complete. MCP server deployed (build 25) with
all ontology and graph-quality features. Ontology doctor CronJob
applied and verified (0 WARNs). Fixed deploy.sh to include
ontology_doctor.py in the build context. Cleaned up 21 stale builds
to resolve recurring BuildPodEvicted failures.

**Commits:** 740e08e, 59bb3aa (main)
**Closed:** #70
**See:** session-summaries/2026-09-09-platform-ops-mcp-deploy.md

## Watch out for

- Worker node scaling (MachineSet edit) causes pod evictions. Plan
  the scale-down/up when other workloads can tolerate disruption.
  PostgreSQL is a StatefulSet with PVC — it survives rescheduling,
  but verify data integrity after the node replacement.
- vLLM v0.8.5 image is ~8GB. First pull to the GPU node will take
  several minutes. The model download (nomic-embed-text-v1.5, ~550MB)
  also happens on first start if no PVC cache exists.
- The GPU node is in us-east-2c; worker pods are mostly in us-east-2b.
  Cross-AZ latency for embedding calls is ~1-2ms — negligible for
  batch but worth noting.
- `truncate_prompt_tokens: 512` must be set in vLLM embedding
  requests (see CLAUDE.md lesson on tokenizer mismatch).

## If blocked

- If the GPU node is unavailable or vLLM won't start, the TEI
  resilience workaround (batch_size=2, 10 retries, watchdog
  port-forward) is documented in CLAUDE.md and still works for
  batch ingestion. Skip to worker node scaling (item 3) as
  standalone value.
- If MachineSet edits are blocked by cluster policy, try increasing
  the ephemeral-storage limit on the BuildConfig instead, or add a
  build-pruning CronJob to keep the existing 100GB nodes clean.
