#!/usr/bin/env bash
# Deploy the RetrievalHub live-data UI to OpenShift via binary build.
#
# The live UI uses nginx to reverse-proxy /api/ requests to the BFF
# service (retrieval-hub-bff:8080) running in the same namespace.
#
# Usage:
#   ./scripts/deploy-ui-live.sh [--context=gpt-oss-120b]
#
# Run from the repo root.

set -euo pipefail

PROJECT="retrieval-hub"
CTX="gpt-oss-120b"

for arg in "$@"; do
    case "$arg" in
        --context=*) CTX="${arg#--context=}" ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

OC_CTX="--context=$CTX"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST_DIR="$REPO_ROOT/deploy/openshift/retrieval-hub/ui-live"
UI_DIR="$REPO_ROOT/retrieval-hub-ui"

echo "========================================="
echo "RetrievalHub Live UI Deployment"
echo "========================================="
echo "Project:   $PROJECT"
echo "Context:   $CTX"
echo "Repo root: $REPO_ROOT"
echo ""

# --- Preflight checks -------------------------------------------------------

if ! oc whoami $OC_CTX &>/dev/null; then
    echo "ERROR: Not logged in to OpenShift context '$CTX'. Run 'oc login' first."
    exit 1
fi

if ! oc get namespace "$PROJECT" $OC_CTX &>/dev/null; then
    echo "ERROR: Namespace $PROJECT does not exist on context $CTX."
    exit 1
fi

# --- Apply OpenShift manifests -----------------------------------------------

echo "-> Applying OpenShift manifests..."
oc apply -f "$MANIFEST_DIR/" -n "$PROJECT" $OC_CTX

# --- Build context -----------------------------------------------------------
# Create a filtered directory containing only what Containerfile.live needs:
# the frontend source and the nginx config.  Excludes node_modules, dist,
# .vite, and other dev artifacts.

BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

echo "-> Creating build context in $BUILD_DIR..."

# Frontend source (excluding build artifacts)
mkdir -p "$BUILD_DIR/frontend"
rsync -a \
    --exclude='node_modules/' \
    --exclude='dist/' \
    --exclude='.vite/' \
    "$UI_DIR/frontend/" "$BUILD_DIR/frontend/"

# Containerfile and nginx config
cp "$UI_DIR/Containerfile.live" "$BUILD_DIR/Containerfile"
cp "$UI_DIR/nginx-live.conf" "$BUILD_DIR/"

# Fix 600 permissions from Claude Code's Write tool
FIXED_COUNT=$(find "$BUILD_DIR" -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.json" -o -name "*.css" -o -name "*.html" -o -name "*.conf" \) -perm 600 2>/dev/null | wc -l | tr -d ' ')
if [ "$FIXED_COUNT" -gt "0" ]; then
    echo "   Fixing $FIXED_COUNT file(s) with 600 permissions..."
    find "$BUILD_DIR" -type f -perm 600 -exec chmod 644 {} \;
fi

echo "   Build context size: $(du -sh "$BUILD_DIR" | cut -f1)"

# --- Binary build ------------------------------------------------------------

echo "-> Starting binary build (this may take several minutes)..."
oc start-build retrieval-hub-ui-live \
    --from-dir="$BUILD_DIR" \
    --follow \
    -n "$PROJECT" $OC_CTX

# --- Rollout -----------------------------------------------------------------

echo "-> Restarting deployment..."
oc rollout restart deployment/retrieval-hub-ui-live -n "$PROJECT" $OC_CTX 2>/dev/null || true
oc rollout status deployment/retrieval-hub-ui-live -n "$PROJECT" $OC_CTX --timeout=300s

# --- Report ------------------------------------------------------------------

ROUTE_HOST=$(oc get route retrieval-hub-ui-live -n "$PROJECT" $OC_CTX \
    -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

echo ""
echo "========================================="
echo "Deployment complete"
echo "========================================="
if [ -n "$ROUTE_HOST" ]; then
    echo "Live UI URL: https://${ROUTE_HOST}/"
else
    echo "Warning: could not retrieve route URL."
fi
echo "========================================="
