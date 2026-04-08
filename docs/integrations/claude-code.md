# Integration: Claude Code

[Claude Code](https://claude.com/claude-code) is Anthropic's official CLI for Claude. It runs **off-cluster** on a developer's laptop (or equivalent), connects to MCP servers declared in its configuration, and uses them as the tool surface for agent turns. For retrieval-hub, Claude Code is a *consumer* — one of several possible MCP clients — and the integration is narrow: make retrieval-hub's standalone Route reachable from a Claude Code session with appropriate credentials.

This is the simplest per-runtime integration we support. It has no platform dependencies on the cluster side (no LlamaStack, no Kagenti, no MLflow — just a reachable retrieval-hub-mcp Route) and no custom code on the Claude Code side (Claude Code's native MCP configuration is sufficient).

## What Claude Code is, briefly

- A CLI agent that runs locally on a developer's machine (macOS, Linux, Windows WSL).
- Connects to an Anthropic-hosted Claude model for the LLM itself.
- Discovers and invokes MCP servers declared in its MCP configuration file.
- Operates primarily against the local filesystem and any MCP servers the user has configured.
- Typically used for coding workflows, but equally useful for agent prototyping and for retrieving from curated knowledge sources.

The integration with retrieval-hub is: **Claude Code is one MCP client among many**, reaching retrieval-hub-mcp over its standalone Route with a valid JWT, and using retrieval-hub's tools the same way it uses any other MCP server's tools.

## Deployment topology

Claude Code is off-cluster. It has no awareness of Kagenti or LlamaStack. The relevant [`../mcp-server.md`](../mcp-server.md) deployment topology is **#1: Standalone Route**:

```
Claude Code (developer laptop) → retrieval-hub-mcp Route → retrieval-hub-mcp pod
```

retrieval-hub-mcp must have a publicly-reachable Route (or at least reachable from the developer's network — VPN, bastion host, port-forward during development, etc.). The Route does not depend on any in-cluster integration.

## Configuring Claude Code to reach retrieval-hub

Claude Code reads its MCP server configuration from a JSON file. The location varies by installation; common paths:

- `~/.claude/mcp.json`
- `~/.config/claude-code/mcp.json`
- Per-project `.mcp.json` in the workspace root

The configuration shape for adding retrieval-hub:

```json
{
  "mcpServers": {
    "retrieval-hub": {
      "transport": "streamable-http",
      "url": "https://retrieval-hub-mcp.apps.cluster.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${RETRIEVAL_HUB_TOKEN}"
      }
    }
  }
}
```

Key points:

- **`transport: streamable-http`** — retrieval-hub-mcp serves streamable-http, not SSE. If Claude Code's version only supports SSE, the integration won't work until it's upgraded.
- **`url`** — the full path to the MCP endpoint on retrieval-hub-mcp's Route, including any path prefix (e.g., `/mcp`).
- **`headers.Authorization`** — Claude Code substitutes environment variables in the config at load time. The user exports `RETRIEVAL_HUB_TOKEN` in their shell before launching Claude Code.

## Authentication

Two realistic auth patterns:

**Pattern A: Personal token from retrieval-hub-auth (local backend)**

Suitable for dev clusters and for developers who have their own retrieval-hub-auth client credentials. The developer runs (one time, per session):

```bash
export RETRIEVAL_HUB_CLIENT_ID=<their-client-id>
export RETRIEVAL_HUB_CLIENT_SECRET=<their-client-secret>

# Fetch a token via the retrieval-hub CLI (or curl)
export RETRIEVAL_HUB_TOKEN=$(retrieval-hub auth token)
```

The retrieval-hub CLI (`cli.md`) exposes a helper command that hits `retrieval-hub-auth/token` with the client credentials and prints the access token. The developer then launches Claude Code and the `${RETRIEVAL_HUB_TOKEN}` substitution in `mcp.json` picks it up.

The token expires after ~15 minutes (per [`../auth.md`](../auth.md)). For long Claude Code sessions, the developer re-runs the token fetch and restarts Claude Code. For a better experience, the CLI can drop the token into a file at a well-known path and the user can set up a shell function that refreshes it on demand.

**Pattern B: Token from an external IdP (Keycloak, corporate SSO)**

For production clusters where retrieval-hub-auth runs in `external_jwt_validator` mode against Keycloak, the developer obtains a JWT from Keycloak directly (via `kcadm.sh`, the Keycloak web UI, a developer-issued device-code flow, or a corporate SSO integration) and exports it into `RETRIEVAL_HUB_TOKEN`. The configuration in `mcp.json` is the same; the token source differs.

This pattern is necessary when retrieval-hub does not issue its own tokens on the cluster — which is the production happy path in Kagenti deploys (see [`kagenti.md`](kagenti.md)). Claude Code is still the same off-cluster consumer; it just needs a valid JWT from whatever issuer the cluster trusts.

In both patterns, **Claude Code never stores the credential long-term**; the token lives only in the shell environment, and the developer re-fetches it when it expires. The retrieval-hub SDK's transparent token refresh is not available to Claude Code because Claude Code uses its own MCP client, not the SDK.

## Sample agent system prompts

Claude Code agents are typically given a system prompt that tells them what tools exist and how to use them. For an agent that should use retrieval-hub sources, the system prompt follows the catalog's `sample_prompts` field conventions (per [`../catalog.md`](../catalog.md)).

A minimal example for querying the Red Hat product docs source:

```
You have access to retrieval-hub's Red Hat Product Documentation source
through the `retrieval-hub` MCP server. When answering questions about
Red Hat products (OpenShift, RHEL, Ansible, OpenShift AI), use the
retrieval tools to fetch relevant documentation before answering.

Tool usage:
- To find documentation for a specific topic, call the query tool with
  source="rh-product-docs" and your query text.
- Cite the source URL and section for every answer, as returned by the
  tool's lineage fields.
- If the rewriter is enabled on the source, prefer the query_with_rewrite
  variant — it will produce clinical/canonical reformulations for better
  recall.
```

More specific system prompts for specific sources live on the source card (catalog's `sample_prompts` field) and can be copy-pasted into Claude Code agent configuration. The `retrieval-hub source mcp-config <slug>` CLI command produces both the `mcp.json` snippet and a suggested system prompt for the source in one shot.

## Testing the integration

A quick end-to-end test loop for a developer verifying retrieval-hub is reachable from Claude Code:

1. Configure `mcp.json` as above with the retrieval-hub Route and a valid token.
2. Launch Claude Code in any project.
3. Run `/mcp` in Claude Code's interactive prompt to list configured MCP servers. `retrieval-hub` should appear as connected.
4. Ask Claude Code to use the retrieval-hub tools: *"List the retrieval-hub sources I have access to."*
5. Claude Code should invoke `retrieval_hub_list_sources` (or whatever the final tool name is from `/plan-tools`) and return the results.
6. Test a query: *"Use retrieval-hub to find Red Hat OpenShift Pipelines documentation about trigger templates."*

If the integration is broken, the failure modes are:

- **Connection refused** — Route unreachable from the developer's network; check VPN/network.
- **401 Unauthorized** — token expired or missing; re-fetch and re-launch.
- **403 Forbidden** — token valid but identity doesn't have the required scope; check that the client credentials grant `sources.list` / `sources.query` / etc.
- **Transport errors** — usually Claude Code trying to speak SSE when retrieval-hub expects streamable-http; confirm Claude Code version.

## What this integration does NOT do

- **No trace propagation.** Claude Code is not a LlamaStack agent, and it does not propagate W3C Trace Context to retrieval-hub. Spans emitted by retrieval-hub on calls from Claude Code will land in the cluster's OTel backend with their own trace IDs, not joined to anything on the Claude Code side.
- **No wristband filtering.** Claude Code reaches retrieval-hub-mcp via the Route, not via the Kagenti MCP Gateway. The tool-filter wristband mechanism (per [`kagenti.md`](kagenti.md)) does not apply. All authorization happens via the token's scopes and retrieval-hub's per-source access policy.
- **No multi-tenant namespace isolation.** Claude Code is off-cluster and has no Kubernetes namespace. The `rh_tenant` claim will be whatever the token's claim mapping produces (typically `"default"` for developer tokens, or a tenant assigned in Keycloak for corporate SSO flows).
- **No agent writes unless explicitly granted.** By default, Claude Code developer tokens should not have `sources.write`. If a developer specifically needs to test agent-write flows, they get a client credential with the scope and a source with `agent_write_policy.allowed: true`.

## Standalone fallback posture

This integration doc *is* the standalone-fallback posture — Claude Code runs against retrieval-hub's standalone Route with no platform dependencies. There is no "Claude Code is absent" case to design around; Claude Code is just one of potentially many off-cluster consumers.

Other off-cluster agent runtimes (custom scripts, LangGraph notebooks, Jupyter-hosted agents, third-party IDEs) follow the **same pattern**: standalone Route, token via env var or auth service, MCP client configured with the Route URL. If and when we need a dedicated doc for another runtime (e.g., `integrations/langgraph.md`), it will closely mirror this one.

## What's Decided

- **Claude Code connects via the standalone Route**, not via LlamaStack or Kagenti.
- **Transport is streamable-http**, same as every other MCP client of retrieval-hub.
- **Auth is a JWT in the `Authorization` header**, obtained via whichever retrieval-hub-auth backend the cluster is running (typically `local` for dev clusters, `external_jwt_validator` for production clusters).
- **Tokens are short-lived** and the developer re-fetches as needed. No long-term credential storage in Claude Code's configuration.
- **The retrieval-hub CLI (`cli.md`) includes a helper** (`retrieval-hub auth token`) for fetching tokens that Claude Code can consume via env var substitution.
- **`retrieval-hub source mcp-config <slug>`** produces a ready-to-paste `mcp.json` snippet and a suggested system prompt for any source.
- **No trace propagation, no wristband filtering, no namespace tenancy.** Claude Code gets what the standalone Route gives it, nothing more.

## What's Open

- **Claude Code's MCP config file path** on newer versions. The doc above lists common locations; confirm against the Claude Code version the developer is running.
- **Whether we ship a `claude code` subcommand in the retrieval-hub CLI** that writes the `mcp.json` snippet to the right location automatically. Probably yes, as quality-of-life; low priority.
- **Whether to support token-file-based auth** (retrieval-hub CLI writes a token to `~/.retrieval-hub/token` on a schedule, Claude Code reads it from there) as an alternative to env var substitution. Probably yes for long Claude Code sessions where repeated token fetch is annoying.
- **Off-cluster rate limiting.** The Route is open to any MCP client that has a valid token. If this becomes abuse-prone, we add rate limiting at retrieval-hub-mcp (round 2) or at the Route level (an operational concern per cluster).
