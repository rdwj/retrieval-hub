# Embedding Model Deployment

Embedding models are cluster infrastructure, not per-service dependencies. Each
data source declares the model it needs in its recipe; the platform ensures that
model is served. Services (MCP server, BFF, agents) call the shared endpoint
rather than loading models in-process.

## Deployed Models

### TEI PubMedBERT (CPU-only)

| Field | Value |
|-------|-------|
| Model | NeuML/pubmedbert-base-embeddings (768 dims, 110M params) |
| Manifest | `tei.yaml` |
| Cluster | gpt-oss-120b |
| Service | `retrieval-hub-embedding:8080` (ClusterIP, no Route) |
| API | `POST /embed` with body `{"inputs": ["text1", "text2"]}` |
| Hardware | CPU-only. Requests 1 CPU / 1Gi, limits 4 CPU / 4Gi |
| Storage | 5Gi PVC (`retrieval-hub-embedding-cache`) for model weights |
| Used by | PubMed Hypertension data source |

### vLLM Snowflake Arctic (GPU)

| Field | Value |
|-------|-------|
| Model | Snowflake/snowflake-arctic-embed-m-v1.5 (768 dims) |
| Manifest | `vllm-snowflake.yaml` |
| Cluster | agent-security-dev-3 |
| Service | `vllm-snowflake-embedding:8000` (ClusterIP + Route) |
| API | `POST /v1/embeddings` (OpenAI-compatible) |
| Hardware | Requires 1x nvidia.com/gpu. Requests 2 CPU / 4Gi, limits 4 CPU / 8Gi |
| Storage | 10Gi PVC (`vllm-snowflake-model-cache`) for model weights |
| Used by | Aircraft Maintenance data source |

### Not deployed remotely (local-only)

**nomic-ai/nomic-embed-text-v1.5** is used by the VA CPG and Tale of Two Cities
data sources via local sentence-transformers during ingestion. No remote endpoint
exists yet.

## Deploying to a New Cluster

Quick start with make:

```bash
make deploy-embedding-tei CONTEXT=<cluster-context>
make deploy-embedding-snowflake CONTEXT=<cluster-context>
```

Or directly with the script:

```bash
./scripts/deploy-embedding.sh tei-pubmedbert --context=<ctx> [--namespace=<ns>]
./scripts/deploy-embedding.sh vllm-snowflake --context=<ctx> [--namespace=<ns>]
```

Namespace defaults to `retrieval-hub`.

## Prerequisites

### TEI (CPU)

- Namespace must exist.
- `gp3-csi` StorageClass available (or edit the PVC in `tei.yaml`).

### vLLM (GPU)

- Namespace must exist.
- `gp3-csi` StorageClass available (or edit the PVC in `vllm-snowflake.yaml`).
- At least 1 available GPU node with `nvidia.com/gpu` resource.
- GPU nodes may have a `nvidia.com/gpu` NoSchedule taint -- the manifest
  includes the toleration.
- vLLM image pinned to v0.8.5. Later versions may not support `--task embed`.

## API Differences

| Framework | Embed endpoint | Request body | Response shape |
|-----------|---------------|--------------|----------------|
| TEI | `POST /embed` | `{"inputs": ["text1", "text2"]}` | `[[0.1, 0.2, ...], [0.3, ...]]` |
| vLLM | `POST /v1/embeddings` | `{"model": "...", "input": ["text1"]}` | `{"data": [{"embedding": [...]}]}` |

Both expose `GET /health` for readiness checks.

## Verifying a Deployment

Port-forward from your workstation and test with curl:

```bash
# TEI PubMedBERT
oc port-forward svc/retrieval-hub-embedding 8080:8080 --context=<ctx> -n retrieval-hub
curl -s http://127.0.0.1:8080/embed -H 'Content-Type: application/json' \
  -d '{"inputs": ["test embedding"]}'

# vLLM Snowflake
oc port-forward svc/vllm-snowflake-embedding 8000:8000 --context=<ctx> -n retrieval-hub
curl -s http://127.0.0.1:8000/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model": "Snowflake/snowflake-arctic-embed-m-v1.5", "input": ["test embedding"]}'
```

## Troubleshooting

**First deploy is slow.** Model weights download from Hugging Face Hub on first
start. The PVC caches them for subsequent restarts.

**OOMKilled.** Check memory limits against model size. BERT models expand roughly
3x from disk to memory. See the "Container memory limits" lesson in the project
CLAUDE.md.

**vLLM PORT env var collision.** The manifest sets `enableServiceLinks: false` to
prevent Kubernetes-generated service env vars from colliding with vLLM's config
parsing. If you see startup errors about port parsing, verify this is set.

**vLLM version.** Must be v0.8.5 for `--task embed` support. The `latest` tag
(v0.27.1 as of August 2026) does not support it.

**StorageClass.** If `gp3-csi` is not available on the target cluster, edit the
PVC `storageClassName` in the manifest before deploying.
