# Session Summary — 2026-08-24 · eval-convergence · EvalHub setup + production readiness

**Plan:** NEXT_SESSION-eval-convergence.md (Phase 2)   **Commits:** none yet (all staged)
**Deployed:** MCP, BFF, EvalHub, Nomic TEI, model probe CronJob on gpt-oss-120b   **Model:** Claude Opus 4.6

## Plan vs. actual

Planned: package eval pipeline as EvalHub cluster Job, run proof-of-concept sweep. Shipped: EvalHub infra + production readiness overhaul. Scope expanded to deploy Nomic v1.5 as a hosted TEI service, migrate MCP/BFF off local embedding, add health endpoints, move DB credentials to Secrets, deploy model health probe CronJob, and create a platform deploy orchestrator.

## Shipped

- `retrieval-hub-evalhub/` — new component: Containerfile, runner, deploy/submit/sweep scripts, refine-strategies sweep config
- `deploy/openshift/retrieval-hub/embedding/tei-nomic.yaml` — Nomic v1.5 TEI service (cpu-1.8.1)
- `scripts/seed_model_endpoints.py` — added Nomic v1.5 endpoint registration
- `src/retrieval_hub/models/enums.py` — added `EVALHUB` to `ExecutionBackend`
- `scripts/eval_answer_quality.py` — Ragas scoring resolves PubMedBERT from model registry (remote when available); `--source-slug` CLI arg for multi-source eval; `db_url` threaded to `_stage_score`
- `retrieval-hub-mcp/` — `/health` endpoint (DB + registry check), stripped local embedding deps (4Gi to 1Gi), added prompts + probe script to container, DB credentials via Secret
- `retrieval-hub-bff/` — stripped local embedding deps (2Gi to 1Gi), DB credentials via Secret, httpGet probes
- `deploy/openshift/retrieval-hub/secret.yaml` — added full connection string URL keys
- `deploy/openshift/retrieval-hub/probe-cronjob.yaml` — model health probe every 5 min
- `scripts/deploy-platform.sh` — platform deploy orchestrator (infra, migrations, seed, builds, verify)

## Verification & confidence

- Smoke test (evalhub-smoke-7): full 3-stage eval completed on cluster, results auto-registered in eval register (ctx_prec=0.747, ans_rel=0.664, faith=0.793 raw condition)
- MCP `/health` returns `{"status":"ok","checks":{"database":"ok","model_registry":"3 endpoint(s)"}}`
- Probe CronJob ran, correctly identified PubMedBERT and Nomic as healthy, Snowflake as unhealthy (not deployed)
- model_endpoint.status updated to healthy/unhealthy with timestamps
- Retrieve via MCP server works at 1Gi using remote Nomic TEI
- 338 tests pass, lint clean (except pre-existing B008), gitleaks clean
- Confidence: **medium-high** — infrastructure proven live on the cluster with real data; the refine-strategies sweep is running but hasn't completed yet; the Ragas remote-embedding change (PubMedBERT via registry) hasn't been tested in a cluster eval run yet (smoke-8 uses the pre-change container)

## Judgment calls & deviations

- Deployed Nomic v1.5 as a TEI service rather than loading locally in containers. User directed this after observing repeated OOMKills from per-query model loading. This is the right long-term architecture: embedding models are shared cluster resources.
- Used `cpu-latest` initially for TEI Nomic (cpu-1.6 and cpu-2.1.0 couldn't parse Nomic's config.json due to duplicate fields). Pinned to `cpu-1.8.1` after confirming it works.
- Reduced MCP server memory from 4Gi to 1Gi and BFF from 2Gi to 1Gi. These are aggressive cuts enabled by removing local model loading. Monitor for OOM if other memory-intensive operations exist.
- Submitted all 4 refine-strategy sweep jobs in parallel (no PVC conflict after removing model cache volume) rather than sequential. The cluster LLM handles the concurrent load.

## Backlog delta

No issues filed or closed this session. #27 (production ingestion runners) is partly addressed by the deploy-platform.sh orchestrator pattern. #31 (MCP e2e testing) is partly addressed by the /health endpoint.

## Drift & forward-collisions

- Backward — #27 (production ingestion runners): deploy-platform.sh establishes the orchestration pattern that runners would use. The CronJob manifest is the first batch workload on this cluster. Still open: runners need their own containers and Tekton pipelines.
- Backward — #31 (MCP e2e testing): /health endpoint verifies DB + registry connectivity but doesn't test a full retrieve round-trip. Still needs a dedicated e2e test path.
- Forward — refine-tool epic: the refine-strategies sweep (4 jobs running) will produce the A/B data that epic needs. Results will be in the eval register when the sweep completes.

## For the reviewer

- Sanity-check: the MCP server at 1Gi is a significant reduction from 4Gi. If there are code paths that allocate large objects (e.g., processing large documents, caching query results), this could OOM under load. Worth watching pod restarts after a period of real usage.
- Thin verification: the Ragas remote-embedding change (`try_resolve_endpoint` for PubMedBERT scoring) is tested by code inspection + lint, not by a live eval run. The next EvalHub container rebuild will include it, but the current running sweep uses the old container.
- Wants guidance: the Snowflake Arctic endpoint is registered but the service isn't deployed. Should it be removed from seed_model_endpoints.py, or should we deploy the vLLM Snowflake service?

## Risks / watch-fors

- The 4 refine-strategy sweep jobs are running in parallel against the cluster LLM. If gpt-oss-120b becomes overloaded, scoring latency will increase for all 4 jobs. Monitor with `oc get jobs -l evalhub-sweep=refine-strategy-sweep`.
- The TEI Nomic image tag `cpu-1.8.1` works around a config parsing bug (duplicate fields in Nomic's config.json). If Nomic publishes a new model revision that changes the config structure, TEI might need updating.
- gpt-oss-120b sandbox cluster may be reprovisioned. Embedding services, model registry entries, and eval jobs would all need redeployment. deploy-platform.sh handles this.
