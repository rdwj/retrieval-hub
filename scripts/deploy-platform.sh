#!/usr/bin/env bash
# Deploy the full RetrievalHub platform to an OpenShift cluster.
#
# Orchestrates: secrets, infrastructure, migrations, model registry seeding,
# service deployments, and post-deploy verification. Wraps the individual
# per-component deploy scripts.
#
# Usage:
#   ./scripts/deploy-platform.sh --context=gpt-oss-120b
#   ./scripts/deploy-platform.sh --context=gpt-oss-120b --env-file=deploy/.env
#   ./scripts/deploy-platform.sh --context=gpt-oss-120b --skip-build
#   ./scripts/deploy-platform.sh --context=gpt-oss-120b --infra-only
#
# Options:
#   --context=NAME     OpenShift context (required)
#   --project=NAME     Namespace (default: retrieval-hub)
#   --env-file=PATH    Source cluster-specific variables from this file
#   --skip-build       Skip container builds (apply manifests and seed only)
#   --infra-only       Deploy infra + migrate + seed, skip service builds

set -euo pipefail

PROJECT="retrieval-hub"
CTX=""
SKIP_BUILD=false
INFRA_ONLY=false
ENV_FILE=""

for arg in "$@"; do
    case "$arg" in
        --context=*)   CTX="${arg#--context=}" ;;
        --project=*)   PROJECT="${arg#--project=}" ;;
        --env-file=*)  ENV_FILE="${arg#--env-file=}" ;;
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

# Source env file if provided
if [ -n "$ENV_FILE" ]; then
    if [ ! -f "$ENV_FILE" ]; then
        echo "ERROR: Env file not found: $ENV_FILE"
        exit 1
    fi
    echo "Sourcing env file: $ENV_FILE"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    # Allow env file to override PROJECT and CTX
    PROJECT="${PROJECT:-retrieval-hub}"
    CTX="${CONTEXT:-$CTX}"
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

# --- Secrets -----------------------------------------------------------------

echo "==> Ensuring secrets exist"

# Helper: create a secret idempotently (only if it doesn't already exist)
ensure_secret() {
    local name="$1"
    shift
    if oc get secret "$name" -n "$PROJECT" $OC_CTX &>/dev/null; then
        echo "  $name: exists (not overwriting)"
    else
        oc create secret generic "$name" "$@" -n "$PROJECT" $OC_CTX 2>&1 | sed 's/^/  /'
    fi
}

# PostgreSQL credentials
PG_USER="${POSTGRES_USER:-retrievalhub}"
PG_PASS="${POSTGRES_PASSWORD:-retrievalhub}"
PG_DB="retrievalhub"
PG_VECTORS_DB="retrievalhub_vectors"
PG_HOST="retrieval-hub-pg"
ensure_secret retrieval-hub-pg \
    --from-literal=POSTGRES_USER="$PG_USER" \
    --from-literal=POSTGRES_PASSWORD="$PG_PASS" \
    --from-literal=POSTGRES_DB="$PG_DB" \
    --from-literal=VECTORS_DB="$PG_VECTORS_DB" \
    --from-literal=RETRIEVAL_HUB_DB_URL="postgresql+psycopg://${PG_USER}:${PG_PASS}@${PG_HOST}:5432/${PG_DB}" \
    --from-literal=RETRIEVAL_HUB_VECTORS_DB_URL="postgresql+psycopg://${PG_USER}:${PG_PASS}@${PG_HOST}:5432/${PG_VECTORS_DB}"

# Auth service database (uses the same PG instance)
ensure_secret retrieval-hub-auth \
    --from-literal=DB_URL="postgresql+psycopg://${PG_USER}:${PG_PASS}@${PG_HOST}:5432/${PG_DB}_auth"

# Auth service signing key
SIGNING_KEY_PATH="${RETRIEVAL_HUB_AUTH_SIGNING_KEY_PATH:-}"
if [ -n "$SIGNING_KEY_PATH" ] && [ -f "$SIGNING_KEY_PATH" ]; then
    if oc get secret retrieval-hub-auth-signing-key -n "$PROJECT" $OC_CTX &>/dev/null; then
        echo "  retrieval-hub-auth-signing-key: exists (not overwriting)"
    else
        oc create secret generic retrieval-hub-auth-signing-key \
            --from-file=signing.pem="$SIGNING_KEY_PATH" \
            -n "$PROJECT" $OC_CTX 2>&1 | sed 's/^/  /'
    fi
else
    if oc get secret retrieval-hub-auth-signing-key -n "$PROJECT" $OC_CTX &>/dev/null; then
        echo "  retrieval-hub-auth-signing-key: exists (not overwriting)"
    else
        echo "  retrieval-hub-auth-signing-key: SKIPPED (no key path provided)"
        echo "    The auth service will generate an ephemeral key."
        echo "    Set RETRIEVAL_HUB_AUTH_SIGNING_KEY_PATH for persistent keys."
    fi
fi

# Google OAuth (optional)
GOOGLE_ID="${RETRIEVAL_HUB_GOOGLE_CLIENT_ID:-}"
GOOGLE_SECRET="${RETRIEVAL_HUB_GOOGLE_CLIENT_SECRET:-}"
if [ -n "$GOOGLE_ID" ] && [ -n "$GOOGLE_SECRET" ]; then
    ensure_secret retrieval-hub-google-oauth \
        --from-literal=RETRIEVAL_HUB_GOOGLE_CLIENT_ID="$GOOGLE_ID" \
        --from-literal=RETRIEVAL_HUB_GOOGLE_CLIENT_SECRET="$GOOGLE_SECRET"
else
    echo "  retrieval-hub-google-oauth: SKIPPED (no Google OAuth credentials)"
    echo "    Set RETRIEVAL_HUB_GOOGLE_CLIENT_ID and _SECRET to enable."
fi

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

PF_PID=""
cleanup_pf() { [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null; }
trap cleanup_pf EXIT

LOCAL_PORT=15432
oc port-forward statefulset/retrieval-hub-pg "$LOCAL_PORT:5432" \
    -n "$PROJECT" $OC_CTX &>/dev/null &
PF_PID=$!
sleep 3

if pg_isready -h 127.0.0.1 -p "$LOCAL_PORT" &>/dev/null; then
    RETRIEVAL_HUB_DB_URL="postgresql+psycopg://${PG_USER}:${PG_PASS}@127.0.0.1:$LOCAL_PORT/$PG_DB" \
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
        --db-url "postgresql+psycopg://${PG_USER}:${PG_PASS}@127.0.0.1:$LOCAL_PORT/$PG_DB" \
        2>&1 | sed 's/^/    /'
else
    echo "  WARNING: Could not reach cluster DB for seeding"
fi

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

    echo "--- Auth Service ---"
    if [ -f "$REPO_ROOT/retrieval-hub-auth/deploy.sh" ]; then
        "$REPO_ROOT/retrieval-hub-auth/deploy.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
    else
        echo "    SKIPPED (no deploy.sh)"
    fi
    echo ""

    echo "--- MCP Server ---"
    "$REPO_ROOT/retrieval-hub-mcp/deploy.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
    echo ""

    # Auto-detect MCP route URL and patch Google OAuth base URL
    MCP_ROUTE=$(oc get route retrieval-hub-mcp -n "$PROJECT" $OC_CTX \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$MCP_ROUTE" ]; then
        DETECTED_BASE_URL="https://$MCP_ROUTE"
        CURRENT_BASE_URL=$(oc get deployment retrieval-hub-mcp -n "$PROJECT" $OC_CTX \
            -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="RETRIEVAL_HUB_GOOGLE_BASE_URL")].value}' 2>/dev/null || echo "")
        if [ "$CURRENT_BASE_URL" != "$DETECTED_BASE_URL" ]; then
            echo "  Patching RETRIEVAL_HUB_GOOGLE_BASE_URL to $DETECTED_BASE_URL..."
            oc set env deployment/retrieval-hub-mcp \
                RETRIEVAL_HUB_GOOGLE_BASE_URL="$DETECTED_BASE_URL" \
                -n "$PROJECT" $OC_CTX 2>&1 | sed 's/^/    /'
        fi
    fi

    echo "--- BFF ---"
    "$REPO_ROOT/retrieval-hub-bff/deploy.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
    echo ""

    if [ -f "$REPO_ROOT/retrieval-hub-evalhub/deploy.sh" ]; then
        echo "--- EvalHub ---"
        "$REPO_ROOT/retrieval-hub-evalhub/deploy.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
        echo ""
    fi

    if [ -f "$REPO_ROOT/scripts/deploy-ui-live.sh" ]; then
        echo "--- UI ---"
        "$REPO_ROOT/scripts/deploy-ui-live.sh" "$PROJECT" --context="$CTX" 2>&1 | sed 's/^/    /'
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
        echo "  Health check: PASS"
    else
        echo "  Health check: WARN (HTTP $HEALTH — may need a moment to start)"
    fi

    OAUTH=$(curl -s -o /dev/null -w "%{http_code}" \
        "https://$MCP_ROUTE/.well-known/oauth-authorization-server" 2>/dev/null || echo "000")
    if [ "$OAUTH" = "200" ]; then
        echo "  Google OAuth: ENABLED"
    else
        echo "  Google OAuth: disabled or not configured"
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
[ -n "$MCP_ROUTE" ] && echo "  MCP:  https://$MCP_ROUTE/mcp"
echo "  Auth: http://retrieval-hub-auth:8080 (internal)"
echo "  BFF:  http://retrieval-hub-bff:8080 (internal)"
echo ""
echo "Connect with Claude Code:"
echo "  claude mcp add --transport http retrieval-hub https://$MCP_ROUTE/mcp"
echo ""
echo "Next steps:"
[ -n "$MCP_ROUTE" ] && echo "  - Verify: curl https://$MCP_ROUTE/health"
echo "  - Run eval: ./retrieval-hub-evalhub/submit-job.sh --context=$CTX"
echo "========================================="
