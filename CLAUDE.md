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
