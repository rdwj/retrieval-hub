# Next Session — model-registry-and-health

## Next: Registry-aware ingestion (Phase 4)

Ingestion scripts resolve embedding endpoints through the registry
instead of hardcoding URLs. `ChunkEmbedder` calls `resolve_model()`
when no explicit endpoint is passed.

1. **Alembic migration for `model_endpoint` table**
   Fields: `id` (varchar PK, same convention as other catalog tables),
   `model_name` (varchar, unique — one endpoint per model name),
   `endpoint_url` (varchar, the base URL for the `/v1/embeddings` API),
   `status` (varchar: healthy/unhealthy/unknown), `last_probed`
   (timestamptz, nullable — null until first probe), `registered_at`
   (timestamptz), `updated_at` (timestamptz). Add the migration to the
   existing Alembic chain in `src/retrieval_hub/db/migrations/`.

2. **SQLAlchemy model**
   Add `ModelEndpoint` to `src/retrieval_hub/models/`. Follow the
   existing pattern (see `Source`, `PhysicalIndex`, `RecipeVersion`).

3. **Internal API module**
   New module `src/retrieval_hub/model_registry.py` (or similar) with:
   - `resolve_model(session, model_name) → endpoint_url` — raises
     `ModelNotFoundError` if no row, `ModelUnavailableError` if status
     is `unhealthy`.
   - `register_model(session, model_name, endpoint_url)` — upsert.
   - `update_model_status(session, model_name, status)` — for the
     health probe (Phase 5) to call later.

4. **Tests**
   Unit tests for all three API functions. Test the error cases
   (not found, unhealthy). Use the existing test fixtures/patterns.

5. **Register Nomic v1.5**
   Add a seed script or CLI command that registers
   `nomic-ai/nomic-embed-text-v1.5` with its current vLLM endpoint
   (or a placeholder URL if no vLLM instance is running yet). This
   makes Phase 2 (deploy vLLM) a matter of updating the URL, not
   creating the record.

**Sequencing.** Migration first, then model, then API, then tests.
The seed registration is last.

**Session start protocol:**
- Premise checks (~5 min):
  - Catalog DB up (`pg_isready -h 127.0.0.1 -p 5434`)
  - `make migrate` runs clean (existing migrations apply)
  - Review existing Alembic migration chain to find the head revision
- Rules with history:
  - Use `127.0.0.1` not `localhost` for all Postgres connections
  - Follow existing model/migration patterns in `src/retrieval_hub/`
- Stop-and-ask before: running `alembic downgrade` or modifying
  existing migration files

## Remaining epic phases

Decouple embedding model hosting from the MCP server pod and introduce a
platform-level model registry for endpoint resolution, health probing,
and ops observability. Data sources name the model they need; the
platform resolves where it runs. All embedding is always-remote — no
models loaded in the MCP pod. Model pods scale independently of the MCP
server.

### Phase 1: Model registry data model + API

New `model_endpoint` table in the catalog DB mapping model names to
serving endpoints. Internal API for resolution, registration, and status
updates.

**Work:**
1. Alembic migration adding `model_endpoint` table (model_name,
   endpoint_url, status, last_probed, registered_at, updated_at).
2. Internal API: `resolve_model(name) → endpoint_url` (raises if not
   found or unhealthy), `register_model(name, url)`,
   `update_model_status(name, status)`.
3. Register Nomic v1.5 pointing at an initial vLLM endpoint.

**Definition of done:** `resolve_model("nomic-ai/nomic-embed-text-v1.5")`
returns the correct endpoint URL from the catalog DB. Alembic migration
applies cleanly.

**Dependencies:** None — this is the foundation.

**Parallel-ok:** Yes — independent of all other epics.

### Phase 2: Deploy embedding model as a standalone service — SKIPPED

**Status:** Skipped (2026-08-22). The original plan called for deploying
Nomic v1.5 as a new vLLM pod on agent-security-dev-3. Cluster inventory
showed Snowflake Arctic and PubMedBERT are already deployed and serving
the datasets that need them. No dataset currently requires a remote Nomic
endpoint — VA CPG and Tale of Two Cities use Nomic via local
sentence-transformers during ingestion only. Deploying Nomic would consume
the one available GPU slot with no consumer.

**Revisit when:** a dataset needs Nomic embeddings at query time (not just
ingestion), or we move VA CPG ingestion to always-remote embedding.

### Phase 3: Registry-aware retrieve + refine

The MCP server's retrieve and refine tools resolve embedding endpoints
through the registry at query time instead of reading from the recipe.
The local sentence-transformers load path is removed from the MCP
server's query path.

**Work:**
1. Change `DocumentAdapter._embedding_endpoint()` to call
   `resolve_model()` with the model name from the recipe.
2. Remove sentence-transformers from MCP server dependencies
   (`requirements-deploy.txt`).
3. Drop MCP pod memory limit from 4Gi to ~512Mi-1Gi.
4. Measure retrieve latency with remote embedding vs. old local path.

**Definition of done:** `retrieve` and `refine` calls succeed against
the registry-resolved endpoint. MCP pod runs without sentence-transformers
installed. Pod memory stays under 1Gi. Latency delta measured and
documented.

**Dependencies:** Phase 1 (registry exists). Phase 2 skipped — the two
models (Snowflake Arctic, PubMedBERT) are already deployed and seeded
in the registry.

**Parallel-ok:** Yes — parallel with Phase 4 (different code paths).

### Phase 4: Registry-aware ingestion

Ingestion scripts resolve embedding endpoints through the registry
instead of hardcoding URLs.

**Work:**
1. `ChunkEmbedder` calls `resolve_model()` when no explicit endpoint
   is passed.
2. Remove hardcoded endpoint URLs from ingestion scripts. Scripts name
   the model; the registry resolves.
3. Recipe content records the model name (already does) but not the
   endpoint URL.
4. Verify: `ingest_va_cpg.py` runs with model resolved from registry.

**Definition of done:** `ingest_va_cpg.py` runs successfully with no
endpoint URL in the script, model resolved from registry. Same for
aircraft and PubMed ingestion scripts.

**Dependencies:** Phase 1 + Phase 2.

**Parallel-ok:** Yes — parallel with Phase 3 (query vs. ingestion are
independent code paths).

### Phase 5: Health probing + error propagation

Active background probe that periodically checks registered model
endpoints, updates status in the registry, and emits structured events
on failure.

**Work:**
1. Background probe (cron job or lightweight loop in a sidecar) that
   hits each registered model's `/v1/models` or `/health` endpoint on
   a configurable interval.
2. Probe updates `model_endpoint.status` and `last_probed` in the
   registry.
3. `resolve_model()` raises a specific `ModelUnavailableError` when the
   model is marked unhealthy. The retrieve tool catches this and returns
   a structured error to the agent:
   `{"error": "embedding_model_unavailable", "model": "...", "source": "..."}`.
4. Probe failures emit a structured JSON log event (parseable by ops
   tooling / alerting).

**Definition of done:** Killing the vLLM pod causes the probe to mark
the model unhealthy within one probe interval. A subsequent retrieve
call returns the structured error. The log event appears in pod logs
with the model name and failure reason.

**Dependencies:** Phases 1-3 (registry exists, model deployed, retrieve
uses registry).

**Parallel-ok:** No — needs the full stack in place to test.

### Phase 6: Health on describe_source

`describe_source` surfaces a health field reflecting the status of each
source's embedding model dependency.

**Work:**
1. Add a `health` field to the `describe_source` response:
   `{"status": "healthy|degraded|unavailable", "embedding_model": "...", "last_checked": "..."}`.
2. Read from the registry's `model_endpoint` table — a join from
   source → recipe → model name → model_endpoint status. No new probe.
3. Update MCP server schema and tests.

**Definition of done:** `describe_source` for VA CPG shows health
status. Killing the model pod changes the health field after the next
probe cycle. Agent developers see health in `describe_source` output.

**Dependencies:** Phase 5 (needs probing in place to have meaningful
status).

**Parallel-ok:** No — sequential after Phase 5.

---

## What this covers (and what it doesn't)

**In scope:**
- Model registry data model and internal API (catalog DB)
- vLLM deployment for Nomic v1.5 as a standalone service
- Always-remote embedding for both retrieve/refine and ingestion
- Active health probing of model endpoints
- Structured error propagation to agents
- Structured log events for ops alerting
- Health status on describe_source

**Out of scope (separate concerns):**
- Ops dashboard / alerting UI (consumes the events this epic emits)
- Model fine-tuning or training pipelines
- Multi-model routing / fallback (e.g., "if model A is down, try
  model B") — future work after the registry proves out
- Reranking model hosting (same pattern, different epic)
- Local dev convenience (e.g., an embedded model for offline dev) —
  could be a follow-up if always-remote makes local dev painful

**Cross-epic dependencies:**
- eval-convergence: the embedding model comparison infrastructure
  assumes local model loading. Phase 4 here would change the ingestion
  path those scripts use.
- refine-tool: Phase 5 A/B eval depends on retrieve working. If this
  epic's Phase 3 is in flight, coordinate timing.
- data-products: ingestion scripts for PubMed and aircraft would be
  updated in Phase 4 here.

## What landed this session (2026-08-22)

Phase 1 complete — model registry data model + API:
- `model_endpoint` table (Alembic migration b4378152f6b0)
- `ModelEndpoint` ORM model, `ModelEndpointStatus` enum
- Internal API: `resolve_model()`, `register_model()`, `update_model_status()`
- Seed script registering Snowflake Arctic and PubMedBERT
- 11 tests for model + API

Phase 2 skipped — Nomic v1.5 deployment deferred (no remote consumer).

Phase 3 complete — registry-aware retrieve + refine:
- `_resolve_embedding_endpoint()` in retrieval API resolves model name
  through registry, falls back to recipe endpoint if not registered
- `DocumentAdapter` accepts pre-resolved endpoint from `_build_adapter()`
- Unhealthy models raise `ModelUnavailableError` through to caller
- 6 tests covering registry resolution, fallback, and error paths

Cluster inventory and deployment infrastructure:
- Inventoried both clusters (gpt-oss-120b and agent-security-dev-3)
- TEI PubMedBERT (CPU) on gpt-oss-120b, vLLM Snowflake Arctic (GPU) on
  agent-security-dev-3. No Nomic endpoint deployed (used locally only).
- Created `scripts/deploy-embedding.sh` with `--context` / `--namespace`
  flags for reproducible deployment to new clusters
- Added `deploy-embedding-tei` and `deploy-embedding-snowflake` Makefile
  targets
- Removed four superseded individual manifest files; consolidated
  manifests (`tei.yaml`, `vllm-snowflake.yaml`) are the source of truth
- Added deployment README with model details, API differences,
  verification steps, and troubleshooting
- Decision: hold off on Nomic v1.5 remote deployment (no urgent need;
  VA CPG and Tale of Two Cities use local sentence-transformers)

## What landed (2026-08-21)

Epic bootstrapped. Design decisions made during eval-convergence session:
- Always-remote embedding (no models in MCP pod)
- Model registry in catalog DB, `model_name` unique (one endpoint per model)
- Active health probing, not passive
- API + events for ops, not a dashboard (dashboard is a separate concern)
- Data card names the model (static); tool resolves the endpoint (runtime)

See `design_model_registry_and_health.md` in project memory for the full
design rationale.

## Watch out for

- **Latency.** Remote embedding adds a network hop. Measure in Phase 3
  before committing. If latency is unacceptable, consider co-locating
  the vLLM pod in the same namespace or using a sidecar pattern.
- **Local dev story.** Always-remote means local dev needs a running
  embedding endpoint. Options: a local vLLM instance, Ollama with
  nomic-embed-text, or a lightweight mock for tests. Decide in Phase 3.
- **vLLM version pinning.** Per CLAUDE.md lesson, vLLM `latest` doesn't
  support `--task embed`. Pin to v0.8.5 or a known-good version.
- **GPU scheduling.** The vLLM embedding pod needs a GPU. Cluster GPU
  capacity may constrain when this can deploy.

## If blocked

- If GPU capacity is unavailable for the vLLM pod, Phase 2 stalls.
  Fallback: use a CPU-only embedding service (slower but unblocked).
- If latency is unacceptable in Phase 3, revisit the always-remote
  decision — could keep local loading as a fallback with the registry
  as the preferred path.
