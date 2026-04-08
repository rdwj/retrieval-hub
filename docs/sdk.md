# SDK

The SDK is the Python typed client for retrieval-hub. Most consumers — application code, agent runtimes, scripts, the CLI — should use the SDK rather than calling MCP directly. It is a thin wrapper around the MCP surface that handles the boring things (token caching, retries, error translation, sync/async ergonomics) so callers can focus on what they're actually trying to do.

This document describes the SDK's shape: where it lives, how it's organized, what it exposes, how it handles auth, how errors and streaming work, and what the common patterns look like.

## Where it lives

`sdk/` is a peer top-level component in the repo. Per the platform pattern, it has its own `pyproject.toml`, its own tests, its own version, and is published to PyPI as `retrieval-hub`. It does **not** import the core library — it talks to the running system over MCP, exactly like any other consumer. This is what keeps the deployable boundaries honest: if the SDK started importing from `src/retrieval_hub/`, it would be a sign that something has drifted in the architecture.

The SDK is what most consumers actually touch. It should feel pleasant. Specifically:

- Default configuration via env vars, no boilerplate to get started.
- Both async and sync entry points, named consistently (`foo` is async, `foo_sync` is sync), per the memory-hub convention.
- Clear typed return values, not raw JSON dicts.
- Clear typed error classes, not stringly-typed exceptions.
- Streaming is a first-class affordance for the operations that need it.
- Token handling is invisible by default and overridable when necessary.

## Installation and configuration

```
pip install retrieval-hub
```

Or with `uv`, `pipx`, etc. The package name is `retrieval-hub` on PyPI; the import name is `retrieval_hub`.

Default configuration is by environment variable so the common case is zero code:

| Variable | Purpose |
|---|---|
| `RETRIEVAL_HUB_URL` | Base URL of the MCP server (e.g. `https://retrieval-hub-mcp.example.com`) |
| `RETRIEVAL_HUB_AUTH_URL` | Base URL of the auth service. Optional in `external_jwt_validator` mode. |
| `RETRIEVAL_HUB_CLIENT_ID` | OAuth client id (when retrieval-hub issues tokens) |
| `RETRIEVAL_HUB_CLIENT_SECRET` | OAuth client secret (when retrieval-hub issues tokens) |
| `RETRIEVAL_HUB_TOKEN` | Pre-existing JWT (when consuming an externally-issued token; takes precedence over client credentials) |
| `RETRIEVAL_HUB_TENANT` | Tenant id (defaults to `default`) |
| `RETRIEVAL_HUB_TIMEOUT_SECONDS` | Per-call default timeout (defaults to 30) |
| `RETRIEVAL_HUB_LOG_LEVEL` | SDK log level |

Two of these correspond to the two auth modes described in [`auth.md`](auth.md):

- **Issued mode** — set `RETRIEVAL_HUB_AUTH_URL` + `RETRIEVAL_HUB_CLIENT_ID` + `RETRIEVAL_HUB_CLIENT_SECRET`. The SDK will hit the auth service's `/token` endpoint and cache the JWT. This is the dev / `local` / `openshift_oauth` / `oidc_external` path.
- **Inherited mode** — set `RETRIEVAL_HUB_TOKEN` to a JWT issued by the customer's external IdP. The SDK uses it directly without contacting an auth service. This is the `external_jwt_validator` path. The caller is responsible for refreshing it before it expires (the SDK warns when the token has less than 60 seconds left).

If both are set, `RETRIEVAL_HUB_TOKEN` wins.

Programmatic configuration (overriding env vars) is also supported:

```python
from retrieval_hub import RetrievalHubClient

client = RetrievalHubClient(
    url="https://retrieval-hub-mcp.example.com",
    auth_url="https://retrieval-hub-auth.example.com",
    client_id="agent-research-assistant",
    client_secret="...",
    timeout_seconds=60,
)
```

## Client structure

The SDK is organized into one top-level client (`RetrievalHubClient`) with several **domain sub-clients** accessed as attributes. This keeps the import surface flat while letting the API stay readable.

```python
from retrieval_hub import RetrievalHubClient

client = RetrievalHubClient()

# Domain sub-clients:
client.sources        # SourcesClient — list, get, browse, filter
client.retrieval      # RetrievalClient — query against a source
client.rewrite        # RewriteClient — invoke the per-source rewriter
client.writes         # WritesClient — append/upsert/annotate (when allowed)
client.ingestion      # IngestionClient — trigger ingestion runs, check status (CLI / source-owner path)
client.evals          # EvalsClient — read eval results from cards (round 2 path)
client.admin          # AdminClient — catalog mutation (humans-only, requires admin.write)
```

Each sub-client exposes a consistent set of methods. Async is the default; sync versions are provided with the `_sync` suffix.

Catalog mutation through `client.admin` is the **humans-only** path — the SDK doesn't reject the calls (it can't tell who you are), but the auth service will reject them if the caller's identity isn't allowed `admin.write`. In practice the only callers using `client.admin` are the BFF behind the UI and source owners running CLI commands as themselves.

## The common operations

A handful of operations cover 90% of consumer code. The shapes below are illustrative — the exact tool names and parameters will be set when `/plan-tools` runs (per [`mcp-server.md`](mcp-server.md)) — but the SDK's surface follows them closely.

### Browse the catalog

```python
sources = await client.sources.list(
    family="document",
    has_rewriter=True,
    visibility="public",
)
for s in sources:
    print(s.slug, s.name, s.family, s.eval_summary)
```

`list` returns a typed `SourceCard` collection with the fields a browse view needs. Use `get` for the full record:

```python
src = await client.sources.get("va-clinical-guidelines")
print(src.recipe.embedding.model)
print(src.rewriter_metadata.vocabulary_mappings)
print(src.evals)
```

### Query a source

```python
result = await client.retrieval.query(
    source="va-clinical-guidelines",
    query="what should I do for someone with high blood sugar after a meal",
    top_k=10,
)
for hit in result.items:
    print(hit.score, hit.text[:200])
    print("  from:", hit.physical_index_id, "recipe v", hit.recipe_version)
```

The pattern dispatch is invisible. If the source is a `graph` family with `default_pattern: graph_traverse_from_seed`, the SDK still calls a single `query` method and the result will include `relationships` alongside `items`. The caller can ignore relationships if they only want chunk text.

To pick a non-default pattern explicitly:

```python
result = await client.retrieval.query(
    source="va-clinical-guidelines",
    query="...",
    pattern="vector_with_filters",
    pattern_parameters={"filter": {"document_type": "guideline"}},
)
```

### Rewrite a query

```python
rewrites = await client.rewrite.suggest(
    source="va-clinical-guidelines",
    raw_query="what should I do for someone with high blood sugar after a meal",
    max_rewrites=5,
)
for r in rewrites.queries:
    print(r.intent, "->", r.text)
```

The rewriter is exposed as its own sub-client because callers commonly want to do rewriting *separately* from retrieval — they get the rewrites, decide what to do with them (use one, union all, rerank, log them for debugging), and then call retrieval. There is also a convenience method that does both in one call:

```python
result = await client.retrieval.query_with_rewrite(
    source="va-clinical-guidelines",
    raw_query="...",
    top_k=10,
    rewrite_strategy="union",   # union | best_only | per_intent
)
```

`query_with_rewrite` is a thin wrapper that calls `rewrite.suggest` then `retrieval.query` once per rewrite then merges/dedupes/reranks per the strategy. It exists because the union-then-merge pattern is so common that making callers write it themselves every time is silly.

### Write to a source

```python
result = await client.writes.append(
    source="clinical-notes-staging",
    items=[
        {"text": "...", "metadata": {"author": "agent-x", "verified": False}},
    ],
    idempotency_key="run-2026-04-07-batch-1",
)
print(result.accepted, result.rejected, result.lineage_id)
```

Writes return a structured result describing what was accepted, what was rejected (with reasons), and a lineage id for the audit trail. Writes are **idempotent** when the caller supplies an `idempotency_key` — re-submitting the same key returns the previous result without re-processing.

`append`, `upsert`, and `annotate` are separate methods on `WritesClient`, mirroring the three write modes from [`catalog.md`](catalog.md). The SDK does not pretend they're the same operation; the semantics differ.

### Trigger and watch an ingestion run

```python
run = await client.ingestion.start(
    source="rh-product-docs",
    refresh_mode="incremental",
)
print("started run:", run.id)

async for event in client.ingestion.stream_events(run.id):
    print(event.stage, event.status, event.progress)
```

Ingestion runs are long. The SDK exposes a streaming interface for run events so a CLI or UI can show real-time progress without polling. Under the hood it's a streamable-http connection to the MCP server, kept open until the run terminates.

For callers that don't want to stream, `client.ingestion.wait(run_id)` blocks (or `await`s) until the run completes and returns the final result, with a configurable timeout.

## Sync vs. async

Async is the default. Every public method has an async signature:

```python
result = await client.retrieval.query(source="...", query="...")
```

For callers that aren't in an async context, every method has a `_sync` twin with the same signature minus the `await`:

```python
result = client.retrieval.query_sync(source="...", query="...")
```

The sync versions are not just `asyncio.run` wrappers — they use a synchronous HTTP client underneath, so they don't pay the event-loop tax and they don't conflict with an outer event loop if one happens to be running. This is the same pattern memory-hub's SDK uses, and it's there because mixing async and sync at the call site is a mess otherwise.

The `_sync` methods are documented as second-class — the async path is what the SDK is optimized for — but they exist because plenty of real callers (notebooks, scripts, ad-hoc REPLs, parts of agent runtimes that aren't async) need them.

## Errors

Every error from the MCP server arrives at the SDK as a structured response with the reserved error codes from [`mcp-server.md`](mcp-server.md). The SDK translates them into typed exceptions, one per error code class:

```python
from retrieval_hub.errors import (
    RetrievalHubError,           # base
    SourceNotFoundError,
    SourceRetiredError,
    SourceNotPublishedError,
    AccessDeniedError,
    PatternNotSupportedError,
    PatternParameterInvalidError,
    RewriteDisabledError,
    BackendUnavailableError,
    RecipeVersionMismatchError,
    WriteNotAllowedError,
    WriteModeNotAllowedError,
    WriteValidationFailedError,
    WriteScopeRequiredError,
    AuthInvalidError,
    AuthExpiredError,
    RateLimitedError,
    InternalRetrievalHubError,
)
```

Every typed exception carries the error `code`, the `message`, and the `details` object from the wire response. Callers can either catch the base `RetrievalHubError` or catch a specific subclass:

```python
try:
    result = await client.retrieval.query(source="va-cpg", query="...")
except SourceRetiredError as e:
    log.warning("source retired, falling back: %s", e.details["successor_id"])
    result = await client.retrieval.query(source=e.details["successor_id"], query="...")
except RetrievalHubError as e:
    log.error("retrieval failed: %s [%s]", e.message, e.code)
    raise
```

The SDK does not retry on application-level errors. It does retry on transport-level transient errors (5xx, connection reset, etc.) with exponential backoff, up to a configurable limit.

The one exception to "no application-level retries" is `AuthExpiredError`: the SDK refreshes the token once and retries the call. A second `AuthExpiredError` propagates.

## Streaming

The MCP server uses streamable-http and supports streaming responses for tools that need them. The SDK exposes streaming as Python async iterators:

```python
async for hit in client.retrieval.query_stream(source="...", query="...", top_k=200):
    process(hit)
```

Streaming is useful when:

- The result set is large and the caller wants to start processing before all hits are retrieved.
- The operation is long-running and the caller wants progress feedback (ingestion run events).
- The result is naturally chunked (multi-source query that returns hits per source as they complete).

Most tools have both a non-streaming and a streaming version. The non-streaming version is the default; the streaming version has a `_stream` suffix.

## What it doesn't do

The SDK is not the place for:

- **Business logic.** It's a thin client. If a caller wants "find me the best document and summarize it," that's the caller's job, not the SDK's.
- **LLM orchestration.** The SDK does not call LLMs (except inside the agent-write content validators, which run in the core library, not in the SDK). If you want an agent loop, that's LangGraph / LlamaStack / Kagenti / your-favorite-runtime.
- **Connection pooling beyond the basics.** httpx defaults are fine for v1.
- **Caching beyond the auth token.** Caching results would be a feature, not a default; add it in user code if you need it.

## Versioning and compatibility

The SDK is versioned independently from the rest of retrieval-hub. The wire contract is the MCP tool surface, which is versioned through the same `/plan-tools → /create-tools → /update-docs → /deploy-mcp` workflow.

The SDK declares compatibility ranges in its `pyproject.toml` (`requires-retrieval-hub = ">=1.0,<2.0"` style). On startup, the client fetches the server's version and warns if the SDK is too old or too new. Mismatches don't fail fast — the SDK tries the call anyway, because forward and backward compatibility are real and the warning is enough.

## What's Decided

- **The SDK is its own peer component at `sdk/`**, published to PyPI as `retrieval-hub`. It does not import the core library.
- **Async is the default**, sync `_sync` methods exist for non-async callers and use a real sync HTTP client underneath.
- **One top-level `RetrievalHubClient`** with domain sub-clients (`sources`, `retrieval`, `rewrite`, `writes`, `ingestion`, `evals`, `admin`).
- **Configuration via env vars** by default, programmatic override available.
- **Two auth modes** are supported: issued (`CLIENT_ID` + `CLIENT_SECRET` → token from auth service) and inherited (`RETRIEVAL_HUB_TOKEN` → externally-issued JWT). Inherited mode wins if both are set.
- **Token caching and refresh transparent** in issued mode. The SDK does not refresh inherited tokens — the caller owns that.
- **Typed exceptions** mapped from the reserved error code set. One subclass per code.
- **Transport-level retries with backoff**, no application-level retries except a single `AuthExpiredError` retry.
- **Streaming via async iterators** for the operations that need it.
- **Convenience methods exist for common patterns** (`query_with_rewrite`) but are clearly marked as compositions, not new primitives.

## What's Open

- **The exact name of the convenience method** for "query with rewrite" — `query_with_rewrite` is a placeholder; whatever it gets called, the shape is more important than the name.
- **Whether `query_with_rewrite` rewrite strategies are open-ended** (`union` / `best_only` / `per_intent`) or pluggable. Round 1 ships the named ones.
- **Async-context managers for the client** (`async with RetrievalHubClient() as client: ...`) for clean resource cleanup. Probably yes; not committed.
- **TypeScript / JavaScript SDK.** Real demand from the UI side, but the UI's BFF is in Python so the JS need is for browser-side or off-cluster JS callers. Round 2 at the earliest.
- **Caching layer.** Out of round 2. Callers that need it can wrap the SDK.
- **Whether the SDK gets opinionated about LangGraph / LlamaStack / Kagenti adapter classes.** Tempting, but it would couple the SDK to specific runtimes. The integration docs (`integrations/<runtime>.md`) are the right place for those, if and when we write them.
