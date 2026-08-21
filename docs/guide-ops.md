# Ops Guide to Dataset Onboarding

This guide covers what the ops team does when a data owner wants to add a
new dataset to RetrievalHub. The data owner handles domain decisions
(chunking strategy, governance rules, embedding model selection). Your job
is to host the infrastructure, run the ingestion, and keep it running.

For a worked example of the full process, see
[onboarding-journey-va-cpg.md](onboarding-journey-va-cpg.md).

## What you are hosting

RetrievalHub has four components:

**Catalog database** (PostgreSQL). Stores source metadata, recipe versions,
physical index records, evaluation results, and governance rules. One
instance serves all sources.

**Vectors database** (PostgreSQL + pgvector). Stores chunk text, embeddings,
and document metadata. Each source gets its own table
(`idx_{source_slug}_v{version}`). One instance serves all sources.

**MCP server** (FastMCP on OpenShift). A single deployment that serves all
sources. It queries the catalog to discover sources and the vectors database
to run retrieval. Agents connect via streamable-http. No per-source
deployment is needed: new sources appear automatically after ingestion.

**Embedding models.** Each source specifies an embedding model. The MCP
server loads the model at query time to embed the user's query for vector
search. Models can be served locally via sentence-transformers (loaded into
the MCP server process) or remotely via vLLM. Different sources may use
different models.

## What the data owner hands you

After the data owner completes their steps (see
[guide-data-owner.md](guide-data-owner.md)), you receive:

1. **An ingestion script.** A Python script in `scripts/` that runs the
   full pipeline: fetch, parse, normalize, chunk, embed, write to pgvector,
   and register in the catalog. The script encodes all pipeline decisions
   (chunking parameters, embedding model, table name, source metadata).

2. **Embedding model requirements.** The model name (e.g.,
   `nomic-ai/nomic-embed-text-v1.5`), its on-disk size, and estimated
   memory footprint. Rule of thumb: in-memory footprint is roughly 3x the
   on-disk weight, plus ~500MB for the Python process.

3. **Semantic layer scripts** (optional). One or two scripts that populate
   vocabulary mappings and entity definitions on the source record. These
   run against the catalog database.

4. **Refresh schedule.** How often the corpus needs re-ingestion: on
   demand, monthly, quarterly. Some sources are static; others update
   regularly.

## Per-source onboarding checklist

### 1. Verify the embedding model

Before running ingestion, confirm the embedding model loads and its memory
footprint fits within your resource limits.

```bash
python -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)
print(f'Dimension: {model.get_sentence_embedding_dimension()}')
emb = model.encode(['test query'])
print(f'Shape: {emb.shape}')
print('OK')
"
```

If the model is too large for the MCP server pod, deploy it on a separate
vLLM instance and configure the MCP server to call it remotely.

**Memory sizing reference** (from production experience):

| Model | On-disk | In-memory | MCP pod limit |
|---|---|---|---|
| PubMedBERT (768-dim) | ~400MB | ~1.2GB | 2Gi sufficient |
| Nomic v1.5 (768-dim) | ~550MB | ~1.5GB | 4Gi recommended |

If a new source requires a model that doesn't fit alongside existing models
in the pod's memory, you have two options: increase the pod memory limit, or
move the model to a dedicated vLLM deployment and configure the ingestion to
use the remote embedding endpoint.

### 2. Run the ingestion script

The data owner's ingestion script handles everything. Run it with the
appropriate database URLs:

```bash
python scripts/ingest_{source_slug}.py \
  --db-url "$CATALOG_DB_URL" \
  --vectors-db-url "$VECTORS_DB_URL"
```

The script will report a summary including document count, chunk count,
embedding model, pgvector table name, and the source UUID.

**Verify after ingestion:**

```bash
# Source appears in the catalog
python -c "
from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.models import Source
sf = make_session_factory(create_db_engine('$CATALOG_DB_URL'))
with sf() as s:
    src = s.query(Source).filter(Source.slug == '{source_slug}').one()
    print(f'Source: {src.name}')
    print(f'Active index: {src.active_physical_index_id}')
    print(f'Status: {src.status}')
"
```

### 3. Run the semantic layer scripts (if provided)

```bash
python scripts/seed_{source_slug}_rewriter_metadata.py --db-url "$CATALOG_DB_URL"
python scripts/seed_{source_slug}_semantic_context.py --db-url "$CATALOG_DB_URL"
```

These are idempotent. Re-running them updates the existing metadata rather
than creating duplicates.

### 4. Verify via the MCP server

If the MCP server is already deployed, the new source should appear
immediately. Test with `mcp-test-mcp` or curl:

```bash
# List sources (should include the new one)
# Via mcp-test-mcp: connect, then list_tools, then call_tool list_sources

# Test retrieval
# call_tool retrieve with source={slug} and a sample query
```

If the MCP server is not yet deployed, see the infrastructure section below.

### 5. Resource sizing

**pgvector table size.** Estimate based on chunk count and embedding
dimension:

```
row_size ≈ (dimension × 4 bytes) + avg_text_bytes + metadata_overhead
table_size ≈ row_size × chunk_count
```

For 6,500 chunks at 768 dimensions with ~500 bytes of text per chunk: about
25MB. For 100,000 chunks: about 400MB. pgvector indexes add roughly 2-3x
the base table size.

**MCP server memory.** The server loads embedding models lazily on first
query. If all sources use the same model, memory is shared. If sources use
different models, each model adds to the memory footprint. Size the pod
limit to accommodate all models that might be loaded concurrently.

## Infrastructure

### Postgres (catalog + vectors)

Two logical databases, which can run on one or two PostgreSQL instances.
The vectors database requires the pgvector extension (`CREATE EXTENSION
vector`). Both use standard PostgreSQL with no special configuration beyond
the extension.

**Migrations.** The catalog schema is managed by Alembic. Run `make
migrate` when deploying a new version of the platform.

### MCP server deployment

The MCP server runs on OpenShift. Key manifest details
(`retrieval-hub-mcp/openshift.yaml`):

- **Route path:** `/mcp` (no trailing slash; see troubleshooting)
- **TLS:** edge termination with insecure redirect
- **Env vars:**
  - `RETRIEVAL_HUB_DB_URL` (catalog Postgres connection string)
  - `RETRIEVAL_HUB_VECTORS_DB_URL` (vectors Postgres connection string)
  - `SENTENCE_TRANSFORMERS_HOME` and `HF_HOME` (model cache directory)
  - `RETRIEVAL_HUB_REWRITER_LLM_URL` and `RETRIEVAL_HUB_REWRITER_LLM_MODEL`
    (if any source uses the query rewriter)
- **Volume:** `retrieval-hub-model-cache` PVC mounted at the model cache path
- **Probes:** TCP 8080, liveness at 30s, readiness at 15s

Deploy with:

```bash
./retrieval-hub-mcp/deploy.sh [project-name] [--context=cluster-context]
```

The deploy script creates a filtered build context, runs an OpenShift
binary build, and restarts the deployment.

### Embedding model deployment (vLLM, when needed)

For models too large to load in the MCP server process, or when GPU
acceleration is needed, deploy on vLLM:

- Use `vllm/vllm-openai:v0.8.5` (not `latest`; see troubleshooting)
- Add `--task embed` to the serve args
- Set `enableServiceLinks: false` in the pod spec
- Add GPU toleration for `nvidia.com/gpu` NoSchedule taint
- Set `HF_HOME` to a PVC mount (not `/root/`; OpenShift runs non-root)
- Include `truncate_prompt_tokens: 512` in API requests to handle chunks
  that exceed the model's position limit after tokenization

## Troubleshooting

These are failure modes we have encountered in production. They are
documented in `CLAUDE.md` under "Lessons Learned."

**OOMKilled on first query.** The MCP server pod crashes after the first
retrieval call loads the embedding model. The model's in-memory footprint
exceeds the pod's memory limit. Fix: increase the memory limit. Estimate
3x the model's on-disk weight plus 500MB for the Python process.

**503 on MCP connection.** FastMCP binds to `/mcp` (no trailing slash) and
307-redirects `/mcp/` to `/mcp`. If the OpenShift route has `path: /mcp/`,
HAProxy only matches requests with the trailing slash, and the redirect
target returns 503. Fix: ensure the route path has no trailing slash.

**ImportError in container.** The local venv pulls transitive dependencies
automatically, but the container's `requirements-deploy.txt` is a flat
list. A model change may introduce a new transitive dependency (e.g.,
`einops` for Nomic v1.5) that isn't listed. Fix: after changing the
embedding model, run `pip show <model-package>`, check its dependency tree,
and update `requirements-deploy.txt`.

**vLLM rejects embedding requests (400 error).** BERT-based models use
WordPiece tokenization, which produces 1.3-1.5x more tokens than the
cl100k_base tokenizer used for chunking. A chunk of 512 cl100k_base tokens
can exceed the model's 512 max_position_embeddings. Fix: include
`truncate_prompt_tokens: 512` in the `/v1/embeddings` request payload.

**vLLM `--task embed` not recognized.** The `latest` vLLM tag may not
support embedding mode. Pin to `v0.8.5` or a version known to support
`--task embed`.

**Nomic v1.5 OOM during ingestion on Apple Silicon.** The default batch
size of 32 causes a 42GB attention buffer allocation on MPS. Fix: use
`--batch-size 8` for the ingestion script. This only affects local
ingestion, not production serving.

## Content refresh

When the data owner provides updated source documents:

1. Re-run the ingestion script. It creates a new recipe version and
   physical index, and updates `active_physical_index_id` to point at the
   new index.
2. Old indexes remain in the database for lineage but are no longer queried.
3. No MCP server restart is needed. The server reads the active index on
   each request.
4. If the eval pipeline is set up, re-run it to verify retrieval quality
   has not regressed.
