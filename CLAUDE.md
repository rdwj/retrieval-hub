# RetrievalHub — Project Instructions

## Lessons Learned

### Embedding model dependencies must be explicit in container requirements

When adding or changing the embedding model used by the MCP server, verify
that all of the model's runtime dependencies are listed in
`retrieval-hub-mcp/requirements-deploy.txt`. The local venv pulls transitive
dependencies automatically, but the container's requirements file is a flat,
explicit list — anything missing there will cause an `ImportError` at query
time (the first call that triggers model load).

Nomic v1.5 (`nomic-ai/nomic-embed-text-v1.5`) requires `einops` for its
attention layers. PubMedBERT does not. When we switched models, the local
tests passed because `einops` was already installed transitively, but the
deployed container crashed on the first retrieval call.

**How to apply:** After changing `EMBEDDING_MODEL` in any ingestion script,
run `pip show <model-package>` and check its dependency tree. Cross-reference
against `requirements-deploy.txt`. Test the container with a retrieval query
before declaring the deploy done.

### Container memory limits must account for embedding model size

Embedding models loaded by `sentence-transformers` expand well beyond their
on-disk size. Nomic v1.5 is ~550MB on disk but uses ~1.5GB in memory. The
MCP server pod was OOMKilled at a 2Gi limit after the first query loaded the
model. Production limit is now 4Gi.

**How to apply:** When onboarding a new embedding model, check its parameter
count and estimate ~3x the on-disk weight for in-memory footprint, plus
headroom for the Python process (~500MB). Update the memory limit in
`retrieval-hub-mcp/openshift.yaml` before deploying.

### OpenShift route paths must not have trailing slashes for FastMCP

FastMCP binds to `/mcp` (no trailing slash) and 307-redirects `/mcp/` to
`/mcp`. If the OpenShift route has `path: /mcp/`, HAProxy only matches
requests with the trailing slash, and the redirect target (`/mcp`) returns
503 because the router doesn't match it. The result is that MCP clients get
503 on every connection attempt.

**How to apply:** Route paths in `openshift.yaml` for FastMCP servers must
not have a trailing slash. The current manifest is correct (`path: /mcp`);
don't reintroduce the trailing slash.

### Chunking tokenizer differs from embedding model tokenizer

The ingestion pipeline chunks text using cl100k_base (tiktoken), but BERT-
based embedding models (e.g., snowflake-arctic-embed) use WordPiece
tokenization which produces 1.3-1.5x more tokens for the same text.
A chunk of 512 cl100k_base tokens can be 650-750+ BERT tokens, exceeding
the model's 512 max_position_embeddings.

When serving embeddings via vLLM, the server rejects inputs that exceed
max_model_len with a 400 error. The fix is to include
`"truncate_prompt_tokens": 512` in the `/v1/embeddings` API request
payload, which tells vLLM to truncate rather than reject.

**How to apply:** When using a BERT-based embedding model with a remote
vLLM endpoint, always set `truncate_prompt_tokens` in the API request.
The `_remote_embed()` function in `embed.py` does this by default. The
token loss from truncation is minimal (affects only the longest chunks)
and the alternative — reducing cl100k_base chunk size to 256 — wastes
significant context window on all chunks just to accommodate a few
outliers.

### vLLM version and embedding model compatibility

vLLM `latest` tag (v0.27.1 as of August 2026) does not support the
`--task embed` flag needed for BERT-based embedding models. vLLM v0.8.5
supports it. When deploying embedding models on vLLM, pin the image to
`vllm/vllm-openai:v0.8.5` (or a version known to support `--task embed`).

Also: OpenShift GPU nodes typically have a `nvidia.com/gpu` NoSchedule
taint. Add a toleration in the pod spec. And the Kubernetes Service
auto-generated env vars (e.g., `VLLM_SNOWFLAKE_EMBEDDING_PORT`) collide
with vLLM's config parsing — set `enableServiceLinks: false` in the pod
spec to prevent this.

**How to apply:** For vLLM embedding deployments, always include in the
pod spec: (1) GPU toleration, (2) `enableServiceLinks: false`,
(3) `HF_HOME` env var pointing to the PVC mount (not `/root/` since
OpenShift runs non-root), (4) `--task embed` in the serve args.

### Use 127.0.0.1 not localhost for local Postgres connections

When `oc port-forward` runs concurrently with a local Podman Postgres
container on the same port, `localhost` resolves non-deterministically
to IPv4 (Podman via gvproxy) or IPv6 (oc port-forward). Different
connections within the same script may hit different backends, causing
phantom data and incorrect row counts.

This happened during the aircraft chunking sweep: `write_chunks` wrote
to one backend and `count_rows` read from another, reporting 2x the
expected rows. The evaluation was unreliable because queries hit a table
with stale or wrong data.

**How to apply:** All local Postgres connection strings in scripts must
use `127.0.0.1` (IPv4 literal) instead of `localhost`. This forces the
connection to the Podman container regardless of what `oc port-forward`
sessions are running. Check `lsof -i :<port>` if row counts or query
results look wrong — a dual IPv4/IPv6 listener is the tell.
