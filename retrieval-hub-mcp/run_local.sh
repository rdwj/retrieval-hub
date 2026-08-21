#!/usr/bin/env bash
set -euo pipefail

export RETRIEVAL_HUB_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
export RETRIEVAL_HUB_VECTORS_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"

echo "Starting RetrievalHub MCP server..."
echo "  Catalog DB: localhost:5434"
echo "  Vectors DB: localhost:5433"
echo "  Transport:  streamable-http"
echo ""

python -m retrieval_hub_mcp
