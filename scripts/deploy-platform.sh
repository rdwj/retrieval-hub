#!/usr/bin/env bash
# Deploy the full RetrievalHub platform to an OpenShift cluster.
#
# Orchestrates: infrastructure, migrations, model registry seeding,
# service deployments, and post-deploy verification. Wraps the
# individual per-component deploy scripts.
#
# Usage:
#   ./scripts/deploy-platform.sh --context=gpt-oss-120b
#   ./scripts/deploy-platform.sh --context=gpt-oss-120b --skip-build
#   ./scripts/deploy-platform.sh --context=gpt-oss-120b --infra-only
#
# Options:
#   --context=NAME    OpenShift context (required)
#   --project=NAME    Namespace (default: retrieval-hub)
#   --skip-build      Skip container builds (apply manifests and seed only)
#   --infra-only      Deploy infra + migrate + seed, skip service builds

set -euo pipefail

PROJECT="retrieval-hub"
CTX=""
SKIP_BUILD=false
INFRA_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --context=*)   CTX="${arg#--context=}" ;;
        --project=*)   PROJECT="${arg#--project=}" ;;
        --skip-build)  SKIP_BUILD=true ;;
        --infra-only)  INFRA_ONLY=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ -z "$CTX" ]; then
    echo "ERROR: --context is required"
    echo "Usage: $0 --context=<cluster-context>"
    exit 1
fi

OC_CTX="--context=$CTX"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "========================================="
echo "RetrievalHub Platform Deploy"
echo "========================================="
echo "Context: $CTX"
echo "Project: $PROJECT"
echo ""

# --- Preflight ---------------------------------------------------------------

echo "==> Preflight checks"

if ! oc whoami $OC_CTX &>/dev/null; then
    echo "ERROR: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi
echo "  Logged in as: $(oc whoami $OC_CTX)"

if ! oc get namespace "$PROJECT" $OC_CTX &>/dev/null; then
    echo "  Creating namespace $PROJECT..."
    oc new-project "$PROJECT" $OC_CTX 2>/dev/null || \
        oc create namespace "$PROJECT" $OC_CTX
fi
echo "  Namespace: $PROJECT"
echo ""

# --- Infrastructure ----------------------------------------------------------

echo "==> Deploying infrastructure"

INFRA_DIR="$REPO_ROOT/deploy/openshift/$PROJECT"

echo "  Applying PostgreSQL (Secret, PVC, StatefulSet, Service)..."
for f in secret.yaml pvc.yaml init-configmap.yaml statefulset.yaml service.yaml; do
    if [ -f "$INFRA_DIR/$f" ]; then
        oc apply -f "$INFRA_DIR/$f" -n "$PROJECT" $OC_CTX 2>&1 | sed 's/^/    /'
    fi
done

echo "  Applying embedding services..."
for f in "$INFRA_DIR/embedding/"*.yaml; do
    [ -f "$f" ] && oc apply -f "$f" -n "$PROJECT" $OC_CTX 2>&1 | sed 's/^/    /'
done

echo "  Waiting for PostgreSQL to be ready..."
oc rollout status statefulset/retrieval-hub-pg -n "$PROJECT" $OC_CTX --timeout=120s 2>&1 | sed 's/^/    /'
echo ""

# --- Database migrations -----------------------------------------------------

echo "==> Running database migrations"

# Port-forward to cluster PG for migration
PF_PID=""
cleanup_pf() { [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null; }
trap cleanup_pf EXIT

LOCAL_PORT=15432
oc port-forward statefulset/retrieval-hub-pg "$LOCAL_PORT:5432" \
    -n "$PROJECT" $OC_CTX &>/dev/null &
PF_PID=$!
sleep 3

if pg_isready -h 127.0.0.1 -p "$LOCAL_PORT" &>/dev/null; then
    RETRIEVAL_HUB_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:$LOCAL_PORT/retrievalhub" \
        python -m alembic upgrade head 2>&1 | sed 's/^/    /'
    echo "  Migrations complete"
else
    echo "  WARNING: Could not reach cluster DB for migrations"
fi
echo ""

# --- Seed model endpoints ----------------------------------------------------

echo "==> Seeding model registry"

if [ -n "$PF_PID" ] && pg_isready -h 127.0.0.1 -p "$LOCAL_PORT" &>/dev/null; then
    python "$REPO_ROOT/scripts/seed_model_endpoints.py" \
        --db-url "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:$LOCAL_PORT/retrievalhub" \
        2>&1 | sed 's/^/    /'
else
    echo "  WARNING: Could not reach cluster DB for seeding"
fi

# Clean up port-forward
kill "$PF_PID" 2>/dev/null
PF_PID=""
echo ""

# --- Deploy CronJob ----------------------------------------------------------

echo "==> Deploying model health probe CronJob"
if [ -f "$INFRA_DIR/probe-cronjob.yaml" ]; then
    oc apply -f "$INFRA_DIR/probe-cronjob.yaml" -n "$PROJECT" $OC_CTX 2>&1 | sed 's/^/    /'
fi
echo ""

if [ "$INFRA_ONLY" = true ]; then
    echo "========================================="
    echo "Infrastructure deploy complete (--infra-only)"
    echo "========================================="
    exit 0
fi

# --- Service builds ----------------------------------------------------------

if [ "$SKIP_BUILD" = false ]; then
    echo "==> Building and deploying services"
    echo ""

    echo "--- MCP Server ---"
    "$REPO_ROOT/retrieval-hub-mcp/deploy.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
    echo ""

    echo "--- BFF ---"
    "$REPO_ROOT/retrieval-hub-bff/deploy.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
    echo ""

    if [ -f "$REPO_ROOT/retrieval-hub-evalhub/deploy.sh" ]; then
        echo "--- EvalHub ---"
        "$REPO_ROOT/retrieval-hub-evalhub/deploy.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
        echo ""
    fi
else
    echo "==> Skipping builds (--skip-build)"
    echo ""
fi

# --- Post-deploy verification -----------------------------------------------

echo "==> Post-deploy verification"

MCP_ROUTE=$(oc get route retrieval-hub-mcp -n "$PROJECT" $OC_CTX \
    -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

if [ -n "$MCP_ROUTE" ]; then
    echo "  MCP Route: https://$MCP_ROUTE/mcp"

    HEALTH=$(curl -s -o /dev/null -w "%{http_code}" \
        "https://$MCP_ROUTE/health" 2>/dev/null || echo "000")
    if [ "$HEALTH" = "200" ]; then
        echo "  Health check: PASS (HTTP $HEALTH)"
    else
        echo "  Health check: WARN (HTTP $HEALTH — may need a moment to start)"
    fi
else
    echo "  WARNING: No MCP Route found"
fi

CRONJOB=$(oc get cronjob model-health-probe -n "$PROJECT" $OC_CTX \
    -o jsonpath='{.metadata.name}' 2>/dev/null || echo "")
if [ -n "$CRONJOB" ]; then
    echo "  Model probe CronJob: deployed"
else
    echo "  Model probe CronJob: not found"
fi

echo ""
echo "========================================="
echo "Platform deploy complete"
echo "========================================="
echo ""
echo "Services:"
echo "  MCP:  https://$MCP_ROUTE/mcp"
echo "  BFF:  http://retrieval-hub-bff:8080 (internal)"
echo ""
echo "Next steps:"
echo "  - Verify: curl https://$MCP_ROUTE/health"
echo "  - Run eval: ./retrieval-hub-evalhub/submit-job.sh --context=$CTX"
echo "========================================="
