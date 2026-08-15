# Research: FastMCP Server Mesh and GitHub Integration for RetrievalHub

**Date:** 2026-08-14

## Summary

FastMCP 4 has robust server composition via `mount()` + `create_proxy()`, supporting namespace-isolated proxying of remote MCP servers with tag-based tool filtering. However, for RetrievalHub's MVP, **extending the existing `retrieve` tool to include live file fetch** is the strongest option: it keeps the tool count at 3, avoids PAT management, and works for public repos using the GitHub REST API's unauthenticated endpoint (60 req/hr). FastMCP's proxy/mount pattern becomes the right tool when PAT management is solved and the full GitHub MCP server's read toolset is needed.

## Options Analyzed

| Option | Tool Count | PAT Required | Complexity | Best For |
|--------|-----------|-------------|-----------|---------|
| **A: Extend `retrieve`** | 3 (unchanged) | No (public repos) | Low | MVP |
| B: New `fetch_code_file` tool | 4 (+1) | No (public repos) | Low | If tool count flex OK |
| C: FastMCP proxy mount | 3+ (filtered) | Yes (server startup) | Medium | Production w/ OAuth |
| D: Separate servers | 3 (ours) + N (GitHub) | Yes | Low (our side) | Agent-managed |

## Recommendation: Option A for MVP, Option C for Production

### MVP (Option A): Extend `retrieve` with live file resolution

Add an optional `file_path` parameter to the existing `retrieve` tool. When provided (along with the source slug), skip vector search and return the live file content from GitHub's public REST API. The recipe records the GitHub `owner/repo` so the tool knows where to fetch.

```python
@mcp.tool
async def retrieve(
    query: str,
    source: str,
    top_k: int = 5,
    file_path: str | None = None,  # fetch this file instead of searching
    ref: str = "main",             # git ref for file fetch
) -> RetrievalResponse:
    if file_path:
        return await _fetch_live_file(source, file_path, ref, session)
    else:
        return await _vector_search(source, query, top_k, session)
```

**Why this works:**
- Tool count stays at 3 -- the `retrieve` tool is polymorphic
- No PAT needed: GitHub REST API allows unauthenticated reads of public repos
- 60 requests/hour is adequate for agent use (a few file fetches per conversation)
- The recipe's `source_url` or a new `github_repo` field provides `owner/repo`
- Backward compatible: existing vector-search behavior unchanged when `file_path` is absent

**The agent workflow becomes:**
1. `retrieve(source="retrieval-hub-code", query="how does ingestion work")` -- vector search
2. Agent sees results with `doc_url = "src/retrieval_hub/ingestion/register.py"`
3. `retrieve(source="retrieval-hub-code", file_path="src/retrieval_hub/ingestion/register.py")` -- live fetch
4. Agent gets current file content at HEAD

### Production evolution (Option C): FastMCP proxy mount

Once PAT/OAuth management is solved (perhaps via an OAuth flow in the UI), use FastMCP 4's server composition:

```python
from fastmcp.server import create_proxy

github_proxy = create_proxy(
    {"mcpServers": {"default": {
        "command": "github-mcp-server", 
        "args": ["--read-only", "--toolsets=repos"],
    }}},
    namespace="github",
)
mcp.mount(github_proxy)
mcp.enable(tags={"retrieval", "catalog"}, only=True)  # filter to our tools only
```

This gives access to the full GitHub read toolset (`get_file_contents`, `search_code`, `list_commits`, `get_repository_tree`) through the RetrievalHub server, with namespace prefixing to avoid collisions.

## Detailed Findings

### FastMCP 4 Server Composition

FastMCP 4 supports server composition through two mechanisms:

**`mount()`** -- combines FastMCP servers into a unified server:
```python
main = FastMCP("Main")
main.mount(child_server, namespace="child")
# child tools accessible as child_tool_name
```

**`create_proxy()`** -- bridges to remote or subprocess MCP servers:
```python
from fastmcp.server import create_proxy
proxy = create_proxy("http://remote-server:8080/mcp")
main.mount(proxy, namespace="remote")
```

Key capabilities:
- **Namespacing**: prevents tool collisions (`github_get_file_contents`)
- **Tag filtering**: `enable(tags={"production"}, only=True)` restricts exposed tools
- **Transport bridging**: stdio to HTTP and vice versa
- **Live connection**: adding tools to child servers after mounting makes them immediately accessible
- **Proxy caching**: 300s TTL on component lists reduces overhead

Performance note: proxying adds latency (~300-400ms per tool list call over HTTP). Component list caching mitigates this for repeated calls.

### GitHub MCP Server

The [official GitHub MCP server](https://github.com/github/github-mcp-server) exposes 70+ tools across repos, issues, PRs, actions, code scanning, discussions, projects, and more.

**Read-only tools relevant to code retrieval:**
- `get_file_contents` -- file or directory contents at a ref
- `search_code` -- GitHub code search with qualifiers
- `get_repository_tree` -- recursive file listing
- `list_commits` -- commit history
- `get_commit` -- single commit details
- `list_branches` / `list_tags` -- ref listing

**Read-only mode**: `--read-only` flag or `GITHUB_READ_ONLY=1` filters out all write tools. Known bug: read-only filtering doesn't work in HTTP mode as of v0.31.0.

**Authentication**: The server requires `GITHUB_PERSONAL_ACCESS_TOKEN` to start, but read-only tools that work on public repos are "always visible, even if your token doesn't have these scopes." The practical question is whether the server starts at all without a token -- the docs don't explicitly confirm this.

### GitHub REST API Unauthenticated Access

The GitHub REST API allows unauthenticated reads of public repos:
- **Rate limit**: 60 requests/hour per IP ([updated May 2025](https://github.blog/changelog/2025-05-08-updated-rate-limits-for-unauthenticated-requests/))
- **Relevant endpoints**:
  - `GET /repos/{owner}/{repo}/contents/{path}?ref={ref}` -- file contents (base64-encoded, 1MB limit)
  - `GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1` -- repo tree
  - `GET /repos/{owner}/{repo}/commits?sha={branch}&per_page=5` -- recent commits
- **No token needed**: just raw HTTP requests with `Accept: application/vnd.github.v3+json`

For RetrievalHub's use case (fetching a few files per agent conversation), 60 req/hr is sufficient.

### Tool Count Stability as Families Grow

The current 3-tool design (`list_sources`, `describe_source`, `retrieve`) is already polymorphic: `retrieve` dispatches to different adapters based on `Source.family`. Adding new families (graph, tabular, SQL) doesn't add tools -- each family implements the `SourceAdapter` interface and the dispatch handles it transparently.

For the `file_path` extension, the same polymorphism applies: only code-family sources support live file fetch. Other families ignore the parameter or return an error.

FastMCP 4's tag system provides additional control if tools do need to proliferate in the future. Tools can be tagged and selectively exposed based on deployment context:

```python
@mcp.tool(tags={"retrieval"})
async def retrieve(...): ...

@mcp.tool(tags={"admin"})
async def reindex_source(...): ...

# Production: only retrieval tools
mcp.enable(tags={"retrieval"}, only=True)
```

## Sources

- [FastMCP Documentation - Server Composition](https://gofastmcp.com/servers/composition)
- [FastMCP Documentation - Proxy Servers](https://gofastmcp.com/servers/proxy)
- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [GitHub MCP Server - Scope Filtering](https://github.com/github/github-mcp-server/blob/main/docs/scope-filtering.md)
- [GitHub MCP Server - Server Configuration](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)
- [GitHub REST API Rate Limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [Updated Rate Limits for Unauthenticated Requests (May 2025)](https://github.blog/changelog/2025-05-08-updated-rate-limits-for-unauthenticated-requests/)
