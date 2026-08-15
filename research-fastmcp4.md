# Research: FastMCP 4 and MCP 2026-07-28 Stateless Specification

**Date:** 2026-08-14
**Status:** FastMCP 4.0.0b1 (beta) — pin exact version, expect sharp edges

## Summary

FastMCP 4 implements the MCP 2026-07-28 stateless specification while maintaining backward compatibility with handshake-era clients. The protocol eliminated sessions, sticky routing, and the initialize handshake — any request can now land on any server replica behind a plain round-robin load balancer. For RetrievalHub's MCP server, this is a significant simplification: the server becomes a standard stateless HTTP service that scales horizontally on OpenShift without session affinity. Most FastMCP 3 patterns upgrade unchanged; the main migration cost is replacing `httpx` with `httpx2` and dropping server-initiated sampling/roots.

**Recommendation:** Build on FastMCP 4.0.0b1. The stateless model aligns perfectly with a retrieval server (every query is independent), and the new features (cacheable tool lists, structured output, response caching) directly benefit a catalog/retrieval use case. Pin the exact beta version and track releases.

## MCP 2026-07-28 Specification Changes

The [2026-07-28 specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/) is the largest revision since launch. Key changes:

### Stateless Core

- **Initialize handshake removed.** No more `initialize`/`initialized` exchange. Protocol version and client capabilities ride in `_meta` on every request.
- **`Mcp-Session-Id` header eliminated.** No protocol-level sessions. Any replica can serve any request.
- **SSE stream resumability removed.** Broken streams require a fresh request with a new request ID.

### New Required HTTP Headers

Every Streamable HTTP request now carries:
- `Mcp-Method` (e.g., `tools/call`)
- `Mcp-Name` (e.g., `retrieve`)

This enables gateways, rate limiters, and WAFs to route and authorize per-tool without parsing JSON-RPC bodies. For RetrievalHub, this means per-tool rate limiting at the edge is free.

### Server Discovery

New `server/discover` RPC: servers MUST implement it. Clients optionally call it to learn capabilities upfront. Replaces the handshake's capability exchange.

### Multi Round-Trip Requests (MRTR)

Replaces bidirectional streaming for mid-call interactions. Server returns `resultType: "input_required"` with an opaque request-state token; client gathers answers and resubmits. Relevant for RetrievalHub's future `refine` tool (iterative query refinement).

### Cacheable List Results

`tools/list`, `prompts/list`, `resources/list`, and `resources/read` responses now carry:
- `ttlMs` — time-to-live in milliseconds
- `cacheScope` — caching strategy

For RetrievalHub: the source catalog changes infrequently, so `list_sources` and `describe_source` can advertise long TTLs, reducing round trips for agents.

### Application-Level State

The protocol is stateless, but applications can still carry state across calls by minting explicit handles (a `search_id`, `session_token`) from a tool and having the model pass it back. This is the pattern for RetrievalHub's `refine` tool.

### Auth Hardening

- Dynamic Client Registration deprecated in favor of Client ID Metadata Documents (CIMD)
- RFC 9207 issuer validation required before code redemption
- `application_type` parameter during client registration

Industry support: AWS (Bedrock AgentCore), Anthropic, Cloudflare (Agents SDK) all support 2026-07-28 from day zero.

## FastMCP 4.0.0b1 — What's New

Released 2026-07-28. Repository moved from `jlowin/fastmcp` to [`PrefectHQ/fastmcp`](https://github.com/PrefectHQ/fastmcp/releases). Full engineering support from Prefect team.

### Protocol Negotiation

One FastMCP server serves both protocol eras. Modern clients get stateless; legacy clients get the handshake flow.

```python
from fastmcp import Client

# Auto-negotiates optimal protocol
client = Client("https://example.com/mcp")

# Forces legacy handshake protocol
legacy = Client("https://example.com/mcp", mode="legacy")
```

### Stateless Scalability

Each modern request carries everything needed to answer it. No session store, no sticky sessions, no shared state between replicas. Standard round-robin load balancing works.

### Extensions Framework

`FastMCP.add_extension()` — plugins can advertise capabilities, add request methods, intercept tool calls, and manage lifespan behavior.

### Background Tasks

Optional `fastmcp-tasks` package implements the `io.modelcontextprotocol/tasks` extension:

```python
from fastmcp import FastMCP
from fastmcp_tasks import TasksExtension

mcp = FastMCP("MyServer")
mcp.add_extension(TasksExtension())

@mcp.tool(task=True)
async def slow_computation(duration: int) -> str:
    await asyncio.sleep(duration)
    return f"Completed in {duration} seconds"
```

Client polls automatically. Redis/Valkey backends for durability. Potentially useful for RetrievalHub bulk ingestion operations exposed via MCP.

### Multi-Round-Trip Tools

Tools can request follow-up input across stateless requests:

```python
@mcp.tool
async def book_flight(ctx: Context) -> str | InputRequiredResult:
    answers = ctx.input_responses
    if answers is None:
        return InputRequiredResult(
            result_type="input_required",
            input_requests={
                "destination": ElicitRequest(
                    method="elicitation/create",
                    params=ElicitRequestFormParams(
                        message="Where would you like to fly?",
                        requested_schema={...}
                    ),
                )
            },
        )
    return f"Booked a flight to {answers['destination'].content['destination']}."
```

### Session State (UserSession)

User-bound session storage without protocol-level sessions:

```python
from fastmcp.server.sessions import UserSession

@mcp.tool
async def remember(fact: str, session: UserSession) -> str:
    facts = await session.get("facts", default=[])
    facts.append(fact)
    await session.set("facts", facts)
    return f"Remembered {len(facts)} facts."
```

Requires authentication binding. Could power RetrievalHub's per-user query history or preference tracking.

### Enterprise Auth

- Identity assertion for internal agents (no OAuth redirect)
- Machine-to-machine via client-credentials grant
- Hugging Face and Auth0 providers built-in

### Response Caching

```python
mcp = FastMCP("Weather", cache_ttl=300, cache_scope="public")
```

`KeyValueResponseCacheStore` for distributed caching via Redis. Good fit for RetrievalHub's catalog metadata.

### Structured Output

Automatic structured output for dict/dataclass/Pydantic returns:

```python
@mcp.tool
def get_user_data(user_id: str) -> dict:
    return {"name": "Alice", "age": 30, "active": True}
```

Returns both `TextContent` and `structuredContent`. Directly benefits RetrievalHub's `retrieve` tool — agents get both human-readable chunks and structured metadata.

### Tool Annotations

```python
from mcp.types import ToolAnnotations

@mcp.tool(annotations=ToolAnnotations(
    title="Search Documents",
    readOnlyHint=True,
    openWorldHint=False,
))
def retrieve(query: str, source: str) -> list[dict]:
    ...
```

### Dependency Injection

Hide parameters from the LLM schema:

```python
from fastmcp.dependencies import Depends

@mcp.tool
def get_user_details(user_id: str = Depends(get_user_id)) -> str:
    return f"Details for {user_id}"
```

Useful for injecting database sessions, auth context, etc. into RetrievalHub tools without exposing them to the agent.

## Breaking Changes from FastMCP 3

### Removed APIs

| Removed | Replacement |
|---|---|
| `ctx.sample()` / `ctx.sample_step()` | Call LLM directly or use `InputRequiredResult` |
| `ctx.list_roots()` | Accept paths as arguments |
| `ctx.elicit()` on modern connections | Use guard pattern with `InputRequiredResult` |
| `FastMCP(sampling_handler=...)` | Removed entirely |
| `import_server(sub)` | `mount(sub)` — live composition |
| `mount(prefix="x")` | `mount(namespace="x")` |

### Required Changes

1. **Pydantic >= 2.12**, **FastAPI >= 0.133.0** (Starlette >= 1.0.1)
2. **`httpx` replaced by `httpx2`** — grep all `except httpx.` patterns
3. **`McpError` construction** — keyword args only: `raise McpError(code=-32000, message="...")`
4. **SDK v2 snake_case** — `inputSchema` becomes `input_schema` (compat shim warns, will be removed)
5. **`fastmcp.types` trimmed** — FastMCP-unique types only
6. **State methods now async** — `await ctx.set_state()`, `await ctx.get_state()`
7. **Background tasks** require `fastmcp-tasks` extra and explicit `TasksExtension()` registration

### camelCase Bridge

SDK v2 renamed all protocol fields to snake_case. FastMCP installs a compatibility shim that warns on old-style access. Disable with `fastmcp.settings.mcp_camelcase_compat = False` to find remaining migrations.

## Upgrade Checklist (from FastMCP 3)

1. Pin `pydantic>=2.12`; upgrade FastAPI to `>=0.133.0`
2. Replace `httpx` with `httpx2` everywhere (imports, clients, exception handlers)
3. Remove `ctx.sample()`, `ctx.list_roots()`, `FastMCP(sampling_handler=...)`
4. Migrate `ctx.elicit()` to guard pattern or keep clients on `mode="legacy"`
5. Fix `McpError` construction to use keyword arguments
6. Replace `import_server` with `mount`, `prefix` with `namespace`
7. Register `TasksExtension()` if using background tasks
8. Run tests with `mcp_camelcase_compat = False`

## Implications for RetrievalHub MCP Server

### Direct Benefits

1. **Horizontal scaling is trivial.** No session affinity needed. Deploy N replicas behind OpenShift's round-robin service routing. This was previously the hardest operational concern for MCP servers.

2. **Per-tool routing at the edge.** `Mcp-Method` and `Mcp-Name` headers enable OpenShift route-level rate limiting and authorization without parsing request bodies. Rate-limit `retrieve` separately from `list_sources`.

3. **Cacheable catalog.** `list_sources` and `describe_source` responses can carry long TTLs. Agents that connect frequently don't re-fetch the full catalog every time.

4. **Structured output for retrieval.** The `retrieve` tool can return both human-readable chunks (TextContent) and structured metadata (source, score, section path, provenance) as `structuredContent`. Agents get both.

5. **Dependency injection for internals.** Database sessions, embedding models, and auth context can be injected via `Depends()` without polluting the tool schema.

6. **Tool annotations.** Mark `retrieve`, `list_sources`, `describe_source` as `readOnlyHint=True`. Mark `write` as `destructiveHint=False, idempotentHint=True`.

### Design Patterns for Retrieval

Based on [community patterns](https://github.com/PrefectHQ/fastmcp/discussions/3087) for RAG-over-MCP:

- **Tools, not resources**, for retrieval. Resources are for static data; tools handle parameterized search.
- **Structured return types** using Pydantic models for type-safe retrieval results.
- **Vector search behind the tool** — the MCP server is the interface; internally it delegates to pgvector via the existing document adapter.

### Architecture Sketch

```python
from fastmcp import FastMCP, Context
from fastmcp.dependencies import Depends
from mcp.types import ToolAnnotations

mcp = FastMCP(
    "RetrievalHub",
    cache_ttl=3600,       # catalog metadata cached 1 hour
    cache_scope="public",
)

@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"catalog"},
)
async def list_sources(db=Depends(get_db)) -> list[SourceSummary]:
    """List all available data sources in the catalog."""
    ...

@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"catalog"},
)
async def describe_source(slug: str, db=Depends(get_db)) -> SourceDetail:
    """Get detailed metadata for a specific data source."""
    ...

@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    tags={"retrieval"},
    timeout=30.0,
)
async def retrieve(
    query: str,
    source: str,
    top_k: int = 5,
    db=Depends(get_db),
) -> list[RetrievalResult]:
    """Search a data source and return relevant passages with provenance."""
    ...
```

### Future Tool Mapping

| RetrievalHub Tool | MCP Pattern | Notes |
|---|---|---|
| `list_sources` | Cached, `readOnlyHint` | Long TTL, rarely changes |
| `describe_source` | Cached, `readOnlyHint` | Per-source TTL |
| `retrieve` | Core tool, structured output | Returns chunks + metadata |
| `refine` | Multi-Round-Trip (MRTR) | Iterative query refinement via request-state tokens |
| `write` | Background task | Long-running ingestion via `fastmcp-tasks` |
| `request_access` | Multi-Round-Trip or standard | Policy check + approval flow |

## RAG-over-MCP Ecosystem

The pattern is well-established in 2026. Notable implementations:

- [Neo4j GraphRAG MCP Server](https://neo4j.com/blog/developer/neo4j-graphrag-retrievers-as-mcp-server/) — graph + vector hybrid via FastMCP
- [knowledge-mcp](https://github.com/olafgeibig/knowledge-mcp) — hybrid BM25 + semantic + cross-encoder reranking
- [Astrophysical RAG MCP](https://arxiv.org/html/2607.03946) — domain-specific FAISS indexes via FastMCP
- [FastMCP RAG Discussion](https://github.com/PrefectHQ/fastmcp/discussions/3087) — canonical patterns from maintainers

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| FastMCP 4 is beta | Medium | Pin exact version, maintain upgrade tests |
| `httpx2` dependency may conflict | Low | Isolated venv, check transitive deps |
| MCP SDK v2 field renames | Low | FastMCP compat shim handles it, run with shim disabled in CI |
| Background tasks (fastmcp-tasks) maturity | Medium | Only needed for `write` tool, can defer |
| Auth provider changes | Low | Using local IdP for MVP, enterprise auth later |

## Sources

- [What's New in FastMCP 4](https://gofastmcp.com/getting-started/whats-new)
- [FastMCP Changelog](https://gofastmcp.com/changelog)
- [FastMCP Releases (GitHub)](https://github.com/PrefectHQ/fastmcp/releases)
- [FastMCP 3→4 Upgrade Guide](https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3)
- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools)
- [MCP 2026-07-28 Specification Blog Post](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP 2026-07-28 Changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [MCP Went Stateless (DEV Community)](https://dev.to/krlz/mcp-went-stateless-what-the-2026-07-28-spec-actually-changes-273k)
- [MCP Goes Stateless (InfoQ)](https://www.infoq.com/news/2026/08/mcp-stateless-gateway/)
- [MCP Goes Stateless (Arcade.dev)](https://www.arcade.dev/blog/mcp-going-stateless/)
- [Cloudflare MCP v2 Support](https://blog.cloudflare.com/mcp-v2/)
- [FastMCP RAG Integration Discussion](https://github.com/PrefectHQ/fastmcp/discussions/3087)
