#!/usr/bin/env bash
set -euo pipefail

export RETRIEVAL_HUB_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
export RETRIEVAL_HUB_VECTORS_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"

# Google OAuth (set these env vars externally to enable)
export RETRIEVAL_HUB_GOOGLE_CLIENT_ID="${RETRIEVAL_HUB_GOOGLE_CLIENT_ID:-}"
export RETRIEVAL_HUB_GOOGLE_CLIENT_SECRET="${RETRIEVAL_HUB_GOOGLE_CLIENT_SECRET:-}"
export RETRIEVAL_HUB_GOOGLE_BASE_URL="${RETRIEVAL_HUB_GOOGLE_BASE_URL:-http://localhost:8000}"

echo "Starting RetrievalHub MCP server..."
echo "  Catalog DB: localhost:5434"
echo "  Vectors DB: localhost:5433"
echo "  Transport:  streamable-http"
if [ -n "$RETRIEVAL_HUB_GOOGLE_CLIENT_ID" ]; then
    echo "  Google OAuth: enabled"
else
    echo "  Google OAuth: disabled (set RETRIEVAL_HUB_GOOGLE_CLIENT_ID to enable)"
fi
echo ""

python -m retrieval_hub_mcp
