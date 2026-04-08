# MCP Tool Planning Notes

This document captures **input constraints and guidance for the eventual `/plan-tools` workflow** that will design retrieval-hub's MCP tool inventory. It is not a tool specification — tool design happens via the prescriptive `/plan-tools → /create-tools → /exercise-tools → /write-system-prompt → /update-docs → /deploy-mcp` workflow per [`mcp-server.md`](mcp-server.md). This file is the place where decisions and considerations *from outside that workflow* are recorded so they're picked up when the workflow runs.

When `/plan-tools` is run for the first time, this document should be read first.

## Why this document exists separately

`mcp-server.md` describes the MCP server component, the conventions every tool will follow, and the read/write boundary. It does **not** specify tools, by design. But several decisions made in other docs — particularly the Kagenti integration, the agent-write story in the catalog, and the eval execution delegation to LlamaStack — have implications for *how* tools should be designed when the time comes. Burying those implications inside the other docs would mean they get lost when `/plan-tools` runs months from now. This file exists so they don't.

The content is intentionally short. Each entry is a constraint or a recommendation, not a full design.

## Constraints from the Kagenti integration

### The tool-filter wristband makes a case for separating writes by mode

**Context.** [`integrations/kagenti.md`](integrations/kagenti.md) describes the Kagenti MCP Gateway's tool-filter wristband: an external authz component decides which tools an agent can see, signs a JWT wristband listing them, and the gateway filters tool discovery responses based on the wristband. Tools are gated **per tool name**, not per parameter value.

**Implication.** If retrieval-hub exposes a single `write` tool with a `mode` parameter (`append` / `upsert` / `annotate`), then an agent either has wristband authorization for the whole `write` tool or none of it. Granting an agent the ability to `append` automatically grants `upsert` and `annotate` from the wristband layer's perspective. retrieval-hub's per-source `agent_write_policy.write_modes` would still gate the modes server-side, but the *gateway* gate would be all-or-nothing.

**Recommendation for `/plan-tools`.** Strongly consider designing **three separate tools** — `append`, `upsert`, `annotate` — rather than one `write` tool with a `mode` parameter. This gives the wristband layer the granularity it needs to gate write modes independently. Defense in depth: gateway gates tool classes, retrieval-hub gates per-source. The same pattern could apply to read tools if there's a meaningful read-mode distinction (e.g., `query` vs. `query_with_rewrite`), though that's less load-bearing because reads are less dangerous than writes.

The trade-off is a slightly larger tool surface. Three tools where one would do. Worth it for the gateway-layer gating.

### Tool naming will be prefixed by Kagenti

**Context.** [`integrations/kagenti.md`](integrations/kagenti.md) notes that the Kagenti MCP Gateway applies a tool prefix (`retrieval_hub_`) to every tool name when exposing them through the gateway's aggregated tool discovery. retrieval-hub-mcp registers raw tool names (e.g., `query`); agents see prefixed names (e.g., `retrieval_hub_query`).

**Recommendation for `/plan-tools`.** Design tool names that will read well after the prefix is applied. `retrieval_hub_query` is fine. `retrieval_hub_search_sources` is also fine. `retrieval_hub_retrieve_hub_sources` is bad because it duplicates "hub" — avoid baking "hub" into individual tool names. Lean toward verb-noun: `retrieval_hub_list_sources`, `retrieval_hub_get_source`, `retrieval_hub_query`, `retrieval_hub_rewrite`, `retrieval_hub_append`, etc.

### LlamaStack connector tool naming

**Context.** [`integrations/llamastack.md`](integrations/llamastack.md) describes registration via LlamaStack `/v1/connectors`. LlamaStack also applies a prefix or namespace to connector-provided tools, the exact form of which depends on the LlamaStack version on the cluster.

**Recommendation for `/plan-tools`.** Same advice: pick names that read well under either Kagenti's prefix or LlamaStack's connector prefix. Avoid names that depend on the prefix for disambiguation (e.g., a tool literally called `query` is fine because `retrieval_hub_query` and `connector_X_query` are clearly distinct after prefixing; a tool called `do_it` is bad regardless).

## Constraints from the catalog and agent-write design

### Tools must enforce per-source `agent_write_policy` server-side

**Context.** [`catalog.md`](catalog.md) defines `agent_write_policy` as a per-source field controlling whether agents can write to the source, which write modes are allowed, which identity groups are allowed, and what validation applies. The default is `allowed: false`.

**Recommendation for `/plan-tools`.** Every write tool must, on every call:

1. Resolve the caller identity from the validated JWT.
2. Load the source's `agent_write_policy`.
3. Check `allowed == true`.
4. Check the requested write mode is in `write_modes`.
5. Check the caller's `rh_identity_groups` intersect `allowed_groups` (or that `allowed_groups` is empty).
6. Run the configured `write_validation` against the payload.
7. Only then dispatch to the source adapter for the actual write.

The check is not optional and not configurable — it lives in the core library, called by every write tool the same way. Read tools have the analogous check against `source.access`.

This is structurally identical to the round-1 catalog policy lookup. The point of restating it here is that *write tools cannot skip it*, even when the gateway wristband has already authorized the tool class. Both gates fire.

### Tools must return lineage on every result

**Context.** [`mcp-server.md`](mcp-server.md) commits to recipe-version-aware result items. Every result returned by a retrieval tool carries the `physical_index_id` and `recipe_version` it came from. [`integrations/mlflow.md`](integrations/mlflow.md) extends this for the rewriter: every rewrite result also carries the `shared_template_version` (an MLflow prompt version when present) and the `metadata_version`.

**Recommendation for `/plan-tools`.** Define a shared `Lineage` type that every result item carries. Specifically:

```yaml
lineage:
  source_id: src_01HXY...
  physical_index_id: pidx_01HXZ...
  recipe_version: 3
  # for rewrite results:
  shared_template_version: 7
  metadata_version: 4
  # for any result:
  request_id: req_01HXY...
  served_at: 2026-04-08T12:34:56Z
```

Tools can extend this with tool-specific fields, but the core lineage shape is shared. Audit and analytics depend on it being consistent across tools.

### Result items from graph-family sources carry relationships

**Context.** [`catalog.md`](catalog.md) describes the `graph_traverse_from_seed` retrieval pattern, where a graph source's adapter does vector-find-entry then graph-crawl and returns chunks **and** relationships in one normalized response.

**Recommendation for `/plan-tools`.** The result item shape returned by retrieval tools must support an optional `relationships` field — an array of `(from, to, relationship_type, weight)` tuples — alongside the standard `text`, `score`, `metadata`, and `lineage` fields. Agents that don't want relationships ignore the field; agents that work with graph sources consume it.

This is the design call that lets one tool surface serve all source families without becoming a god API.

## Constraints from the eval delegation to LlamaStack

### Eval execution does not require new tools

**Context.** [`integrations/llamastack.md`](integrations/llamastack.md) describes eval execution delegation to LlamaStack. LlamaStack's `/v1/eval` invokes retrieval through the same MCP tools agents use; there is no separate "eval mode."

**Recommendation for `/plan-tools`.** **Do not design eval-specific tools.** LlamaStack-driven evals call the same retrieval tools any agent calls. The only eval-specific machinery is on the catalog/orchestration side, not the MCP tool side. This keeps the MCP tool surface narrow and means eval results are predictive of production retrieval behavior because they go through identical code paths.

### Eval triggering is a catalog action, not an MCP tool

**Context.** [`evaluation.md`](evaluation.md) describes eval runs as catalog operations triggered from the UI or CLI by source owners.

**Recommendation for `/plan-tools`.** **Do not expose eval-trigger tools through MCP for agents.** Triggering an eval run is a *human action* (or a system-driven scheduler action), not an agent action. It belongs alongside catalog mutation in the humans-only path. The MCP server has no `start_eval` tool.

## Constraints from the rewriter design

### Query rewriting is its own tool

**Context.** [`query-rewriter.md`](query-rewriter.md) describes the rewriter as a service inside the core library, exposed to agents through MCP.

**Recommendation for `/plan-tools`.** Design **`rewrite` as a distinct tool** (or whatever the prefix-applied name will be), not as an option on a query tool. Reasons:

1. Agents commonly want to do rewriting separately from retrieval — get the rewrites, decide what to do with them (use one, union all, log them for debugging, rerank them), then call retrieval. Bundling rewrites into a query tool prevents that pattern.
2. The convenience composition (rewrite + retrieve + dedupe in one call) can be a separate tool if `/plan-tools` decides it's worth it. The SDK already provides `query_with_rewrite` as a client-side composition; whether that needs a server-side tool counterpart is a `plan-tools` call.
3. Rewriting and retrieval have different cost profiles, different latency profiles, and different failure modes. Keeping them as separate tools keeps the error model clean.

### Rewrite tool must surface lineage

Already covered above — the rewrite tool's result includes `shared_template_version`, `metadata_version`, and the LLM that produced the rewrites.

## Constraints from the SDK and CLI design

### Tool inputs should be ergonomic for both agents and humans

**Context.** Both [`sdk.md`](sdk.md) and [`cli.md`](cli.md) describe consumer surfaces that wrap the MCP tools. SDK methods and CLI commands are 1:1 with MCP tools where possible.

**Recommendation for `/plan-tools`.** Tool input shapes should be designed so the SDK wrapper is mechanical (no clever parameter remapping in the SDK) and so the CLI can expose them as flags without major restructuring. Specifically:

- Tool parameters should be **named**, not positional.
- Optional parameters with defaults should be... optional, with defaults. The SDK defaults match the tool defaults; the CLI flags default to the same values.
- Tool parameter types should be JSON-friendly primitives, lists of primitives, or named typed objects. Avoid deeply nested input shapes.

### Streaming for long operations

**Context.** Both [`mcp-server.md`](mcp-server.md) and [`sdk.md`](sdk.md) commit to streamable-http for the transport and async iterator interfaces in the SDK for streaming operations.

**Recommendation for `/plan-tools`.** Tools that can return more than ~50 items, or that take longer than ~5 seconds, should be designed with a streaming variant. The convention is non-streaming as the default with a `_stream` suffix variant. Examples that probably need streaming variants: large `query` results, multi-source query, ingestion run progress events, eval run progress events.

## Reserved error codes

The error code set is reserved upfront in [`mcp-server.md`](mcp-server.md) so `/create-tools` doesn't invent ad-hoc error shapes per tool. The full set as of round 2:

**Read-path codes:**
- `source_not_found`, `source_retired`, `source_not_published`
- `access_denied`
- `pattern_not_supported`, `pattern_parameter_invalid`
- `rewrite_disabled`
- `backend_unavailable`
- `recipe_version_mismatch`

**Write-path codes:**
- `write_not_allowed` — source's `agent_write_policy.allowed = false`
- `write_mode_not_allowed` — source allows writes but not this mode
- `write_validation_failed` — content failed the source's validation schema
- `write_scope_required` — caller missing `sources.write` scope
- `write_provenance_required`
- `write_idempotency_conflict` — upsert key collision

**Cross-cutting codes:**
- `auth_invalid`, `auth_expired`
- `rate_limited`
- `internal_error`

**Recommendation for `/plan-tools`.** New tools must use codes from this set. Tools that need a code that doesn't exist add it to this list (and to `mcp-server.md`) before using it; codes are not invented inline.

## Sequencing recommendation for `/plan-tools` itself

When `/plan-tools` is eventually run, the recommended order to design tools in:

1. **Discovery and metadata tools first**: `list_sources`, `get_source`, `get_source_recipe`, `get_source_sample_prompts`. These are the lowest-risk and the foundation everything else builds on.
2. **Read-only retrieval next**: `query` (with the family-aware adapter dispatch hidden behind it). One tool that handles vector search, graph traversal, and structured queries via the source's declared retrieval pattern.
3. **Rewrite as its own tool**: `rewrite`. Independent of `query` so callers can compose them.
4. **Optional convenience composition**: `query_with_rewrite` if `/plan-tools` decides it's worth a server-side tool (vs. SDK-side composition).
5. **Write tools last, separately**: `append`, `upsert`, `annotate`. Three tools (per the wristband consideration above) with the per-source policy enforcement that's not optional.
6. **Cross-source / multi-source variants** (if needed) only after the single-source surface is real.

The goal is to ship the read surface first, prove it works against a real source (Red Hat product docs), and only then add write capability and rewriting. This matches the build order in [`SYSTEMS.md`](SYSTEMS.md).

## What this document is not

- **Not a tool specification.** Specs come from `/create-tools`.
- **Not a security policy.** Security is in [`auth.md`](auth.md), [`catalog.md`](catalog.md), and [`integrations/kagenti.md`](integrations/kagenti.md).
- **Not a roadmap.** Build order is in [`SYSTEMS.md`](SYSTEMS.md).
- **Not a guarantee.** `/plan-tools` may overrule any of these recommendations if reality shows them wrong. The recommendations are starting positions, not commitments.

When `/plan-tools` runs, this document should be the first thing it reads, and if anything in it is wrong by then, fix this document as part of the same workflow.
