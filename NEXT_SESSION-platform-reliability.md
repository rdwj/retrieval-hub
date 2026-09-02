# Next Session -- Platform Reliability

## Priority queue

1. **#40 Memgraph PVC migration** — replace emptyDir with PVC so graph
   data survives pod restarts. Small scope, high reliability gain.
2. **#29 Elicitation** — retrieve/refine: clarifying questions for
   low-confidence results. New epic, needs design.
3. **#31 MCP-level end-to-end eval** — integration test path through
   the deployed MCP server. Builds on existing EvalHub infrastructure.
4. **#27 Production ingestion runners** — Tekton/Job-based ingestion
   for reproducible, scheduled onboarding.

## Next: Memgraph PVC migration (#40)

Replace the emptyDir volume in the Memgraph StatefulSet with a
PersistentVolumeClaim so graph data persists across pod restarts.

1. **Read current StatefulSet manifest.**
   Check `retrieval-hub-mcp/openshift.yaml` or wherever the Memgraph
   StatefulSet is defined. Identify the emptyDir volume and mount path.

2. **Create PVC and update StatefulSet.**
   Add a `volumeClaimTemplates` entry for 10Gi (current data is ~23K
   nodes, well under 1Gi, but leave room for growth). Update the
   volume mount to reference the PVC instead of emptyDir.

3. **Apply and verify.**
   Apply the updated manifest. The pod will restart with a fresh PVC.
   Re-run the three graph ingestion scripts to populate Memgraph.
   Then force-restart the pod and verify data survives:
   `oc delete pod memgraph-0` → wait for restart → query node count.

4. **Update documentation.**
   Remove the emptyDir warnings from CLAUDE.md and session plan files.
   Update the "watch out for" sections that reference data loss on
   pod restart.

5. **Rebuild MCP server (if needed).**
   The MCP server connects to Memgraph via `MEMGRAPH_BOLT_URI`. The
   PVC change is transparent to the server — no rebuild needed unless
   the service name changes.

**Constraints:**
- Cluster: gpt-oss-120b, namespace: retrieval-hub
- StatefulSet already exists: `memgraph-0`
- Port-forwards needed: Memgraph bolt (7687), Postgres catalog (5434),
  Postgres vectors (5433), TEI embedding (8090)
- Re-ingestion required after PVC creation (fresh volume = empty DB)
- Use `127.0.0.1` not `localhost` for port-forwarded connections

**Session start protocol:**
- `oc get pods --context=gpt-oss-120b -n retrieval-hub` — cluster healthy?
- `oc get pvc --context=gpt-oss-120b -n retrieval-hub` — any existing PVCs?
- Read the current Memgraph StatefulSet manifest before modifying

**If blocked:**
- If the cluster doesn't support dynamic PVC provisioning, check
  available StorageClasses: `oc get sc --context=gpt-oss-120b`
- If PVC binding fails, try a smaller size or different access mode
