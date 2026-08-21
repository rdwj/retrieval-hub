#!/usr/bin/env bash
# Port-forward cluster PostgreSQL to local ports matching code defaults.
# Catalog DB: localhost:5434 -> cluster:5432 (database: retrievalhub)
# Vectors DB: localhost:5433 -> cluster:5432 (database: retrievalhub_vectors)
# Both databases are in the same PostgreSQL pod; use different local ports
# for clarity and backward compat with the local Ansible setup.

set -euo pipefail

CTX="gpt-oss-120b"
NS="retrieval-hub"
SVC="svc/retrieval-hub-pg"

echo "Port-forwarding cluster PostgreSQL..."
echo "  Catalog DB: localhost:5434 -> retrievalhub"
echo "  Vectors DB: localhost:5433 -> retrievalhub_vectors"
echo ""
echo "Connection strings:"
echo "  RETRIEVAL_HUB_DB_URL=postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
echo "  RETRIEVAL_HUB_VECTORS_DB_URL=postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
echo ""

# Forward two local ports to the same cluster service port
oc port-forward --context="$CTX" -n "$NS" "$SVC" 5434:5432 5433:5432 &
PF_PID=$!

echo "Port-forward PID: $PF_PID"
echo "Press Ctrl+C to stop."
wait $PF_PID
