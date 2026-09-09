# Retrospective: Platform Ops Epic

**Date:** 2026-09-09
**Effort:** Operational reliability and deployment catchup -- ship accumulated features, fix TEI/ingestion pain points, set up production ingestion runners
**Issues:** #27 (closed), #66 (closed), #67 (closed), #70 (closed)
**Commits:** b48f8dd..9b20ca1 (6 commits across 4 sessions, all on 2026-09-09)

## What We Set Out To Do

Four phases to make the platform operationally reliable:

1. Deploy the MCP server with latest ontology and graph features (#70)
2. Replace TEI with vLLM for embedding, add a dedicated GPU node (#66)
3. Add checkpoint-resume to the ingestion pipeline (#67)
4. Deploy ingestion as in-cluster Kubernetes Jobs (#27)

The overarching goal: ingestion should be runnable in-cluster without local port-forwards, crash-resilient, and not dependent on TEI (which OOMKilled every ~25 minutes under batch load).

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| TEI retirement during Phase 2 | Scope addition | Natural follow-on from vLLM deploy. Scaled TEI to 0, updated model registry. Low effort, high value. |
| g6e.xlarge MachineSet instead of sharing quad-GPU node | Good pivot | LLM predictor consumed all 4 GPUs. Single-GPU node is ~$1.25/hr vs ~$6.50/hr for the quad. |
| Health probe needed no changes | Scope reduction | Originally planned as item 5 in Phase 4. Probe was already checking vLLM nomic correctly. Error pods were transient PubMedBERT connection refused, not probe bugs. |
| tree-sitter lazy import fix | Missed | Pipeline eagerly imported code_ast, which requires tree-sitter (not in core deps). Crashed the ingestion container on first run. Only caught by actually running in the container. |
| 21 old builds cleaned up | Scope addition | BuildPodEvicted failures from ephemeral storage pressure. Cleaned up to unblock the MCP server deploy. |

## What Went Well

- **TEI pain eliminated.** vLLM ran for 4+ hours at 78.5 chunks/sec with zero OOMs. The #1 recurring ops problem is gone. Container memory dropped from 32Gi (TEI, still OOMing) to 2Gi (vLLM, stable).
- **Checkpoint-resume worked first try.** DB-based checkpoint (not file-based) is the right design for K8s Jobs -- no shared filesystem needed. Resume correctly detected 769 pre-existing chunks and skipped re-embedding.
- **Ingestion Job pattern is simple and proven.** `oc create -f ingestion-job-hetionet.yaml` -- 9 seconds to completion. The deploy.sh binary build pattern matches the MCP server's and is reproducible.
- **Deploy scripts cover the full stack.** MCP server, embedding models, ingestion runner -- all have deploy.sh scripts with the same pattern. New cluster setup is scripted.
- **Cost-conscious GPU provisioning.** Dedicated g6e.xlarge at ~$1.25/hr, scalable to 0 when not needed.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Custom-flow scripts lack --resume | Follow-up | aircraft, code, va-cpg, pubmed, tale-of-two-cities still use all-at-once embed+write |
| tree-sitter import only caught by container test | Process gap | Add an import-guard test that verifies pipeline.py imports without optional deps |
| Docling-family sources can't run in ingestion container | Accept | Would need [ingest] extras (sentence-transformers, docling). Heavier image variant for later. |
| PubMedBERT recommendation stale in docs | Fix now | Third retro flagging this. Fixing in this session. |
| No CI/CD for ingestion image builds | Accept | Manual deploy.sh is fine at current ingestion frequency |

## Action Items

- [x] Fix stale PubMedBERT references in docs (this session)
- [ ] Add import-guard test: `python -c "from retrieval_hub.ingestion.pipeline import ingest"` without tree-sitter installed
- [ ] Port --resume to custom-flow ingestion scripts (per-script work, not urgent)

## Patterns

Compared with prior retros (code-source, data-products, model-registry-and-health, eval-convergence, ontology):

**Continue:**
- Sub-agent delegation for parallel work. Sixth consecutive positive retro. The maker/checker pattern caught the tree-sitter import issue via the review agent before the first build attempt.
- Deploy scripts that are reproducible and follow the same pattern. Every component now has deploy.sh with binary build. New cluster onboarding is scripted.
- Per-batch checkpointing for long-running jobs. Lesson from eval-convergence (30+ hours of lost compute) now applied to ingestion.
- Smoke tests before full runs. Every session tested small before going big.

**Start:**
- **Import-guard tests for container-deployed code.** The tree-sitter issue was only caught by running in the container. A test that imports pipeline.py without optional deps would catch this class of issue in CI.
- **Fix stale doc references promptly.** PubMedBERT has been flagged in three retros. Process improvement: add a `/docs-refresh` run to session-close when a model or config change lands.

**Stop:**
- Nothing systemic. The epic stayed tightly scoped and delivered cleanly.

**Watch:**
- BuildPodEvicted may recur as builds accumulate. Consider a build pruning policy or CronJob.
- gpt-oss-120b cluster instability remains a background concern (flagged in eval-convergence retro too).
