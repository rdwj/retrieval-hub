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

4. **Worker MachineSet EBS updated** — us-east-2b MachineSet changed
   from 100GB gp2 to 200GB gp3 for future nodes. Existing nodes not
   replaced (deferred to maintenance window).

## Manifests created

- `deploy/openshift/gpu-machineset-g6e-xlarge.yaml`
- `deploy/openshift/retrieval-hub/embedding/vllm-nomic.yaml`
- `scripts/test_batch_embed_vllm.py`

## Key decisions

- g6e.xlarge (1 GPU) over g6e.12xlarge (4 GPUs) to avoid competing
  with the LLM predictor
- Deferred worker node replacement to avoid StatefulSet disruption
- Added lessons to CLAUDE.md: vLLM rope_scaling workaround,
  single-GPU node strategy

## Issue status

- #66: Partially done — vLLM deployed and tested, EBS config edited
  but nodes not replaced yet

## Cluster state at session end

- `vllm-nomic-embedding`: 1/1 Running, 0 restarts, g6e.xlarge GPU node
- All retrieval-hub services: healthy
- 5 worker nodes (4 original + 1 new GPU)
- MachineSet count: 2 regular (us-east-2b), 1 regular (us-east-2c),
  1 quad-GPU (us-east-2c), 1 single-GPU (us-east-2c, new)
