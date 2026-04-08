# Integration: MLflow

[MLflow](https://mlflow.org/) is the open-source experiment tracking, model registry, and (as of 3.x) GenAI lifecycle platform. On the target deployment cluster, MLflow is **available** as a separately-installed capability. As of RHOAI 3.3 the MLflow operator's `managementState` is `Removed` in the default DataScienceCluster, so MLflow is **no longer a managed RHOAI component**; clusters that want it install it themselves (typically via the `strangiato/mlflow-server` Helm chart, which deploys MLflow 3.4 as of chart version 0.8.0). Red Hat publishes a Beta container image (`rhoai/odh-mlflow-rhel9`, currently `v3.4.0-ea.1`), but it is not part of a supported RHOAI install.

**Minimum version target: MLflow 3.0. Recommended floor: MLflow 3.4.** The 3.x line is where the prompt registry, dataset tracking, and GenAI tracing are all mature and stable. The retrieval-hub Python client is pinned to `mlflow>=3.0,<4.0`. Clusters running MLflow 2.x are treated as the standalone-fallback case for the prompt registry path.

This document describes how retrieval-hub integrates with MLflow when present: which retrieval-hub objects map to which MLflow objects, the ownership boundary, the buffer-and-reconcile pattern when MLflow is transiently unavailable, the design for clusters where MLflow is *not* SSO'd to the rest of the platform identity story, the RHOAI-specific deployment caveats, and the standalone fallback for clusters without MLflow at all.

## What MLflow provides that we care about

MLflow's GenAI features as of 3.10 (February 2026; 3.10.1 on March 5, 2026) cover almost everything retrieval-hub round 1 was on the hook to build for "experiment-style" objects:

- **Experiment tracking** — runs with parameters, metrics, tags, artifacts. The unit of an "eval run" maps directly.
- **Run comparison UI** — diff parameters, plot metrics across runs, group by tag. We do not need to build run comparison.
- **Prompt registry** — versioned prompts with tagging, comments, and rollback. Designed for exactly the kind of prompt-engineering workflow our shared rewriter template needs.
- **Dataset tracking** — datasets as first-class objects linked to runs, with versioning.
- **OpenTelemetry-compatible tracing** — multi-step trace capture for agent and RAG workflows.
- **Model registry** — versioned ML models with stages and tags. Less directly relevant to retrieval-hub (we don't manage embedding model lifecycles; vLLM does), but worth noting.
- **REST API and Python client** — MLflow tracking server is reachable over HTTP; we consume it as a service, never as an in-process import.

What MLflow does **not** model:

- **Curated retrieval sources.** MLflow has experiments, runs, datasets, prompts, and models. It does not have "a curated, owned, evaluated retrieval surface with a recipe and an active physical index pointer." That richness is the catalog's, not MLflow's.
- **Source-level access policy.** MLflow has workspace-style permissions, not "this agent identity group can query this source."
- **Hot-path read APIs.** MLflow is for offline / batch / human-driven workflows. The MCP server does not call MLflow on every retrieval; the catalog is the runtime hot path.
- **Catalog state.** Recipes, source families, retrieval pattern declarations, agent_write_policy — all of this is operational runtime state and lives in retrieval-hub Postgres.

The mental model: **catalog = retrieval-hub Postgres (runtime, hot path, security boundary), experiments = MLflow (history of record, comparison, governance)**. Every field on a source has a clear authoritative side.

## What retrieval-hub consumes from MLflow

Four object-level mappings, in roughly increasing scope.

### 1. Eval runs → MLflow runs

The biggest mapping. Per the platform-overlap analysis in [`README.md`](README.md), eval **history of record** is delegated to MLflow. Each eval run becomes an MLflow run, structured as:

```yaml
mlflow_experiment: rh.eval.<source-slug>     # one experiment per source
mlflow_run:
  run_name: "eval-<suite-slug>-v<n>-<llm>-rewrite_<on|off>-<timestamp>"
  parameters:
    source_id: src_01HXY...
    source_slug: va-clinical-guidelines
    physical_index_id: pidx_01HXZ...
    recipe_version: 3
    eval_suite_id: eval_01HYZ...
    eval_suite_version: 2
    llm: granite-3.3-8b-instruct
    rewrite_enabled: true
    metric_set: ragas_default
    execution_backend: llamastack    # or "retrieval-hub-native"
  metrics:
    recall_at_1: 0.62
    recall_at_3: 0.71
    recall_at_5: 0.74
    mrr: 0.68
    ndcg_at_5: 0.79
    latency_p50_ms: 820
    latency_p95_ms: 1840
    cost_estimate_tokens_per_query: 1240
    # When LLM-in-loop is enabled (Ragas):
    faithfulness: 0.88
    answer_relevancy: 0.83
    context_precision: 0.79
  tags:
    rh.source_id: src_01HXY...
    rh.recipe_version: "3"
    rh.eval_suite_version: "2"
    rh.run_kind: "eval"            # eval | metadata_test | recipe_tuning
    rh.triggered_by: <identity>    # see "no-SSO design" below
    rh.triggered_by_kind: user     # user | service | scheduler
  inputs:
    datasets:
      - name: "rh.eval.<suite-slug>.v2"
        digest: <test-cases hash>
```

The catalog's source record stores **headline projections** — the values an owner needs at browse time — plus **lineage pointers** into MLflow:

```yaml
evals:
  - llm: granite-3.3-8b-instruct
    suite: va-cpg-eval
    suite_version: 3
    physical_index: pidx_01HXZ...
    rewrite_enabled: true
    run_at: 2026-04-06T03:14:00Z
    scores:
      recall_at_5: 0.74
      mrr: 0.68
      rewrite_lift_at_5: 0.27
    mlflow:
      experiment_id: exp_...
      run_id: run_...
      tracking_uri: https://mlflow.example.com
```

The card surface reads from `scores` (fast, in-Postgres). Anyone who wants the full historical record clicks through `mlflow.run_id` to MLflow's UI. We do not reimplement the run-comparison UI, the metric plots, or the diff view; MLflow does all of that.

### 2. Test cases → MLflow datasets

Each version of an eval suite's test cases is an MLflow dataset. The catalog's eval suite object carries the dataset reference:

```yaml
test_cases:
  count: 412
  storage_uri: mlflow-dataset://exp_.../rh.eval.rh-docs-eval.v2   # logical reference
  schema: case_schema_v1
  mlflow:
    dataset_name: rh.eval.rh-docs-eval
    dataset_digest: sha256:abc123...
    version: 2
```

When the eval suite version is bumped, a new MLflow dataset version is created. Eval runs reference the exact dataset version they were run against. Reproducing a historical eval is a matter of fetching the dataset version from MLflow.

### 3. Shared rewriter template → MLflow prompt registry

The shared core rewriter template (from [`../query-rewriter.md`](../query-rewriter.md)) lives as an MLflow prompt registry entry when MLflow is present:

```yaml
mlflow_prompt:
  name: rh.rewriter.shared-core
  version: 7
  template: |
    You are a query reformulator for the {source_family} retrieval source
    "{source_name}". You will receive a user's question in natural language
    and a structured metadata payload describing the corpus's vocabulary,
    domain, and conventions...
    [...]
  tags:
    rh.template_kind: shared_core_rewriter
    rh.compatible_llm_families: granite,llama,mistral,gpt
```

retrieval-hub keeps the **active version pointer** in its own configuration so the hot-path rewriter doesn't have to call MLflow on every rewrite call:

```yaml
rewriter:
  shared_template_pointer:
    mlflow_prompt_name: rh.rewriter.shared-core
    active_version: 7
    cached_template_at_version: <full template text, refreshed periodically>
```

The rewriter's I/O contract surfaces the active prompt version on every result for lineage:

```yaml
shared_template_version: 7    # corresponds to the MLflow prompt version
metadata_version: 4           # the per-source rewriter_metadata version
```

Per-source override prompts (the rare case from [`../query-rewriter.md`](../query-rewriter.md) where a source needs a non-default template) work the same way: their template lives in MLflow prompt registry, the catalog's `rewriter_metadata.prompt_override_id` references the MLflow prompt name, and the hot path caches the active version.

The **per-source rewriter metadata itself** (vocabulary mappings, sample queries, domain notes, schema hints) stays in retrieval-hub Postgres. It's strongly typed, has a typed editor in the admin UI, and is on the hot path. MLflow's prompt registry is for free-text prompts; rewriter metadata is structured.

### 4. Recipe tuning runs → MLflow runs (when AutoRAG is wired up)

If we wire up the AutoRAG integration described in [`autorag.md`](autorag.md), each tuning run also becomes an MLflow run, in a separate experiment:

```yaml
mlflow_experiment: rh.tuning.<source-slug>
mlflow_run:
  run_name: "tuning-<source-slug>-<timestamp>"
  parameters:
    source_id: src_01HXY...
    search_space: <serialized search space yaml>
    autorag_version: <version>
  metrics:
    best_recall_at_5: 0.78
    best_mrr: 0.72
    combinations_tested: 180
    runtime_seconds: 4320
  artifacts:
    scoreboard.csv: <AutoRAG summary.csv>
    recommended_recipe.yaml: <translated retrieval-hub recipe>
  tags:
    rh.run_kind: recipe_tuning
    rh.recommended_recipe_version: 4    # if accepted into the catalog
```

This gives source owners the same comparison story for tuning runs that they get for eval runs — diff parameters across attempts, plot metric trajectories, see which combinations worked best — without retrieval-hub having to build a tuning UI.

## Ownership boundary

The cleanest way to keep the catalog and MLflow from getting muddled is to write down, field by field, who is authoritative for what. The pattern is the same as the table in [`openshift-ai-assets.md`](openshift-ai-assets.md): the catalog is authoritative for runtime / operational / security state, MLflow is authoritative for experiment / history / comparison state, and the catalog stores small projections of MLflow state for hot-path display.

| Concern | Authoritative | Notes |
|---|---|---|
| Source identity (id, slug, name, family, status) | retrieval-hub | Hot path; security boundary |
| Recipe (version, parser, chunker, embedding model, backend) | retrieval-hub | Hot path; ingestion reads it |
| Active physical index pointer | retrieval-hub | Hot path; retrieval reads it |
| Source ownership and access policy | retrieval-hub | Security boundary |
| `agent_write_policy` and per-write audit records | retrieval-hub | Security boundary |
| Per-source rewriter metadata (vocabulary, samples, domain notes, schema) | retrieval-hub | Strongly typed; hot path; typed UI editor |
| Lineage of source state transitions | retrieval-hub | Audit; queryable from the UI |
| Eval suite definition (name, applies_to, metric set, test case version) | retrieval-hub | Catalog object |
| Eval test cases (the actual cases) | **MLflow** when present, retrieval-hub MinIO when absent | MLflow dataset versioned |
| Eval run history (per-run params, metrics, lineage) | **MLflow** when present, retrieval-hub Postgres when absent | MLflow run per execution |
| **Headline eval scores on the card** | **retrieval-hub** | Always. Projection from the authoritative source |
| Eval run comparison UI | **MLflow** when present | We don't build one |
| Shared rewriter template (the prompt text + version history) | **MLflow** when present, retrieval-hub config when absent | MLflow prompt registry |
| Active rewriter template version pointer | retrieval-hub | Hot path; cached for fast lookup |
| Per-source override prompts | **MLflow** when present, retrieval-hub config when absent | Same pattern as shared template |
| Recipe tuning run history (when AutoRAG is wired) | **MLflow** when present | One run per tuning attempt |
| Tuning recommendation acceptance (which recipe went into the catalog) | retrieval-hub | The acceptance is a catalog mutation; the audit trail is in both places |
| Metric definitions | retrieval-hub | We declare what `recall_at_5`, `rewrite_lift_at_5`, etc. mean |
| Production retrieval telemetry | OpenTelemetry / LlamaStack telemetry | Not MLflow's job; see [`llamastack.md`](llamastack.md) |

The pattern is consistent: retrieval-hub owns *what to evaluate* and *how to render the result on a card*; MLflow owns *the historical record of what happened when we evaluated it*. The hot path never calls MLflow; the runtime never blocks on MLflow.

## The no-SSO design

A real complication: **MLflow on the target cluster will not necessarily have SSO with the cluster's identity provider**. The user explicitly flagged this. The design has to handle the case where retrieval-hub authenticates as a *service-account identity* to MLflow rather than as the *actual human or agent* who triggered the eval.

The relevant MLflow auth facts to understand:

- **MLflow's built-in auth is basic-auth** (`mlflow server --app-name basic-auth`), username + password, no tokens.
- **The MLflow Python client only accepts auth via env vars** (`MLFLOW_TRACKING_USERNAME` + `MLFLOW_TRACKING_PASSWORD`) or a `~/.mlflow/credentials` file. There is no first-class "pass a token" API on `MlflowClient`.
- **The `mlflow.user` system tag is auto-set** from the runtime context. For retrieval-hub talking to MLflow, this will be the retrieval-hub service account on every run. The historical `user_id` argument was deprecated and migrated to this system tag, so there is no MLflow API for "log this run *as* a different user."
- **MLflow custom auth plugins** can replace basic-auth with OIDC/SSO. The community `mlflow-oidc-auth` plugin supports Keycloak and group-based authorization. This is an option for clusters that want SSO, but retrieval-hub does not configure it — it's a cluster-side install decision.

The pattern retrieval-hub uses, which works on every cluster regardless of SSO state:

1. **retrieval-hub holds a service-account credential for MLflow.** Configured at deploy time as a Kubernetes Secret containing `MLFLOW_TRACKING_USERNAME` and `MLFLOW_TRACKING_PASSWORD`. The service account has write permission to the MLflow experiments and prompt registry entries that retrieval-hub manages.
2. **All MLflow API calls from retrieval-hub use the service-account credential.** From MLflow's audit perspective, every run is "owned by" the retrieval-hub service. The `mlflow.user` system tag will be the retrieval-hub service user on every run.
3. **The actual triggering identity is recorded as MLflow run tags**, not as the run's owner. Specifically:
   - `rh.triggered_by: <identity sub>` — the SPIFFE ID, user id, or service id from the retrieval-hub JWT that triggered the run
   - `rh.triggered_by_kind: user|agent|service|scheduler` — the identity kind
   - `rh.triggered_by_groups: <comma-separated>` — the identity groups, for after-the-fact access review
   - `rh.tenant_id: <tenant>` — the tenant the run belongs to
4. **The catalog's audit trail** continues to record the actual triggering identity in retrieval-hub Postgres, which is the security boundary for "who is allowed to do what." MLflow tags are for *display* and *querying*, not for authorization.
5. **MLflow prompt registry edits** follow the same pattern: the service account makes the edit, the actual identity is in tags. Authorization for "who can edit the shared rewriter template" is enforced in retrieval-hub before the MLflow call ever happens.

This design is intentionally non-fancy. Real SSO between retrieval-hub-auth and MLflow would be cleaner — the catalog identity would naturally become the MLflow run owner — but it requires customer configuration (the `mlflow-oidc-auth` plugin) we cannot count on. The service-account-with-tags pattern works on every cluster.

If a future cluster *does* have MLflow SSO'd to the same Keycloak as retrieval-hub-auth and Kagenti (via `mlflow-oidc-auth` or equivalent), we can add an optional "pass through real identity" mode that uses on-behalf-of token exchange to make MLflow runs natively owned by the triggering identity. That's a configuration option, not a redesign.

### The RHOAI dashboard auth gotcha

Flag this prominently: **the RHOAI dashboard-proxied MLflow URL does not accept Kubernetes service account authentication.** This is a documented gotcha in the ai-on-openshift MLflow guide. The workaround:

**Always configure `MLFLOW_TRACKING_URI` to point at the direct OpenShift Route for the MLflow service**, not at the RHOAI dashboard URL. The dashboard URL is fine for humans browsing MLflow through the RHOAI UI; it is not fine for retrieval-hub's service-account writes.

This is a configuration-time concern (the deploy engineer sets `MLFLOW_TRACKING_URI` correctly), not a runtime one. Retrieval-hub doesn't need to detect or work around it — we just need to document it so nobody points us at the dashboard URL and is surprised when writes fail.

## Buffer-and-reconcile when MLflow is unavailable

MLflow is a service. Services go down. retrieval-hub must not block production work because MLflow is unreachable.

The pattern, applied uniformly to every MLflow write:

1. **Try the MLflow write.** If it succeeds, done.
2. **On failure, write the would-be MLflow content to a local buffer table** in retrieval-hub Postgres (`mlflow_pending_writes`). The original retrieval-hub operation still completes — eval runs still produce a result row, prompt edits still take effect locally.
3. **A background reconciler loop** picks up `mlflow_pending_writes` rows and retries them. Successful writes are deleted; persistent failures are flagged for operator attention but do not block.
4. **The catalog's lineage pointers** include a state field (`mlflow_state: synced|pending|failed`). The UI surfaces this on the source detail page so an owner can tell at a glance whether the historical record is up to date.

Same posture as the AI Assets registration in [`openshift-ai-assets.md`](openshift-ai-assets.md): **retrieval-hub does not depend on the integration being available for core operations**. The integration enriches the experience when it works; when it doesn't, retrieval-hub continues.

Idempotency matters here. MLflow runs are created with deterministic external IDs (constructed from `{source_id, eval_suite_version, physical_index_id, llm, rewrite_enabled, run_started_at}`) so a retried `create_run` call after a transient failure does not produce duplicate runs.

## Configuration boundaries

retrieval-hub-mcp / retrieval-hub-ui / the catalog needs the following configuration to talk to MLflow when present:

- `MLFLOW_TRACKING_URI` — the MLflow server URL. **Must be the direct OpenShift Route**, not the RHOAI dashboard-proxied URL, due to the service-account auth gotcha (see above).
- `MLFLOW_TRACKING_USERNAME` + `MLFLOW_TRACKING_PASSWORD` — service account credential, mounted from a Kubernetes Secret. These are the only client-side auth mechanism MLflow's Python client supports; there is no token alternative.
- `MLFLOW_EXPERIMENT_PREFIX` — namespace prefix for retrieval-hub experiments (default `rh.`), so multiple retrieval-hub instances can share one MLflow tracking server without colliding.
- `MLFLOW_REGISTRY_URI` — usually the same as the tracking URI but separable for clusters with split tracking/registry deployments.
- `MLFLOW_S3_ENDPOINT_URL` — when MLflow's artifact store is on MinIO/S3/NooBaa, this is the artifact store endpoint. **Must be set on both the MLflow server and on retrieval-hub's pods** (eval runners and the core library writer). Credentials come from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars mounted from a separate Secret.
- `MLFLOW_DISABLED` — explicit kill switch to run retrieval-hub in standalone mode even on a cluster where MLflow exists (for testing or in incident scenarios).

Configuration is per-deployment, not per-source. Sources do not declare which MLflow they want.

### Coexistence with RHOAI

A few operational notes for clusters where MLflow and RHOAI coexist:

- **MLflow needs its own Postgres.** The strangiato chart provisions a dedicated Crunchy Postgres cluster for MLflow. Do **not** share Postgres with retrieval-hub's catalog or with anything RHOAI installs. Mixing schemas in one Postgres is operationally fragile and makes backup/restore painful.
- **Artifact storage (NooBaa/MinIO).** MLflow's default artifact store in the strangiato chart is NooBaa (ODF S3). retrieval-hub uses MinIO for ingestion checkpoints. They can share an S3-compatible store with **separate buckets**, or be fully separate. Round 1 recommendation: separate buckets in a shared NooBaa instance unless ops asks for full separation.
- **No port clashes** with RHOAI 3.x components are documented. MLflow runs on its own Service and Route.
- **Dashboard auth gotcha**: covered above. Use the direct Route, not the dashboard URL.

## Standalone fallback

When MLflow is **not** present (or `MLFLOW_DISABLED=true`), retrieval-hub falls back to the round-1 native designs:

- **Eval runs** are stored as rows in retrieval-hub Postgres, with full per-run parameters and metrics. The card surface and the audit trail still work; what's missing is the rich comparison UI MLflow provides.
- **Test cases** are stored as Parquet in MinIO (the round-1 design), referenced by an internal `eval_suite_test_cases` table in Postgres for indexing.
- **The shared rewriter template** ships as a versioned artifact in the core library — a Python file or YAML in `src/retrieval_hub/rewriter/templates/` with a version constant. Bumping the version is a code change reviewed in the normal way. Per-source override prompts (when used) are stored as catalog objects in Postgres. We lose MLflow's prompt-vs-prompt diff UI; we gain "the template lives in source control like every other piece of code."
- **Recipe tuning runs** (if AutoRAG is wired) drop their scoreboard as Parquet to MinIO and a summary row to retrieval-hub Postgres. No comparison UI; the CLI can dump the scoreboard for inspection.

The fallback is **degraded but functional**. Every core capability still works. What's missing is the experiment-comparison ergonomics MLflow provides for free.

The fallback is also the test-time and dev-time configuration: developers running retrieval-hub locally don't need to spin up an MLflow server.

## The clean exit

If we decide to retire the MLflow integration (e.g., a different experiment tracker becomes the cluster default, or MLflow stops being the right tool for our scale), the exit is:

1. Set `MLFLOW_DISABLED=true` in the deployment configuration.
2. retrieval-hub falls back to native storage on the next restart.
3. **Backfill historical data** from MLflow into retrieval-hub Postgres / MinIO before decommissioning the MLflow instance. The catalog's lineage pointers contain enough information to fetch the full record from MLflow during backfill. This is a one-time migration script.
4. Archive the MLflow data and decommission.

The fallback being a real first-class mode (not a "broken degraded state") is what makes the exit cheap. Both modes are tested.

## What's Decided

- **MLflow is the experiment / history-of-record / prompt registry / dataset tracker when present**, with native fallback when absent.
- **Minimum MLflow version is 3.0; recommended floor is 3.4** (matching the strangiato Helm chart default and the Red Hat container image). Python client is pinned `mlflow>=3.0,<4.0`.
- **MLflow is not part of RHOAI 3.x.** Operators install it themselves (typically via `strangiato/mlflow-server` Helm chart). retrieval-hub talks to it over a direct OpenShift Route.
- **Catalog vs. MLflow ownership is split** by the rule "runtime hot path and security boundary belong to the catalog; experiment history and comparison belong to MLflow."
- **Score on the card stays in retrieval-hub** as a projection. The catalog row carries the headline values; the lineage pointer goes to MLflow for the full record.
- **The shared rewriter template lives in MLflow prompt registry** when present, with the active version cached in retrieval-hub config for hot-path lookup. The MLflow prompt registry is GA in 3.x and feature-complete for our use case (versioning, tags, aliases, side-by-side diff in UI, programmatic load).
- **Per-source rewriter metadata stays in retrieval-hub Postgres**, regardless of MLflow availability. It's strongly typed, has a typed editor, and is not a "prompt" in MLflow's sense.
- **Service-account auth to MLflow with triggering identity in tags** is the production pattern. Username + password via `MLFLOW_TRACKING_USERNAME`/`MLFLOW_TRACKING_PASSWORD`, not a token — this is the only auth mechanism MLflow's Python client supports. SSO between retrieval-hub-auth and MLflow is not assumed; clusters that want it can install the community `mlflow-oidc-auth` plugin.
- **`MLFLOW_TRACKING_URI` must be the direct Route**, not the RHOAI dashboard-proxied URL, due to the dashboard's service-account auth limitation.
- **`mlflow.user` system tag is explicitly set to the retrieval-hub service identity** at run-create time. The actual triggering identity is in `rh.triggered_by` / `rh.triggered_by_kind` / `rh.triggered_by_groups` / `rh.tenant_id` tags.
- **Buffer-and-reconcile** for MLflow writes that fail. retrieval-hub never blocks on MLflow.
- **Idempotent run/dataset creation** using deterministic external IDs.
- **Standalone fallback is a first-class mode**, not a broken state. Tested, documented, and the right answer for clusters without MLflow.

## What's Open

- **Whether the per-source rewriter metadata test cases also live in MLflow as a dataset**, or stay inline in the catalog. Round 1 says inline; if rewriter metadata test suites grow large, they should move to MLflow.
- **MLflow tracking server scaling** under the load of automatic re-evals. If a recipe edit triggers eval runs across many sources, the MLflow tracking server may bottleneck. Probably not v1 concern; flag for round 2.
- **The MinIO vs. MLflow artifact store overlap.** retrieval-hub uses MinIO for ingestion checkpoints; MLflow uses MinIO (or another S3) for run artifacts. They can share a bucket or be separated; decide at deploy time.
- **The reconciler loop's retry policy.** Exponential backoff with jitter; max retries before giving up; alerting threshold. Operational tuning.
- **Whether the "real SSO" mode** (on-behalf-of token exchange to natively own MLflow runs as the triggering identity) is worth implementing for the small number of clusters where MLflow does have SSO with Keycloak. Defer until we encounter a cluster that actually has it.
- **Cleanup of old MLflow runs.** retrieval-hub history grows forever; MLflow does too. Probably "keep all of them until storage becomes a problem, then aggregate older runs," same as the round-1 catalog policy.
