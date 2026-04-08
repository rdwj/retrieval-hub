# Platform Integrations

This directory captures how retrieval-hub integrates with the OpenShift AI capabilities that may already exist on the deployment cluster — specifically **LlamaStack**, **MLflow**, **Kagenti**, the **AI Assets** registry, and **AutoRAG**. Each capability has its own detail doc here. This file is the entry point: it explains the integration philosophy, surfaces a clear-eyed analysis of where round-1 retrieval-hub design **duplicated** things the platform already provides, and points at the per-capability docs.

The TL;DR is: a meaningful fraction of round-1 retrieval-hub design was duplicating things the cluster already provides. The right move is to consume those capabilities where present and to keep retrieval-hub runnable standalone where they aren't.

## Integration philosophy

Three commitments shape every doc in this directory.

**Deployable anywhere.** retrieval-hub must run on a cluster that has none of LlamaStack, MLflow, Kagenti, AI Assets, or AutoRAG, and it must run on a cluster that has all of them. Every integration is *additive*: turning it on enriches the experience, turning it off degrades it gracefully without losing core function. There is **no integration** in this directory that is allowed to be a hard dependency of the core product.

**Consume what's there, don't reinvent.** If the platform provides a capability — experiment tracking, prompt registry, agent identity, OAuth token exchange, MCP gateway — retrieval-hub should consume it rather than ship its own. Every integration doc names exactly what we stop building when the capability is present, and what fallback we ship when it isn't.

**Score cards stay ours.** The catalog — sources, recipes, eval *results as projected onto cards*, rewriter metadata, lineage, lifecycle — is the heart of retrieval-hub's value proposition and stays authoritative. We may delegate eval *execution* to LlamaStack, eval *history of record* to MLflow, agent *identity* to Kagenti+Keycloak, and tool *aggregation* to the Kagenti MCP Gateway. We do not delegate the catalog itself or the per-source rewriter metadata.

These three commitments explain almost every concrete design choice in the per-capability docs.

## A meaningful fraction of round-1 design was duplicating the platform

Before the cluster context was clear, round 1 of retrieval-hub designed several subsystems against the assumption that we might deploy alone into a customer environment with nothing already in place. With the deployment target now known to include LlamaStack, MLflow, and (eventually) Kagenti — and with AutoRAG and the AI Assets registry as candidate integrations — that assumption was wrong for the production happy path. Several round-1 choices need to be reframed as "the standalone fallback" rather than "the production default."

What follows is the honest assessment of what we were building vs. what the platform provides.

### Experiment tracking and run history

**What round 1 designed.** `evaluation.md` described eval suites as catalog objects, eval runs as rows in retrieval-hub's Postgres, test cases as Parquet files in MinIO, and an eval orchestrator that runs the production retrieval path against a test set, computes metrics, and writes the result row. The catalog's `evals` field on a source carried full historical results.

**What MLflow already provides.** Versioned experiment tracking with run comparison, per-run parameters and metrics, multi-step trace capture, dataset versioning, prompt registry, and a mature UI for browsing all of it. As of MLflow 3.10 (March 2026), GenAI workflows are first-class: trace cost tracking, multi-turn evaluation, RAG-specific metrics, prompt-vs-prompt comparison.

**The right move.** MLflow becomes the **history of record** for eval runs when present. The catalog keeps the score-on-the-card (the headline numbers a source owner needs at browse time), plus lineage pointers `{experiment_id, run_id, dataset_id}` into MLflow for the full record. We stop building our own run history UI, our own dataset versioning, our own prompt registry, our own experiment comparison. When MLflow is *not* present, we fall back to the round-1 native Postgres+MinIO design — degraded comparison experience, no rich UI, but the score-on-the-card still works.

See [`mlflow.md`](mlflow.md) for the object-model mapping and the buffer-and-reconcile pattern when MLflow is transiently unreachable.

### Eval execution and metrics

**What round 1 designed.** An eval orchestrator inside the core library, calling the production retrieval path for each test case, computing Recall@k / MRR / NDCG / latency / cost / rewrite_lift in our own code, returning a result row.

**What LlamaStack provides.** A documented Evaluation API (`/v1/eval`) with a **Ragas provider** that ships in RHOAI 3.0+, supporting RAG-specific metrics out of the box (faithfulness, answer relevancy, context precision, etc.) plus the standard retrieval metrics. The execution is async, benchmark/scoring-function-based, and tied into LlamaStack's telemetry.

**The right move.** When LlamaStack is present, eval **execution** is delegated to it. retrieval-hub still defines the eval suite and the test cases (because the suite is a catalog object owned by the source owner), but the metric-computing run happens inside LlamaStack with Ragas, and we project the resulting metrics onto the source card. This means we stop maintaining a metric-computation library and gain Ragas metrics for free. When LlamaStack is *not* present, we fall back to running evals through our own orchestrator using the production retrieval path — the round-1 design.

The score-on-the-card is unchanged in either path: the value the user sees on a card comes from retrieval-hub, regardless of where the metric was computed. **Score cards stay ours; eval execution is delegated.**

See [`llamastack.md`](llamastack.md) for the eval delegation contract.

### Prompt storage

**What round 1 designed.** `query-rewriter.md` described a shared rewriter prompt template living in the core library and (via `prompt_override_id`) per-source override prompts as catalog objects in retrieval-hub's Postgres. We were on the hook for prompt versioning, diff display, history, and rollback flows.

**What MLflow already provides.** A prompt registry with versioning, comparison, tagging, and audit. Designed for exactly this kind of GenAI prompt-engineering workflow.

**The right move.** When MLflow is present, the **shared rewriter template** lives as an MLflow prompt registry entry, versioned there. retrieval-hub keeps the *active version pointer* in its own configuration for hot-path lookup (we don't want every rewrite call to hit MLflow), but the version history, the diff view, and the rollback flow are all MLflow's. Per-source override prompts (the rare case where a source needs its own template instead of the shared one) work the same way: MLflow when present, native fallback when absent.

The per-source **rewriter metadata** (vocabulary mappings, sample queries, domain notes, schema hints) stays in retrieval-hub Postgres regardless. It's strongly typed, runtime hot-path, and not a "prompt" in MLflow's sense.

See [`mlflow.md`](mlflow.md) for the prompt registry integration shape.

### Agent identity and JWT issuance

**What round 1 designed.** `auth.md` described OAuth 2.1 `client_credentials` issuing short-lived JWTs through `retrieval-hub-auth`, with `external_jwt_validator` as a fourth IdP backend mode for the case where a customer environment already has an identity story. The four IdP backends were `local` / `openshift_oauth` / `oidc_external` / `external_jwt_validator`, with `client_credentials` issuance as the baseline.

**What Kagenti provides.** SPIFFE/SPIRE for workload identity, Keycloak for OAuth 2.1, and a **Kuadrant AuthPolicy** at the MCP Gateway implementing **RFC 8693 token exchange**. The gateway exchanges the agent's broad token for a *narrowly-scoped audience-bound* token before forwarding the call to the downstream MCP server. This is designed to prevent lateral movement: a token issued for retrieval-hub cannot be used to attack any other MCP server, because its audience claim doesn't match.

**The right move.** In a Kagenti-fronted deploy, retrieval-hub-auth runs in `external_jwt_validator` mode and never issues tokens. The Kagenti MCP Gateway issues audience-scoped tokens; retrieval-hub-auth validates them and translates the claims into the retrieval-hub claim shape (SPIFFE `sub` → structured identity, Keycloak roles → `rh_identity_groups`, namespace annotation → `rh_tenant`). The other three IdP backends remain available and become the right choice for non-Kagenti clusters. **Inherited auth is the production default in Kagenti deploys**, with our own issuance as the fallback.

The hard-coded rule that **`admin.write` is never issued to agent identities** stays in place — enforced in code, not in claim mapping configuration, so a bad mapping cannot disable it.

See [`kagenti.md`](kagenti.md) for the token exchange flow and claim mapping.

### MCP transport, rate limiting, tool aggregation

**What round 1 designed.** A standalone MCP server with its own Route, its own auth validation, and (in the round-1 Open list) eventual rate limiting before exposure to off-cluster agents.

**What Kagenti MCP Gateway provides.** An Envoy-based MCP gateway that fronts every MCP server in the cluster, applies tool prefixing to prevent name clashes between servers, centralizes rate limiting and auditing, propagates trace context, and (per the previous section) does the audience-scoping token exchange for downstream calls.

**The right move.** When the Kagenti MCP Gateway is present, retrieval-hub-mcp registers as a backend behind it via an `MCPServer` CRD + Gateway API HTTPRoute (the more recent Kagenti registration path). Tool prefixing means agents see tools like `retrieval_hub_query` and `retrieval_hub_rewrite`, which is a fine namespacing outcome. We stop planning our own edge rate limiting in this topology; the gateway does it. We **also keep our standalone Route** for off-Kagenti consumers (the SDK from a notebook, the CLI from a laptop, an external agent that doesn't go through the gateway). Both topologies coexist and the underlying MCP server is unchanged between them.

See [`kagenti.md`](kagenti.md) for registration via CRD and the tool-filter wristband layering.

### Tool discovery conventions

**What round 1 implied.** The `/plan-tools → /create-tools → ...` workflow would design retrieval-hub's MCP tool surface against generic MCP conventions.

**What LlamaStack and Kagenti expect.** Both define standard MCP server registration paths (LlamaStack `/v1/connectors`, Kagenti `MCPServer` CRD), and both have conventions for how tool discovery responses get filtered, prefixed, and named. The Kagenti MCP Gateway specifically filters tool discovery responses based on a **tool-filter wristband** — a signed JWT listing which tools the agent is allowed to see — so tool design has implications for how cleanly tools can be gated per-agent.

**The right move.** The `/plan-tools` workflow when it runs should treat LlamaStack and Kagenti conventions as **input constraints**, not invent new ones. Specifically, the wristband mechanism makes a case for splitting agent write tools by mode (`append` / `upsert` / `annotate` as separate tools, separately gateable at the wristband layer) rather than one tool with a `mode` parameter. This is captured as guidance in [`../mcp-tools-planning.md`](../mcp-tools-planning.md) so it's picked up when `/plan-tools` actually runs.

### Observability: query logs, latency histograms, abuse detection

**What round 1 designed.** An admin dashboard with per-source query volumes, top-consumer breakdowns, anomaly detection, and a native query log feeding all of the above. The implication was retrieval-hub would build a `query_log` table in Postgres, run aggregation pipelines, ship Grafana-equivalent dashboards, and build threshold-based anomaly detection.

**What the cluster already provides.** A mature observability stack: Prometheus scraping `/metrics` endpoints, Grafana for dashboards, OpenTelemetry for traces, a logging backend (EFK / Loki). Every real OpenShift cluster has all of this. Building a native query log would mean reimplementing a subset of Prometheus inside retrieval-hub Postgres.

**The right move.** **Delegate observability entirely to Prometheus + Grafana + OTel.** retrieval-hub emits metrics (`retrieval_hub_*` naming, dimensional labels) and OpenTelemetry traces with W3C Trace Context propagation. The cluster's Prometheus scrapes the metrics; Grafana visualizes them. The retrieval-hub admin dashboard holds a **thin catalog-specific slice** (source counts, recent catalog changes, flagged sources derived from catalog state) and **deep-links to Grafana** for query volumes, latency distributions, per-identity breakdowns, and anomaly detection. No native query log. Round 2 admin features (anomaly detection, top consumers by query volume, write activity dashboards) are also delegated to Grafana when shipped. See [`prometheus-grafana.md`](prometheus-grafana.md).

The one piece of retrieval-hub-native observability is the **catalog audit trail** (state transitions, agent writes) stored in Postgres. That's not observational in the Prometheus sense — it's a permanent audit log that lives with the catalog. Everything else observational lives in Prometheus.

### Recipe optimization and synthetic Q&A

**What round 1 designed.** `evaluation.md` named SDG Hub as the working assumption for synthetic Q&A generation. `integrations/autorag.md` described AutoRAG as a considered candidate for recipe tuning *and* eval data generation.

**What the platform now changes.** With LlamaStack present, eval data generation has another candidate: LlamaStack's eval API can produce or consume Ragas-style test sets, and there are RHOAI-documented patterns for using Ragas for synthetic evaluation. So the eval-data side of AutoRAG has a competitor; we'd pick whichever lands first against a real corpus. The **recipe optimization** side of AutoRAG (automated search across chunkers, embedding models, top-k values, etc.) is still uniquely AutoRAG's — neither LlamaStack nor MLflow does that.

**The right move.** AutoRAG's role narrows to recipe optimization specifically. Eval data generation can come from LlamaStack/Ragas, AutoRAG, SDG Hub, or hand curation, depending on what's present and what works. With MLflow as the experiment backbone, an AutoRAG tuning run becomes an MLflow run with the scoreboard as MLflow metrics, which is a much better fit than the scoreboard living in MinIO Parquet.

See [`autorag.md`](autorag.md) for the updated framing.

### What stays exactly as designed

To balance the "things to stop building" list, here's what round 1 got right and doesn't change:

- **The query rewriter** — shared core + per-source metadata. None of LlamaStack, MLflow, Kagenti, AutoRAG, or AI Assets has anything in this space. The shared template moves to MLflow prompt registry; the per-source metadata model stays in retrieval-hub Postgres because it's typed, operational, and on the hot path. **The differentiator is intact.**
- **The catalog** — source / family / retrieval pattern dispatch / lifecycle / rewriter metadata / agent_write_policy / lineage. MLflow doesn't model curated retrieval sources; LlamaStack's vector_stores don't model recipes or lifecycles or owners. The catalog is retrieval-hub-authoritative.
- **Source adapters and the family discriminator.** Retrieval pattern dispatch, GraphRAG-as-tool, the four v0 corpora. None of the platform capabilities touches this.
- **Agent writes via MCP** with per-source `agent_write_policy`. The policy is ours; Kagenti's tool-filter wristband is a separate gate at the gateway. They layer cleanly: the gateway gates *tool classes* ("this agent can use retrieval-hub's append tool"), we gate *per-source actions* ("this agent can write to source X").
- **The MCP server itself.** The component doesn't change — same FastMCP 3 server, same scaffolding, same `/plan-tools` workflow for tool design. What changes is *deployment topology*.
- **`agent.write_policy.allowed: false` as the default.** Agent-writability stays opt-in per source.
- **The four v0 sources** — Red Hat product docs, VA clinical practice guidelines, Wikipedia, public code repos. Heterogeneity on purpose; the data model's regression test.
- **The `external_jwt_validator` rule** that no claim mapping may emit `admin.write` for an `agent` or `service` identity. Enforced in code, not configuration.

## Per-capability summary

| Capability | Status | What we consume from it | Detail doc |
|---|---|---|---|
| **LlamaStack** | Technology Preview on target cluster (RHOAI 3.0+) | Toolgroup registration for agent access to retrieval-hub MCP, `/v1alpha/eval` + Ragas for eval execution, OAuth2 provider alignment, OpenTelemetry trace propagation | [`llamastack.md`](llamastack.md) |
| **MLflow** | Installed separately, no SSO assumption | Experiment tracking for eval runs, prompt registry for the shared rewriter template, dataset tracking for test cases, run comparison UI | [`mlflow.md`](mlflow.md) |
| **Kagenti** | Coming to the target cluster, not present yet | MCP Gateway registration via `MCPServer` CRD, RFC 8693 audience-scoped token exchange, SPIFFE/SPIRE workload identity, namespace-as-tenant, tool-filter wristband | [`kagenti.md`](kagenti.md) |
| **Prometheus + Grafana + OTel** | Cluster observability stack | Metric scraping from all peer components, OTel trace export, deep-link targets for the admin dashboard. No native query log; observability fully delegated. | [`prometheus-grafana.md`](prometheus-grafana.md) |
| **AI Assets** | Coexistence with the RHOAI AI Hub registry | Source discovery surface alongside MCP servers and models | [`openshift-ai-assets.md`](openshift-ai-assets.md) |
| **Claude Code** | Off-cluster MCP consumer | Standalone Route topology; JWT in env var; one-per-runtime template | [`claude-code.md`](claude-code.md) |
| **AutoRAG** | Considered, not committed | Recipe optimization at source creation and during drift; possibly synthetic Q&A generation | [`autorag.md`](autorag.md) |

## How to read the per-capability docs

Each integration doc in this directory follows roughly the same shape:

1. **What the capability is**, in one paragraph, with current sources.
2. **What retrieval-hub consumes from it** when the capability is present.
3. **What surfaces retrieval-hub registers into it** (where applicable — connector registration, prompt registry entries, MCP Gateway CRDs).
4. **The ownership boundary**: a table of which fields are authoritative on which side, modeled on the table in [`openshift-ai-assets.md`](openshift-ai-assets.md).
5. **The standalone fallback**: how retrieval-hub functions when this capability is absent. This is the round-1 design degraded but functional.
6. **The clean exit**: what we do if we decide to retire this integration entirely.
7. **What's Decided** and **What's Open**, consistent with the rest of the docs.

The one doc that doesn't fit this template is this README, which is the platform overlap analysis and the index.

## What this directory is not

- It is not a roadmap with dates. The integrations are sequenced by need.
- It is not a place for tool-level design. MCP tool design happens via `/plan-tools`; the input constraints from these integrations live in [`../mcp-tools-planning.md`](../mcp-tools-planning.md).
- It is not a place for runtime-configuration documentation. How a specific cluster's retrieval-hub is configured to talk to its specific MLflow / LlamaStack / Kagenti instance is operations documentation, written when there's a real deployment to document.

## Cross-references

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — system overview, including the platform-integration topology
- [`../SYSTEMS.md`](../SYSTEMS.md) — subsystem index
- [`../auth.md`](../auth.md) — IdP backends including `external_jwt_validator` (the production default in Kagenti deploys)
- [`../evaluation.md`](../evaluation.md) — eval suites, with MLflow as the experiment backbone and LlamaStack as the execution backend when present
- [`../query-rewriter.md`](../query-rewriter.md) — shared template lives in MLflow prompt registry when present
- [`../catalog.md`](../catalog.md) — ownership boundary section
- [`../mcp-server.md`](../mcp-server.md) — three deployment topologies (standalone Route, LlamaStack connector, Kagenti MCP Gateway)
- [`../mcp-tools-planning.md`](../mcp-tools-planning.md) — guidance for the eventual `/plan-tools` workflow including the tool-filter wristband consideration
