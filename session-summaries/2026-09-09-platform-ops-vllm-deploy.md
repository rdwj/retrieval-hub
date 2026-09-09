# Session Summary: Platform-ops Phase 2 — vLLM Embedding Deployment

**Date:** 2026-09-09
**Epic:** platform-ops
**Phase:** 2 (vLLM embedding + worker node scale-up)

## What landed

1. **Single-GPU MachineSet (g6e.xlarge)** — New MachineSet
   `gpu-g6e1-cluster-z9hbt-2hdjl-worker-us-east-2c` for a g6e.xlarge
   instance (1x L40S GPU, 4 vCPU, 32 GiB). The quad-GPU g6e.12xlarge
   was fully consumed by the LLM predictor, so a separate single-GPU
   node serves embedding workloads at ~$1.25/hr.

2. **vLLM v0.8.5 with nomic-embed-text-v1.5** — Deployed after fixing
   a NomicBert rope_scaling bug in vLLM (rotary_scaling_factor: null
   crashes DynamicNTKScalingRotaryEmbedding). Workaround:
   `--hf-overrides '{"rotary_scaling_factor": 1.0}'`. Uses Recreate
   deployment strategy (single GPU can't surge).

3. **Batch embedding test** — 1000 chunks in 23.6s (42.3 chunks/sec),
   2000 chunks in 25.5s (78.5 chunks/sec). Zero pod restarts.
   TEI OOM'd every ~25 min under the same load.

4. **Worker node scaling** — us-east-2b MachineSet updated to 200GB
   gp3 for new nodes, then scaled from 2 to 3 replicas. New 200GB
   node joined the cluster; existing 100GB nodes stay as-is.

5. **Model endpoint registry updated** — nomic endpoint switched from
   TEI to vLLM (`vllm-nomic-embedding:8000`). Snowflake endpoint
   updated to khsm8 external cluster. All source recipes now include
   `embedding.model` so the MCP server routes queries through served
   endpoints instead of loading models locally (which would OOM the
   1Gi pod).

6. **Nomic TEI retired** — Scaled to 0 replicas. vLLM handles all
   nomic query-time and batch embedding. PubMedBERT TEI kept running
   for va-cpg and pubmed-hypertension sources.

## Manifests created/modified

- `deploy/openshift/gpu-machineset-g6e-xlarge.yaml` — new
- `deploy/openshift/retrieval-hub/embedding/vllm-nomic.yaml` — new
- `deploy/openshift/retrieval-hub/embedding/tei-nomic.yaml` — retired (replicas: 0)
- `scripts/test_batch_embed_vllm.py` — new

## Database changes (cluster only, not in code)

- `model_endpoint`: nomic → vLLM URL, snowflake → khsm8 URL
- `recipe_version`: created for 10 sources missing recipes, linked
  `embedding.model` so registry lookup works at query time

## Key decisions

- g6e.xlarge (1 GPU) over g6e.12xlarge (4 GPUs) to avoid competing
  with the LLM predictor
- Added 3rd worker node instead of replacing existing ones
- Added lessons to CLAUDE.md: vLLM rope_scaling workaround,
  single-GPU node strategy

## Issue status

- #66: Done — vLLM deployed, tested, registry updated, TEI retired,
  worker node added

## Cluster state at session end

- `vllm-nomic-embedding`: 1/1 Running, 0 restarts, g6e.xlarge GPU node
- `retrieval-hub-embedding-nomic` (TEI): 0 replicas (retired)
- All retrieval-hub services: healthy
- 6 worker nodes (3 regular in us-east-2b [1 with 200GB], 1 regular
  in us-east-2c, 1 quad-GPU, 1 single-GPU)
