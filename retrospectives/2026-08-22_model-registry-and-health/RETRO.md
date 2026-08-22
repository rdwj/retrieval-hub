# Retrospective: Model Registry and Health Epic

**Date:** 2026-08-22
**Effort:** Platform-level model registry for endpoint resolution, health probing, and ops observability
**Commits:** `8abbf01`..`9d45229` (10 commits)

## What We Set Out To Do

Decouple embedding model hosting from the MCP server pod. Six phases:
data model + API, deploy Nomic as standalone vLLM, wire retrieve/refine
to the registry, wire ingestion, active health probing, and health
status on describe_source. Additionally, create reproducible deployment
tooling for the embedding models already running on two clusters.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Phase 2 (deploy Nomic v1.5) skipped | Good pivot | Cluster inventory showed no dataset needs a remote Nomic endpoint. Would have consumed the last GPU slot with no consumer. |
| Seeded Snowflake + PubMedBERT instead of Nomic | Good pivot | Register what's actually deployed, not what was hypothetically planned. |
| Added deploy script + Makefile + README (not in plan) | Scope addition | Emerged from cluster inventory. Makes the stack reproducible on new clusters. |
| Cleaned up four superseded manifest files | Scope addition | Discovered during inventory. Old files had wrong PVC names and resource requests. |
| Resolve in caller, not in ChunkEmbedder | Good pivot | Original plan said to modify ChunkEmbedder. Resolving in the caller and passing explicitly is cleaner and matches the Phase 3 pattern. |
| Fallback to recipe endpoint | Good pivot | Not in original plan. Ensures local dev works without seeding the registry. |

## What Went Well

- Cluster inventory before coding prevented building the wrong thing (Nomic deployment nobody would use).
- The registry API surface (3 functions, 3 exceptions) was right-sized and served all downstream phases without modification.
- Fallback pattern (registry -> recipe -> local) made every change backward-compatible. No breaking changes.
- Parallel sub-agent delegation worked well throughout. Most phases had 2-3 agents running simultaneously.
- 30 new tests, 332 total, all passing. Good coverage of error paths (not-found, unhealthy, fallback).
- Clean commit history: 10 commits, each a logical unit. Prep commits separated from feature commits.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Deployment scripts not tested against a live cluster | Follow-up | Scripts were validated for argument handling and error paths but not `oc apply`'d to either cluster this session. Next deploy is the real test. |
| MCP server health integration not tested live | Follow-up | describe_source health field and ModelUnavailableError handling were unit-tested only. Need a running MCP server against a seeded catalog DB to verify end-to-end. |
| Health probe not deployed as a CronJob | Accept | Script exists and works locally. CronJob manifest is a future ops task. |
| PubMed ingestion now resolves PubMedBERT from registry (remote TEI) | Watch | Previously used local sentence-transformers. The switch to remote TEI is correct but changes latency characteristics. Verify on next PubMed re-ingest. |
| No integration test for the full resolve chain (registry -> adapter -> embed) | Accept | Unit tests cover each layer. Full chain requires a running embedding endpoint. |
| Sweep/eval scripts unchanged | Accept | They still use local embedding or explicit endpoints. Fine for experiments. |

## Action Items

- [ ] Test deploy script against agent-security-dev-3: `./scripts/deploy-embedding.sh vllm-snowflake --context=agent-security-dev-3`
- [ ] Test describe_source health field with a running MCP server
- [ ] Run PubMed ingestion to verify remote TEI embedding works via registry resolution

## Patterns

Compared with the code-source-epic retro (2026-08-18):

**Continue:**
- Sub-agent delegation for parallel implementation. Both epics used this and it works.
- Cluster/environment inventory before coding. Code-source epic didn't do this and had model download delays; this epic did and caught the Nomic non-issue early.
- Fallback patterns for backward compatibility. The code-source epic reused DocumentAdapter instead of a new CodeAdapter (same principle: don't break what works, extend it).

**Start:**
- Live deployment verification as part of the epic. Both epics stopped at "tests pass" without deploying. The deploy scripts exist now, so the barrier is lower.
- Running the MCP server locally with a seeded DB as a final smoke test. Both epics had MCP server changes that were only unit-tested.

**Watch:**
- Epic scope grew from 6 phases to 6 phases + deployment infra. Healthy growth, but watch for scope creep in future epics.
