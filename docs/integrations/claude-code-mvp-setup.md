# Claude Code MVP Setup

Quick setup for the local MVP: query VA/DoD Clinical Practice Guidelines from Claude Code via the retrieval-hub MCP server.

## Prerequisites

- PostgreSQL+pgvector running on `gpt-oss-120b` cluster (deployed in `retrieval-hub` namespace)
- VA CPG corpus ingested (via `scripts/ingest_va_cpg.py`)
- `retrieval-hub` and `retrieval-hub-mcp` packages installed locally

## Step 1: Start port-forwarding

```bash
./scripts/port_forward_cluster_pg.sh
```

This forwards the cluster PostgreSQL to local ports:
- `localhost:5434` -> catalog DB (`retrievalhub`)
- `localhost:5433` -> vectors DB (`retrievalhub_vectors`)

## Step 2: Start the MCP server

In a separate terminal:

```bash
cd retrieval-hub-mcp
./run_local.sh
```

The server starts on `http://localhost:8000/mcp` with streamable-http transport.

## Step 3: Launch Claude Code

From the `retrieval-hub` project root:

```bash
claude
```

Claude Code picks up `.mcp.json` automatically. Verify the MCP server is connected:

```
/mcp
```

You should see `retrieval-hub` listed as a connected server with three tools.

## Step 4: Query clinical guidelines

Example prompts to test:

- "List the retrieval-hub sources"
- "What are the VA guidelines for managing hypertension?"
- "What medications are recommended for PTSD treatment?"
- "Describe the VA CPG clinical guidelines source"
- "What does the VA/DoD guideline say about opioid prescribing for chronic pain?"

The agent will call `list_sources`, `describe_source`, and `retrieve` tools to answer clinical questions using the VA CPG corpus.
