# MCP Server (`retrieval-hub-mcp`)

The MCP server is the **only external surface agents touch**. UI users go through the UI, source owners go through the CLI, but every agent runtime — LangGraph, LlamaStack, Kagenti, Claude Code, anything else — connects here and only here. Everything we do to make retrieval-hub agent-friendly happens through this component.

This document describes the **component**: how it's built, how it's deployed, how it relates to the rest of the system, and how its tool inventory gets designed. It does **not** specify the tool surface itself. That is deliberate — see "Tool design" below.

## Where it sits in the platform pattern

`retrieval-hub-mcp/` is a peer top-level component in the repo, exactly like `memory-hub-mcp` is in memory-hub. It carries its own `Containerfile`, `Makefile`, `pyproject.toml`, `requirements.txt`, `src/`, `tests/`, and `openshift.yaml`. It is independently buildable and deployable. It imports the core library at `src/retrieval_hub/` for domain logic and never reaches around the core library to talk to storage directly.

It is the **only** peer component, other than the auth service, that agents are expected to reach over the network. The UI's BFF, the CLI, and the SDK all also call into the MCP server (or, equivalently, the core library through the MCP transport) — not into the core library directly across the network — so the same surface is exercised by every consumer.

## How it's built

- **Framework**: FastMCP 3.
- **Transport**: streamable-http. SSE is deprecated; we do not use it.
- **Scaffolding**: scaffolded from the **fips-agents MCP template** via `fips-agents create mcp-server retrieval-hub-mcp`. Never hand-rolled, and never delegated to a sub-agent — the template carries the test scaffolding, the permission handling, the registration patterns, and the FIPS-clean defaults that we want to inherit on day one.
- **Base image**: Red Hat UBI9 Python.
- **Auth integration**: validates JWTs issued by `retrieval-hub-auth`. See [`auth.md`](auth.md).
- **Core library coupling**: in-process import of `retrieval_hub` (the core lib lives at `src/retrieval_hub/` in the repo and is installed into the MCP container as a dependency at build time). The MCP server does not hold its own copy of domain logic.
- **Test framework**: pytest with the structure that the template ships with. 80% coverage target.

The expected build command is the standard remote-build flow on `ec2-dev-2`, since the deploy target is OpenShift and the developer machine is a Mac. Local builds are fine for syntax-checking the Containerfile but not for deploying.

## Tool design

**The tool inventory is intentionally not specified in this document.** Tools are designed through the prescriptive workflow that the fips-agents MCP template ships with:

```
/plan-tools  →  /create-tools  →  /exercise-tools  →  /write-system-prompt  →  /update-docs  →  /deploy-mcp
```

Each step has a purpose: `plan-tools` is where we decide what tools should exist *based on the source families and the agent use cases we are actually trying to serve*; `create-tools` writes them; `exercise-tools` proves they work end-to-end against a real agent; `write-system-prompt` produces the system prompt that an agent should be given when it has these tools; `update-docs` keeps `mcp-server.md` and the rest of the docs honest; and `deploy-mcp` ships it.

This is not a placeholder. Pre-specifying tools before going through `plan-tools` is how MCP servers end up with surface area nobody actually wants. The tools we will design will fall out of three concrete questions, asked in this order:

1. **What does an agent need to do** to discover sources, fetch a source's recipe and sample prompts, retrieve from a source, and (where enabled) ask a source for query rewrites? The data shapes for each of those are already implied by [`catalog.md`](catalog.md) and [`query-rewriter.md`](query-rewriter.md). The *tool granularity* (one fat tool vs. several focused ones, how much is a parameter vs. a separate tool) is a `plan-tools` question.
2. **What does an agent need to do that *spans* sources?** Cross-source search, capability filtering, family-aware routing — these are real and they probably want their own tools, but the design lives in `plan-tools` after we have at least one real agent driving the requirements.
3. **What absolutely must not be a tool?** **Catalog mutation.** Source creation, recipe edits, publish/retire, access policy changes, and rewriter-metadata edits are *human actions* and go through the UI or CLI by an authenticated human identity. They are not exposed to agents under any circumstances. Data writes into existing sources (`append`, `upsert`, `annotate`, per [`catalog.md`](catalog.md)) **are** in scope and will produce write tools. The boundary `plan-tools` must respect is "data into existing curated sources, yes; changing the curation itself, no."

When the tool inventory exists, it lands in this file under a "Tools" section that this round of the doc deliberately omits, alongside per-tool signatures, error responses, and an example call for each. Until then, the tools are **TBD by design**.

## What's *not* TBD: the cross-cutting posture

Several things are true regardless of which tools end up existing. These are the conventions every tool the server eventually exposes will follow.

### Identity and authorization

Every tool call carries an authenticated identity, resolved from the JWT issued by `retrieval-hub-auth`. The MCP server validates the token on every request — it does not trust transport-level proxy hints. Source-level access policy is enforced *inside* the core library, not in the MCP layer, so the same enforcement applies whether the caller is an agent through MCP, a human through the UI, or a script through the CLI.

There is no anonymous access. There is no "internal" trusted caller. Even in-cluster agents authenticate.

### Reads and data writes, no catalog mutation

The MCP server exposes both **read** operations and **data write** operations against sources. The line that doesn't move is between *data writes against an existing curated source* and *catalog mutation*:

- **Reads** — discover sources, fetch recipe/metadata/sample prompts, query a source, request a query rewrite. Always allowed when the caller has the right scope and the source's access policy permits it.
- **Data writes** — `append`, `upsert`, `annotate` against an existing source, governed by the source's `agent_write_policy` and the caller's auth scope (`sources.write`). The source owner opts a source into agent-writability; by default it's off. Writes flow through the same source adapter as reads, so the recipe (parser, chunker, embedding model) processes the new data — no end-runs around the source's curation.
- **Catalog mutation** — creating sources, editing recipes, editing rewriter metadata, editing access policy, publishing, retiring. **Not exposed via MCP, ever.** These are human actions performed through the UI or CLI by an authenticated human identity holding the `admin.write` scope. The IdP backend is configured to never issue `admin.write` to agent identities.

The reason this boundary is the right place to draw the line: it gives the catalog a coherent trust model. The *curation* of a source — what it's called, how it's chunked, who can see it, whether it's published — is a human responsibility, and humans are accountable for it. *Data inside a curated source* can come from humans or from agents, scoped by the policy the human owner declared. An agent that contributes a clinical observation to a clinical-notes source is doing exactly what the source owner enabled it to do; an agent that tries to create a brand new source is doing something it shouldn't be doing on its own and the right answer is "ask a human."

Mixing data writes and catalog mutation in a single tool surface is what would let agents grow into roles their owners never intended. Keeping them on opposite sides of this line is what makes the agent-write surface safe to expose.

### Errors

Tool errors are structured. Every error response carries:

- A stable, machine-readable `code`. The round-1 reserved set includes:
  - **Read-path codes**: `source_not_found`, `source_retired`, `source_not_published`, `access_denied`, `pattern_not_supported`, `pattern_parameter_invalid`, `rewrite_disabled`, `backend_unavailable`, `recipe_version_mismatch`
  - **Write-path codes**: `write_not_allowed` (source's `agent_write_policy.allowed = false`), `write_mode_not_allowed` (source allows writes but not this mode), `write_validation_failed` (content failed the source's validation schema), `write_scope_required` (caller missing `sources.write`), `write_provenance_required`, `write_idempotency_conflict` (upsert key collision)
  - **Cross-cutting codes**: `auth_invalid`, `auth_expired`, `rate_limited`, `internal_error`
- A human-readable `message` for logs and UIs
- Where relevant, a `details` object with the specific identifiers involved

The set is finite and reserved up front so `create-tools` cannot invent ad-hoc error shapes per tool. New codes get added by amending this list, not by tools rolling their own.

### Pagination and streaming

Any tool that can return more than ~50 items returns a paginated response with an opaque cursor. No offset/limit pagination — we don't want to commit to a specific backend's paging semantics. The tool layer maps cursor → backend-specific continuation token inside the adapter.

For long-running operations (large retrievals, multi-source queries), streaming is permitted because the underlying transport is streamable-http. The convention is partial-result streaming with a final "complete" frame, not chunked text. Concrete shapes will be defined per tool.

### Logging and tracing

Every tool call gets a structured log line with: caller identity, source id (when applicable), tool name, latency, result code, and a request id that propagates to downstream calls (vLLM, pgvector, etc.). OpenTelemetry traces are emitted with the same request id. No PII in logs by default; source content is never logged at info level.

### Recipe-version awareness

When a tool returns retrieval results, every result item carries the **physical index id** and **recipe version** it came from. This is the lineage handle described in [`catalog.md`](catalog.md). It is not optional — it's part of the result shape regardless of which tool returned it. Agents can ignore it; analytics and audit cannot.

## Talking to the core library

The MCP server is a thin layer over the core library. The pattern is:

1. Validate the JWT and resolve the caller identity.
2. Validate the tool inputs against the input schema.
3. Call into the core library with the resolved identity as a first-class argument.
4. Translate the core library's typed return value into the tool's response shape.
5. Emit log + trace.

Step 3 is the only step that does real work. Steps 1, 2, 4, and 5 are the same for every tool. The fips-agents MCP template provides middleware-style helpers for them so we don't reinvent the wrapper per tool.

The core library is *not* allowed to know it's being called from MCP. It takes typed arguments and returns typed values. This is what lets the UI's BFF and the CLI exercise the same code paths without going through MCP at all.

## Deployment shape

Deployed as a single Deployment in the `retrieval-hub` OpenShift project, behind a Service and a Route. Replicas are stateless — no sticky sessions, no in-memory caches that need affinity. Configuration is environment-driven:

- `RETRIEVAL_HUB_DB_URL` — Postgres connection string (read by the core library)
- `RETRIEVAL_HUB_AUTH_URL` — auth service base URL for token validation
- `RETRIEVAL_HUB_VLLM_URL` — vLLM endpoint for the cluster default rewrite LLM
- `RETRIEVAL_HUB_LOG_LEVEL`
- Plus whatever the fips-agents template injects for its own concerns

Secrets (DB credentials, auth service keys) are mounted from OpenShift Secrets, not env vars, where they exist.

The Route is the public agent endpoint. Whether it's exposed to off-cluster agents or only in-cluster is a deploy-time policy decision; the server itself doesn't care.

## Deployment topologies

The MCP server runs in **one of three topologies**, depending on what platform capabilities the cluster has. The MCP server itself — code, tools, auth validation logic — is **unchanged across all three**. What differs is the registration mechanism, the network path agents take to reach it, and the auth validation rules. All three topologies can also coexist in the same deployment: a cluster with Kagenti can simultaneously serve retrieval-hub-mcp through the Kagenti MCP Gateway (for in-cluster agents) and through its standalone Route (for the SDK from a notebook, the CLI from a laptop, off-cluster agents).

### Topology 1: Standalone Route

The simplest topology. retrieval-hub-mcp has its own OpenShift Route, agents connect to it directly with a JWT obtained from the cluster's existing OAuth path (or from retrieval-hub-auth in `local` / `openshift_oauth` / `oidc_external` mode). This is the round-1 default and the right topology for clusters without LlamaStack or Kagenti.

```
Agent → Route → retrieval-hub-mcp
```

Token audience is whatever retrieval-hub-auth or the configured IdP issued. Tool names are the raw names retrieval-hub-mcp registers (no prefix).

### Topology 2: LlamaStack connector

Retrieval-hub-mcp registers itself as a connector via LlamaStack's `/v1/connectors` API (see [`integrations/llamastack.md`](integrations/llamastack.md)). LlamaStack-hosted agents discover and invoke retrieval-hub tools through their normal LlamaStack tool-discovery and tool-invocation paths. The standalone Route stays available for non-LlamaStack consumers.

```
LlamaStack Agent → LlamaStack tool runtime → /v1/connectors → retrieval-hub-mcp
                                                                    ↑
Off-LlamaStack consumer → Route ────────────────────────────────────┘
```

Token audience is whatever the cluster's OAuth provider issued; LlamaStack and retrieval-hub-auth validate against the same JWKS (typically Keycloak) so the same token is valid for both. Tool names get whatever prefix LlamaStack applies to connector-provided tools.

### Topology 3: Kagenti MCP Gateway

The production happy path on the target cluster (when Kagenti arrives — see [`integrations/kagenti.md`](integrations/kagenti.md)). Retrieval-hub-mcp registers as a backend behind the Kagenti MCP Gateway via an `MCPServer` CRD + Gateway API HTTPRoute. Kagenti-hosted agents reach retrieval-hub through the gateway, which applies tool prefixing (`retrieval_hub_*`) and exchanges the agent's broad token for an audience-scoped downstream token before forwarding the call. The standalone Route stays available for off-Kagenti consumers, and topology 2 (LlamaStack connector) can also coexist if both LlamaStack and Kagenti are present.

```
Kagenti Agent → Kagenti MCP Gateway → audience-scoped token → retrieval-hub-mcp
                                                                       ↑
LlamaStack Agent → /v1/connectors ─────────────────────────────────────┤
                                                                       ↑
Off-cluster consumer → Route ──────────────────────────────────────────┘
```

Token audience in this topology is the gateway-minted audience for retrieval-hub's hostname (typically `retrieval-hub.retrieval-hub.svc.cluster.local`). retrieval-hub-auth runs in `external_jwt_validator` mode, validating the gateway-issued audience-scoped token and translating Keycloak claims into the retrieval-hub claim shape. Tool names are prefixed with `retrieval_hub_` by the gateway.

### Coexistence

All three topologies use **the same MCP server**. The auth validator handles both gateway-issued audience-scoped tokens and direct-Route tokens by checking against the configured set of acceptable audiences. The tool surface is identical from the server's perspective; what varies is which network path delivered the call. Agents on the same cluster can reach retrieval-hub through whichever path their runtime configuration prefers — and a single deploy can support all three simultaneously without coordination.

This is what makes the integration **deployable anywhere**: every cluster gets at least topology 1, clusters with LlamaStack get topology 2 in addition, clusters with Kagenti get topology 3 in addition. None of the topologies excludes the others.

## Registration with AI Assets

When AI Assets integration is enabled, `retrieval-hub-mcp` registers itself as an MCP server in the AI Assets registry on startup, and registers each `Published` source as an "AI Asset" entry pointing back to the MCP server's tool surface. The full design lives in [`integrations/openshift-ai-assets.md`](integrations/openshift-ai-assets.md). Integration is optional — retrieval-hub functions normally without it.

## What's Decided

- **One MCP server**, one Containerfile, one Deployment, one Route. Not microservices.
- **FastMCP 3, streamable-http, scaffolded from fips-agents template.** No SSE, no hand-rolled MCP machinery.
- **Reads and data writes both exposed to agents.** Data writes (`append`, `upsert`, `annotate`) are scoped per-source by `agent_write_policy` and per-caller by the `sources.write` scope. Defaults are read-only — sources are opt-in to agent-writability.
- **Catalog mutation is *not* exposed to agents, ever.** Source create/edit/publish/retire and recipe/policy/metadata edits go through the UI or CLI by an authenticated human identity. The IdP backend never issues `admin.write` to agent identities.
- **JWT auth on every call**, validated against `retrieval-hub-auth`, with source-level access policy and `agent_write_policy` enforced inside the core library.
- **Cursor-based pagination, structured errors with the reserved code set, recipe-version-aware result items, audit records on every write.** All tools, no exceptions.
- **Tool inventory is designed via `/plan-tools → /create-tools → ...`**, not specified in this doc. The boundary the workflow must respect is the data-write vs. catalog-mutation line above.

## What's Open

- **The actual tool inventory.** By design.
- **Whether write tools are one general "write" tool with a `mode` parameter, or three separate tools (`append`, `upsert`, `annotate`).** A `plan-tools` question. The error model already distinguishes `write_mode_not_allowed`, so either shape works.
- **Whether the cluster default rewrite LLM is reachable through this server's URL** or directly. Probably directly (the rewriter calls vLLM itself, the MCP server is not a proxy), but worth re-checking when `query-rewriter.md` is implemented.
- **Whether multi-source search is one tool or several.** A `plan-tools` question once we have a real agent making the case.
- **Off-cluster agent access policy.** The deployment supports it; whether it's enabled by default for v1 is a separate decision and probably "no, opt-in per cluster."
- **Rate limiting posture, especially on write tools.** Writes are more dangerous than reads; they probably want their own rate-limit class. Round 2 unless a use case forces it earlier.
- **Whether write idempotency is enforced via a caller-supplied idempotency key** (RFC-style) or via the natural `upsert` key. Probably both, with the idempotency key as the safety net.
