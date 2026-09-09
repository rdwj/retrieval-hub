# Next Session -- Platform Ops

## Epic: Operational reliability and deployment catchup

Ship the accumulated features to the deployed MCP server, fix the
recurring TEI/ingestion pain points, and set up production ingestion
runners.

Issues: #27 (open), #66 (closed), #67 (closed), #70 (closed)

## Next: Production ingestion runners (#27) — final epic phase

Deploy ingestion as Kubernetes Jobs so sources can be re-ingested
in-cluster without local port-forwards. This is the last item in
the platform-ops epic.

1. **Containerize the ingestion pipeline**
   Create a Containerfile for the ingestion code. The image needs
   `src/retrieval_hub/` (core library), `scripts/` (ingestion
   scripts), and the Python dependencies. Base on UBI9 Python.
   The container connects to in-cluster services directly
   (`retrieval-hub-pg:5432`, `vllm-nomic-embedding:8000`) — no
   port-forwards.

2. **Create a Job manifest template**
   A parameterized Job manifest that takes the source slug, data
   directory (PVC-mounted or fetched), and optional `--resume` flag.
   The Job runs the appropriate `ingest_*.py` script with in-cluster
   DB URLs. Use a ConfigMap or Job args for per-source config.

   Start with one concrete Job for a small source (tale-of-two-cities
   or hetionet) to prove the pattern, then generalize.

3. **Test end-to-end: `oc create job` → query via MCP**
   Create the Job, watch it complete, verify chunks land in pgvector,
   query the source through the MCP server.

4. **Cleanup: remove TEI cooldown sleeps from embed.py**
   The 0.5s inter-batch sleep and 5s/50-batch cooldown in
   `ChunkEmbedder.embed_chunks()` were TEI memory-leak mitigations.
   vLLM doesn't need them. Remove or gate behind a flag.

5. **Cleanup: fix model health probe CronJob**
   The probe is failing (Error pods in retrieval-hub namespace).
   Update it to check vLLM nomic at port 8000 in addition to TEI
   endpoints. Drop the nomic TEI check since it's scaled to 0.

**Sequencing.** Items 1-3 are the core deliverable (sequential).
Items 4-5 are independent cleanups — do them first as warmup or
last as polish.

**Constraints for the session:**
- Use Red Hat UBI9 base image for the container.
- `--platform linux/amd64` for container builds (Mac → OpenShift).
- The ingestion container needs the `psycopg[binary]` and `pgvector`
  packages for DB writes, plus `httpx` for remote embedding.
- In-cluster DB URLs use service DNS: `postgresql://retrievalhub:
  <password>@retrieval-hub-pg:5432/retrievalhub`. The password is
  in the `retrieval-hub-pg` secret.
- Use `127.0.0.1` not `localhost` if any port-forwarding is needed
  during testing.

**Session start protocol:**
- Premise checks: `oc get pods --context=gpt-oss-120b -n retrieval-hub`
  (vLLM and PG still running?). `oc get nodes --context=gpt-oss-120b`
  (GPU node still up?). `git log --oneline -5` (no surprise merges?).
- Rules with history: vLLM needs `--hf-overrides
  '{"rotary_scaling_factor": 1.0}'` and `--task embed` (CLAUDE.md).
  Container builds need `chmod 644` on source files (CLAUDE.md).
  Use `--context=gpt-oss-120b -n retrieval-hub` on every oc command.
- Stop-and-ask before: deleting existing pgvector tables; scaling
  down GPU or worker MachineSets; any changes to the PostgreSQL
  StatefulSet.
- Close ritual: session summary + `/plan-next-session platform-ops`
  (or `/retro platform-ops` if #27 is complete and the epic is done)

## Remaining epic phases

### Phase 4: Production ingestion runners (#27) — NEXT (final phase)

Deploy ingestion as Kubernetes Jobs in-cluster.

**Definition of done:** At least one source can be re-ingested via
`oc create job` without local port-forwards.

**Dependencies:** Phase 2 (done) + Phase 3 (done).

## What landed last session (2026-09-09)

Phases 2 and 3 both completed. vLLM v0.8.5 deployed on a dedicated
g6e.xlarge GPU node (78.5 chunks/sec, zero OOM). Model registry
updated (nomic→vLLM, snowflake→khsm8). All 11 source recipes linked
with embedding.model. Nomic TEI retired. 200GB worker node added.
Checkpoint-resume implemented in pipeline.py with DB-based checkpoint
and --resume flag. #66 and #67 closed.

**Closed:** #66 — TEI memory leak (replaced by vLLM)
           #67 — Checkpoint-resume (incremental embed+write)

**Commits:** b48f8dd..285ea78 (main)

**See:** session-summaries/2026-09-09-platform-ops-phase2-3.md

## Watch out for

- The g6e.xlarge GPU node costs ~$1.25/hr. Scale to 0 when not
  actively needed: `oc scale machineset
  gpu-g6e1-cluster-z9hbt-2hdjl-worker-us-east-2c --replicas=0
  -n openshift-machine-api --context=gpt-oss-120b`
- PubMedBERT TEI endpoint is marked unhealthy. The model health
  probe CronJob pods are in Error state — item 5 above addresses
  this.
- Custom-flow ingestion scripts (aircraft, code, va-cpg, pubmed,
  tale-of-two-cities) still use all-at-once embed+write — no
  --resume support. Only pipeline-based scripts (fhir, hetionet,
  snomed) have it. The Job template should use pipeline-based
  scripts where possible.
- embed.py still has TEI cooldown sleeps that slow batch embedding
  unnecessarily with vLLM — item 4 above addresses this.

## If blocked

- If container builds fail (registry auth, build eviction), use
  the remote-builder agent on ec2-dev-2 or try an OpenShift
  BuildConfig.
- If the ingestion Job can't connect to vLLM (GPU node down),
  the --resume flag means you can restart the Job later without
  losing progress. Or fall back to local embedding in the
  container (heavier image, slower, but no GPU dependency).
