# Session Summary — 2026-09-09 · platform-ops · vLLM deploy + checkpoint-resume

**Plan:** NEXT_SESSION-platform-ops.md / #66, #67   **Commits:** b48f8dd..e7128ec (main)
**Deployed:** dev (cluster gpt-oss-120b)   **Model:** Opus 4.6

## Plan vs. actual
Planned: Phase 2 (vLLM embedding + worker node scale-up) and Phase 3
(checkpoint-resume). Shipped: both phases. No slippage.
Scope: expanded slightly — also updated model registry, linked all
source recipes, and retired nomic TEI (unplanned but natural follow-on).

## Shipped
- `b48f8dd` — g6e.xlarge MachineSet, vLLM v0.8.5 nomic deployment
  with rope_scaling workaround, batch embedding test (78.5 chunks/sec)
- `a9fdfd2` — Nomic TEI retired (0 replicas), model_endpoint registry
  updated (nomic→vLLM, snowflake→khsm8), tei-nomic.yaml marked retired
- `e7128ec` — Checkpoint-resume: incremental embed+write loop in
  pipeline.py, write.py batch functions, --resume flag on 3 scripts,
  7 tests passing against cluster pgvector
- SQL (cluster only): model_endpoint updates, recipe_version rows
  created for 10 sources, all sources linked to recipes with
  embedding.model

## Verification & confidence
- vLLM: smoke test (768-dim vector), batch test (2000 chunks, 78.5/sec,
  0 restarts), MCP retrieval verified through served endpoint (pod
  memory stayed at 160Mi — no local model load)
- Checkpoint-resume: 7 unit tests against cluster pgvector (simulated
  interrupt, resume, fresh-after-partial, batch accumulation)
- Confidence: **high** for vLLM deployment (live-proven on real data).
  **medium** for checkpoint-resume (tested against real DB but not yet
  exercised in a real interrupted ingestion run)

## Judgment calls & deviations
- Created a new g6e.xlarge MachineSet instead of sharing the quad-GPU
  node — the LLM predictor consumed all 4 GPUs
- Worker EBS: added a 3rd 200GB node instead of rolling-replacing
  existing 100GB nodes (user decision: avoid StatefulSet disruption)
- vLLM rope_scaling bug: `--hf-overrides '{"rotary_scaling_factor": 1.0}'`
  — no-op scaling factor bypasses NomicBert crash in v0.8.5
- Checkpoint-resume uses DB table as checkpoint (not file-based) — works
  in-cluster without shared filesystem
- Custom-flow ingestion scripts (aircraft, code, va-cpg, etc.) don't
  have --resume yet — they need the same pattern applied to their
  custom embed+write code

## Backlog delta
Filed: none · Closed: none (propose closing #66, #67 below)
Memory: updated `design_shared_model_serving` (endpoint topology)
Deferred: custom-script checkpoint-resume — separate work per script

## Drift & forward-collisions
- Backward — #66 (TEI memory leak): addressed by replacing TEI with
  vLLM for nomic. TEI PubMedBERT still runs but is a different issue
  (it was never the source of OOM under batch). Propose close with
  note that PubMedBERT TEI remains for va-cpg/pubmed queries.
- Backward — #67 (checkpoint-resume): pipeline.ingest() now has resume
  support. Issue asked for file-based checkpoints; we used DB-based
  (better for in-cluster Jobs). Propose close.
- Forward — #27 (production ingestion runners): checkpoint-resume is a
  prerequisite. The DB-based checkpoint design works naturally with
  Kubernetes Jobs (no shared filesystem needed).

## For the reviewer
- Sanity-check: the `rotary_scaling_factor: 1.0` workaround — is this
  a no-op or does it subtly change embedding quality? We set
  max_model_len=512 which is within the base 2048 positions, so dynamic
  scaling shouldn't be active regardless.
- Thin verification: custom-flow scripts still do all-at-once embed+write.
  They're the scripts most likely to be run against large sources.
- Wants guidance: should we file a vLLM upstream issue for the NomicBert
  rope_scaling bug, or is it too version-specific (v0.8.5)?

## Risks / watch-fors
- g6e.xlarge GPU node costs ~$1.25/hr. Scale to 0 when not needed.
- 3rd worker node in us-east-2b increases cluster cost. Monitor whether
  builds actually land there (they may prefer existing nodes).
- TEI PubMedBERT endpoint is marked unhealthy in the model_endpoint
  table. The model health probe CronJob is failing (check-10 of this
  session's pod listing showed Error pods). Should investigate or
  update the probe to check vLLM instead.
