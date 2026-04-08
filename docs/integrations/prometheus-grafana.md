# Integration: Prometheus + Grafana (Observability)

Observability for retrieval-hub is delegated to the cluster's **Prometheus + Grafana + OpenTelemetry** stack. retrieval-hub emits metrics and traces; the cluster's observability stack ingests, stores, aggregates, and visualizes them. The retrieval-hub admin dashboard holds a **minimal catalog-specific slice** of the full picture (source counts, recent changes, flagged sources) and then **links out to Grafana** for everything else — query volumes, latency distributions, error rates, per-identity usage, anomalies, cost.

This is a deliberate design choice. Building a native query log with aggregation pipelines, dashboards, and anomaly detection would duplicate capabilities that already exist in every real OpenShift cluster. The user's direction was explicit: "use Prometheus/Grafana for observability and just point to that. We'll reuse anything we can."

This document describes what retrieval-hub emits, how the UI links out, what the cluster needs to have installed for the integration to work, and what the fallback is when any of it is absent.

## What retrieval-hub emits

Three data streams, all flowing into the cluster's existing observability stack (not into retrieval-hub's own storage).

### 1. Prometheus metrics (per-component)

Every retrieval-hub peer component (MCP server, auth service, UI BFF, ingestion runners) exposes a `/metrics` endpoint that Prometheus scrapes. Metrics follow Prometheus naming conventions with a `retrieval_hub_` prefix and rich labels for filtering in Grafana.

**MCP server metrics** (`retrieval-hub-mcp`):

- `retrieval_hub_mcp_tool_calls_total{tool, source_id, source_family, identity_kind, result_code, tenant}` — counter
- `retrieval_hub_mcp_tool_call_duration_seconds{tool, source_id, source_family}` — histogram
- `retrieval_hub_mcp_tool_call_errors_total{tool, source_id, error_code}` — counter
- `retrieval_hub_mcp_access_denied_total{source_id, identity_kind, reason}` — counter (important for abuse detection)
- `retrieval_hub_mcp_rewriter_invocations_total{source_id, llm, resolution_mode}` — counter
- `retrieval_hub_mcp_rewriter_duration_seconds{source_id, llm}` — histogram
- `retrieval_hub_mcp_active_connections` — gauge
- `retrieval_hub_mcp_build_info{version, commit}` — gauge (always 1; labels for version tracking)

**Auth service metrics** (`retrieval-hub-auth`):

- `retrieval_hub_auth_token_issuance_total{backend, identity_kind, result}` — counter
- `retrieval_hub_auth_token_validation_total{result}` — counter
- `retrieval_hub_auth_token_validation_duration_seconds` — histogram
- `retrieval_hub_auth_active_clients` — gauge
- `retrieval_hub_auth_jwks_fetches_total{upstream_issuer, result}` — counter (external_jwt_validator mode)
- `retrieval_hub_auth_rate_limit_hits_total{client_id}` — counter

**Core library / catalog metrics** (embedded in MCP server and UI BFF processes):

- `retrieval_hub_catalog_sources_total{status, family, visibility}` — gauge (published count etc., scraped periodically from the catalog)
- `retrieval_hub_catalog_state_transitions_total{from_status, to_status}` — counter
- `retrieval_hub_catalog_agent_writes_total{source_id, mode, result}` — counter
- `retrieval_hub_catalog_ingestion_runs_total{source_family, refresh_mode, status}` — counter
- `retrieval_hub_catalog_ingestion_duration_seconds{source_family}` — histogram
- `retrieval_hub_catalog_eval_runs_total{source_id, llm, execution_backend, result}` — counter

**UI BFF metrics** (`retrieval-hub-ui-backend`):

- `retrieval_hub_ui_requests_total{route, method, status}` — counter
- `retrieval_hub_ui_request_duration_seconds{route}` — histogram
- `retrieval_hub_ui_active_sessions` — gauge

The metric set is deliberately **small and labeled**. Labels carry the dimensions we want to slice by in Grafana: source, family, identity kind, tenant, tool name, result code. Cardinality is bounded because `source_id` is a stable slug per-source, `identity_kind` is a small enum, and `tool` is a small enum.

**What we deliberately do NOT put in metrics**:

- Per-user labels (`identity_sub` as a metric label would explode cardinality).
- Query text or result content.
- Per-chunk labels.
- Long-lived counters that would persist across restarts — Prometheus handles this via counter reset detection.

### 2. OpenTelemetry traces

Every MCP tool call, every retrieval operation, every rewriter invocation, every catalog mutation emits OpenTelemetry spans. Traces are exported via OTLP (OpenTelemetry Protocol) to the cluster's configured OTel collector — typically a Jaeger, Tempo, or Grafana Cloud Tempo deployment, or (in clusters with LlamaStack) the LlamaStack `/v1/telemetry/events` endpoint.

Span conventions:

- **Span names** use the pattern `retrieval_hub.<component>.<operation>` (e.g., `retrieval_hub.mcp.tool.query`, `retrieval_hub.rewriter.invoke`, `retrieval_hub.catalog.publish_source`).
- **Span attributes** carry the same dimensions as metric labels: `rh.source_id`, `rh.source_family`, `rh.tool`, `rh.identity_kind`, `rh.tenant`, `rh.request_id`, plus operation-specific attributes (`rh.physical_index_id`, `rh.recipe_version`, `rh.rewrite_enabled`).
- **W3C Trace Context is propagated** on all incoming and outgoing HTTP calls so retrieval-hub spans join whatever parent trace the caller is in. When the caller is a LlamaStack-hosted agent (see [`llamastack.md`](llamastack.md)), retrieval-hub's spans appear as children of the agent's user-turn trace. When the caller is off-cluster (see [`claude-code.md`](claude-code.md)), retrieval-hub's spans are the root of their own trace.
- **Exceptions are recorded as span events** with stack traces redacted of sensitive data.

Sampling is configurable per-component and defaults to **parent-based sampling** (honor the upstream sampling decision if one exists, otherwise sample at a configurable rate, default 10% for production and 100% for dev).

### 3. Structured logs (Loki-compatible when available)

retrieval-hub-mcp and the other peer components emit **structured JSON logs** to stdout/stderr, which OpenShift's default logging stack (EFK / Loki / ClusterLogForwarder) ingests. Log lines include `request_id`, `trace_id`, `span_id`, `source_id`, `identity_kind`, `tenant`, and the operation-specific fields.

Log lines are intentionally **not** the primary observability path — metrics and traces are. Logs exist for post-hoc forensics and for debugging issues where trace/metric data isn't enough. PII is redacted at the source level per [`auth.md`](auth.md): tokens, client secrets, query text, and source content are never logged at info level.

## How the admin UI uses this

The retrieval-hub admin dashboard (see [`../ui-card-data.md`](../ui-card-data.md) Section 2b) holds a **thin catalog-specific slice** of the overall picture:

- Source counts (from catalog Postgres, not Prometheus)
- Last agent write timestamp (from `audit_records`, not Prometheus)
- Recent catalog changes (from `audit_records`)
- Flagged sources (drift, degraded index, stale refresh — from catalog state)
- Per-source basic health (from catalog)

All of this is **derivable from the catalog without calling Prometheus**, which keeps the admin dashboard fast and works even when Prometheus is unavailable.

For everything that depends on query volume, latency, per-identity usage, or error rates — the dashboard **deep-links to Grafana**:

- The "Cluster Health" panel has a prominent "View observability dashboards in Grafana" button. URL configured via `RETRIEVAL_HUB_GRAFANA_DASHBOARD_URL`; button hidden if unset.
- Each row in the "Top sources" table has a "Query metrics in Grafana" link that opens the Grafana retrieval-hub dashboard pre-filtered to that source's label (`?var-source=<slug>`).
- The round-2 anomaly detection panel (not in round 1) will link out to Grafana-side alerting rules for the actual detection logic.

The pattern: **retrieval-hub answers "what's in my catalog"; Grafana answers "how is it being used."**

## The Grafana dashboard retrieval-hub expects (if you're setting it up)

retrieval-hub does not ship a Grafana dashboard JSON — that's a cluster-operational concern, and the right shape depends on what other stuff the cluster runs. But for a deploy engineer setting up retrieval-hub on a new cluster, the dashboard panels we'd expect to find are:

1. **Query rate** — `rate(retrieval_hub_mcp_tool_calls_total[5m])` broken down by source and tool
2. **Error rate** — `rate(retrieval_hub_mcp_tool_call_errors_total[5m])` broken down by error_code
3. **Latency distribution** — `histogram_quantile(0.95, retrieval_hub_mcp_tool_call_duration_seconds)` per source and tool
4. **Top sources by query volume** — top N sources by query rate over the selected time range
5. **Top identities by query volume** — top N identities, broken down by kind (agent / user / service)
6. **Access denial rate** — `rate(retrieval_hub_mcp_access_denied_total[5m])` broken down by source and reason
7. **Rewriter usage** — fraction of queries with rewrite enabled, broken down by source and LLM
8. **Ingestion run status** — counter of completed/failed ingestion runs by source
9. **Auth service health** — token issuance rate, validation rate, error rate
10. **UI BFF request rate and latency** — if the UI BFF is deployed

A template dashboard JSON can ship alongside retrieval-hub's OpenShift manifests in round 2 (`deploy/grafana-dashboard.json`), but it is not a hard requirement — any cluster that has Prometheus scraping retrieval-hub's `/metrics` endpoints can build its own dashboard from the metric catalog above.

## Configuration

Each retrieval-hub component takes observability configuration via environment variables:

- `RETRIEVAL_HUB_METRICS_ENABLED` (default `true`) — whether to expose `/metrics`.
- `RETRIEVAL_HUB_METRICS_PORT` (default `9090` or the same port as the main app) — the port serving `/metrics`.
- `RETRIEVAL_HUB_OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP endpoint for trace export. If unset, traces are not exported (metrics still work).
- `RETRIEVAL_HUB_OTEL_SAMPLING_RATE` (default `0.1`) — parent-based sampling rate when no upstream sampling decision exists.
- `RETRIEVAL_HUB_LOG_LEVEL` (default `INFO`) — structured log level.
- `RETRIEVAL_HUB_LOG_FORMAT` (default `json`) — `json` or `text`.
- `RETRIEVAL_HUB_GRAFANA_DASHBOARD_URL` — URL of the Grafana retrieval-hub dashboard, used for deep links from the admin UI. If unset, deep-link buttons are hidden.

All components read the same variables — there is no per-component telemetry config. This is intentional: one observability story for the whole system.

## Ownership boundary

| Concern | Source of truth | Notes |
|---|---|---|
| Metric emission | retrieval-hub peer components | Prometheus client libraries |
| Trace emission | retrieval-hub peer components | OpenTelemetry SDK |
| Metric storage and aggregation | Cluster Prometheus | We don't run our own |
| Trace storage | Cluster OTel collector / Jaeger / Tempo | We don't run our own |
| Log storage | Cluster logging stack (EFK / Loki) | We don't run our own |
| Dashboards | Cluster Grafana (operator-managed) | We don't ship dashboards in round 1; optional template in round 2 |
| Alerting rules | Cluster Prometheus Alertmanager | We don't define rules; operators do |
| Long-term retention | Cluster-configured retention policies | We don't manage it |
| Query volume history | **Cluster Prometheus**, not retrieval-hub Postgres | This is why retrieval-hub does not have a query_log table |
| Catalog state snapshots | retrieval-hub Postgres | Count of published/draft/etc. sources |
| Audit trail | retrieval-hub Postgres | State transitions and agent writes |
| Source-level access decisions | retrieval-hub Postgres (via access denial metric emission) | Counter metric; detail is in the audit trail |

The pattern is consistent: **catalog state and audit stay in retrieval-hub Postgres; everything observational lives in the cluster's observability stack.**

## Standalone fallback

When Prometheus and Grafana are **not** present on the cluster — a small customer install, a dev cluster, an air-gapped environment — retrieval-hub falls back gracefully:

- **Metric emission continues.** The `/metrics` endpoints are still exposed. Nothing scrapes them, but the components work. A deploy engineer can configure an ad-hoc Prometheus later without code changes.
- **Trace export is disabled** if `RETRIEVAL_HUB_OTEL_EXPORTER_OTLP_ENDPOINT` is unset. Traces are still generated internally for local debugging, but not exported.
- **Structured logs go to stdout** as usual. Whatever is harvesting stdout (journald, podman logs, OpenShift console) ingests them.
- **The admin dashboard hides the deep-link buttons** to Grafana. The "View in Grafana" rows disappear; the catalog-derived panels (cluster health, top sources, recent changes) still render.
- **Round-2 anomaly detection**, which depends on Prometheus metrics, is simply unavailable. We do not try to implement a fallback anomaly detector in the catalog — that would undermine the "reuse what's there" principle.

The fallback is **degraded but functional**. Every catalog operation works. What's missing is the observational richness Prometheus and Grafana provide, which is fair because those are substantial systems to run.

## The clean exit

If the cluster switches from Prometheus+Grafana to a different observability stack (Datadog, New Relic, Honeycomb, Grafana Cloud, etc.), the exit is usually configuration only:

1. **Metrics** — Prometheus client libraries emit in the OpenMetrics format which most observability systems can scrape directly. For systems that don't scrape, a small adapter sidecar or remote_write configuration covers the gap.
2. **Traces** — OpenTelemetry OTLP is the universal export format. Point `RETRIEVAL_HUB_OTEL_EXPORTER_OTLP_ENDPOINT` at the new collector.
3. **Logs** — stdout JSON works with any log aggregator.
4. **UI deep links** — update `RETRIEVAL_HUB_GRAFANA_DASHBOARD_URL` (rename it to `_OBSERVABILITY_DASHBOARD_URL` in a future version if we support non-Grafana) to point at the new dashboarding system.

No retrieval-hub code changes are required for any of this, because we don't bake Prometheus or Grafana into the data model or the runtime. Everything is configuration.

## What's Decided

- **Observability is delegated to the cluster's Prometheus + Grafana + OpenTelemetry stack.** retrieval-hub does not have a native query log, does not ship Grafana dashboards in round 1, and does not build anomaly detection.
- **Prometheus metrics are emitted by every peer component** with a `retrieval_hub_` prefix and rich labels for dimensional slicing in Grafana.
- **OpenTelemetry traces are emitted via OTLP.** W3C Trace Context is propagated on inbound and outbound HTTP calls so retrieval-hub spans join upstream traces (LlamaStack agent turns, Kagenti gateway requests, etc.) when appropriate.
- **Structured JSON logs** go to stdout for ingestion by the cluster's logging stack. PII redacted.
- **The admin UI deep-links to Grafana** for anything depending on query volume, latency, per-identity usage, or error rates. The UI shows a small catalog-specific slice (source counts, recent changes, flagged sources) and then gets out of the way.
- **Per-user / per-identity labels are deliberately omitted from metrics** to control cardinality. Per-identity breakdowns happen in Grafana via query-time filtering, not via high-cardinality metric labels.
- **Standalone fallback** hides the Grafana deep links and keeps the catalog-derived panels working. Degraded but functional on clusters without Prometheus/Grafana.
- **Cardinality is bounded** by design: metric labels are constrained to small enums and per-source slugs.

## What's Open

- **Template Grafana dashboard JSON** for operators to import as a starting point. Not a round-1 deliverable; probably ships in round 2 alongside the OpenShift deploy manifests.
- **Per-cluster retention policies** for metrics, traces, and logs. These are operator-driven and out of retrieval-hub's scope, but we should document minimum recommended retention for the dashboard to be useful (probably 7–14 days for query volumes, 90 days for audit-adjacent events).
- **Alerting rules** — which Prometheus alerts are "retrieval-hub operators should see this" vs "ignore." Probably a starter set ships with the dashboard JSON in round 2.
- **Exact sampling policy for traces.** 10% parent-based sampling is the default; that may be too aggressive for debugging in production and not aggressive enough under load. Tune per cluster.
- **Integration with LlamaStack's `/v1/telemetry/events` endpoint** as a trace sink. LlamaStack supports OTel export natively, so this may "just work" by pointing `OTEL_EXPORTER_OTLP_ENDPOINT` at LlamaStack's endpoint — but verify against a real LlamaStack install before documenting.
- **Per-metric cardinality audit before production.** Label choices above look bounded, but `source_id` can grow large in a cluster with many published sources. If cardinality becomes a problem, drop `source_id` from the counter and make it queryable via traces only.
- **Grafana dashboard URL templating for source-specific deep links.** The pattern `?var-source=<slug>` assumes the Grafana dashboard uses a template variable named `source`. We should document the expected dashboard variable names so cluster operators know how to set up dashboards that work with retrieval-hub's deep links.
- **Whether retrieval-hub should emit metrics about MLflow / LlamaStack reachability** (e.g., `retrieval_hub_mlflow_reachable`) so operators can alert on integration failures. Probably yes; low priority.
