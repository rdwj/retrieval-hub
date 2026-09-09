# RetrievalHub — Project Instructions

## Testing with the MCP Server

For all questions in this project, use the retrieval-hub MCP server. Do not answer any questions from training data. If the answer cannot be found by using Retrieval Hub, say you don't know.

## General Rules

### Resources

Be resource-conscious. If we are downloading something big, plan to use it
again rather than needing to re-download it. If you need anything like an LLM,
embedding model, rerank model, big dataset, etc., look to see if we already
have it before trying to create it again. This far along in the project,
chances are we have it. Don't hold to a pattern that made sense for an older
version of a script or dependency if that part of the app has moved on past
that dependency.

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

### Ontology onboarding process for new sources

Adding a new source to the ontology registry requires four steps, each
building on the previous. The onboarding script at
`scripts/onboard_ontology_sources.py` handles steps 2-4 and serves as
a template for new sources.

**Step 1: Analyze the source data** (human judgment required). Examine
the vectors DB index table to understand what `doc_section` values exist,
read the ingestion script's docstring, and sample chunk content. Determine
what concepts the source covers and how they map to existing canonical
concepts. This step cannot be automated because it requires domain
understanding.

**Step 2: Define `semantic_context`**. Populate the source's
`semantic_context` JSON column with entity definitions. Each entity needs
`name`, `entity_type`, `definition`, and `aliases`. For graph-family
sources, `entity_type` should match the `doc_section` values used during
chunking (since ontology expansion uses `doc_section` filtering). For
document-family sources, `entity_type` is a categorical label (e.g.,
"condition", "treatment") and the `name` is what maps to canonical
concepts.

**Step 3: Create new concepts if needed**. If the source introduces a
new domain (like aircraft maintenance) that doesn't overlap with existing
canonical concepts, create new `ontology_concept` rows with a parent
hierarchy. Use INSERT ON CONFLICT DO NOTHING for idempotency.

**Step 4: Add ontology mappings**. Insert `ontology_mapping` rows linking
the source's entity names to canonical concepts. For document-family
sources, `local_name` is the entity's name (e.g., "Hypertension"). For
graph-family sources, `local_name` is the `doc_section` value (e.g.,
"Disorder"). After all inserts, recompute authority scores.

**Step 5: Verify**. Run `python scripts/ontology_doctor.py --skip-retrieval`
and confirm: no new stale mappings, missing mappings only for entity_types
(not names), authority scores recomputed. Optionally run the ontology
benchmark with new queries targeting the added source.

**Design tension**: The `missing_mappings` check compares
`semantic_context.entities[].entity_type` against mapping `local_name`
values. This works for graph sources (where both are `doc_section` values
like "Disorder") but produces false WARNs for document sources (where
`entity_type` is "condition" but `local_name` is "Hypertension"). The
`stale_mappings` check handles this correctly by comparing against names,
types, and aliases. A future fix should align `missing_mappings` to do
the same.

**How to apply:** Use `scripts/onboard_ontology_sources.py` as a
template. Copy a source definition block, fill in the semantic_context
and mappings, run with `--dry-run` first. The script is idempotent (all
inserts use ON CONFLICT DO NOTHING) and safe to re-run.

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

### Metadata-only changes don't need re-ingestion

When a pipeline change only affects metadata columns (doc_title,
doc_url, doc_section) and not chunk text or embeddings, apply the fix
with SQL UPDATEs rather than re-running the full ingestion pipeline.
Re-ingestion re-embeds all chunks, which is expensive in compute time
and API usage. The embeddings are identical when only metadata changes.

This applies to both local and cluster databases. For cluster fixes,
port-forward the cluster PostgreSQL and run the UPDATEs directly.

**How to apply:** Before triggering re-ingestion, ask: did the chunk
text or embedding model change? If only metadata columns changed, write
SQL UPDATEs. Reserve re-ingestion for changes to chunking boundaries,
chunk text, or the embedding model.

### TEI CPU has a memory leak under sustained batch embedding

The Hugging Face Text Embeddings Inference (TEI) container on CPU
(`ghcr.io/huggingface/text-embeddings-inference:cpu-latest`) accumulates
memory over hundreds of consecutive embedding requests and never releases
it. Even at 32Gi, the nomic-embed-text-v1.5 pod OOMs every ~25 minutes
under batch ingestion load.

The production embedding endpoint is designed for query-time use (single
texts), not batch ingestion of thousands of chunks. For batch ingestion,
the resilience approach is:

1. Set `embedding_batch_size=2` in the pipeline (small batches)
2. Use 10 retries with exponential backoff (catches pod restarts)
3. Add `RemoteProtocolError` and HTTP 429 to the retry catch list
4. Run a self-healing port-forward watchdog (auto-reconnects when
   the pod restarts during `oc port-forward`)
5. Keep the pod memory at 32Gi with `--max-client-batch-size 8`

This lets the pipeline survive repeated pod OOM restarts. Long-term
fix: either swap TEI for vLLM (better memory management) or add
checkpointed embedding to the pipeline (save intermediate vectors,
resume after crash).

**How to apply:** When running batch ingestion against the cluster
embedding endpoint, expect pod restarts. Use the watchdog port-forward
script at `/tmp/pf-watchdog.sh` (created during sessions) alongside
ingestion. If the ingestion fails after exhausting 10 retries, restart
it — no data is written to the vectors DB until all chunks are embedded,
so a fresh run is safe.
