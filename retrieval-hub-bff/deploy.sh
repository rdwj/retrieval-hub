#!/usr/bin/env bash
# Deploy the RetrievalHub BFF to OpenShift via binary build.
#
# Usage: ./retrieval-hub-bff/deploy.sh [project-name] [--context=name]
#
# Run from the repo root so the script can find both the core library
# source and the BFF source.

set -euo pipefail

PROJECT="retrieval-hub"
CTX=""

for arg in "$@"; do
    case "$arg" in
        --context=*) CTX="${arg#--context=}" ;;
        *) PROJECT="$arg" ;;
    esac
done

OC_CTX=""
if [ -n "$CTX" ]; then
    OC_CTX="--context=$CTX"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "========================================="
echo "RetrievalHub BFF Deployment"
echo "========================================="
echo "Project:   $PROJECT"
[ -n "$CTX" ] && echo "Context:   $CTX"
echo "Repo root: $REPO_ROOT"
echo ""

# --- Preflight checks -------------------------------------------------------

if ! oc whoami $OC_CTX &>/dev/null; then
    echo "ERROR: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

if ! oc get namespace "$PROJECT" $OC_CTX &>/dev/null; then
    echo "ERROR: Namespace $PROJECT does not exist."
    exit 1
fi

# --- Apply OpenShift resources -----------------------------------------------

echo "-> Applying OpenShift resources..."
IMAGE_REF="image-registry.openshift-image-registry.svc:5000/$PROJECT/retrieval-hub-bff:latest"
sed "s|image: retrieval-hub-bff:latest|image: $IMAGE_REF|g" \
    "$SCRIPT_DIR/openshift.yaml" \
    | oc apply -f - -n "$PROJECT" $OC_CTX

# --- Build context -----------------------------------------------------------

BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

echo "-> Creating build context in $BUILD_DIR..."

# Core library (installed as a package inside the container)
mkdir -p "$BUILD_DIR/core-lib/src"
cp -r "$REPO_ROOT/src/retrieval_hub" "$BUILD_DIR/core-lib/src/"
cp "$REPO_ROOT/pyproject.toml" "$BUILD_DIR/core-lib/"
[ -f "$REPO_ROOT/README.md" ] && cp "$REPO_ROOT/README.md" "$BUILD_DIR/core-lib/"

# BFF (installed as a package inside the container)
mkdir -p "$BUILD_DIR/bff/src"
cp -r "$REPO_ROOT/retrieval-hub-bff/src/retrieval_hub_bff" "$BUILD_DIR/bff/src/"
cp "$REPO_ROOT/retrieval-hub-bff/pyproject.toml" "$BUILD_DIR/bff/"

# Containerfile and requirements
cp "$SCRIPT_DIR/Containerfile" "$BUILD_DIR/"
cp "$SCRIPT_DIR/requirements-deploy.txt" "$BUILD_DIR/"

# Fix 600 permissions from Claude Code's Write tool
FIXED_COUNT=$(find "$BUILD_DIR" -name "*.py" -perm 600 2>/dev/null | wc -l | tr -d ' ')
if [ "$FIXED_COUNT" -gt "0" ]; then
    echo "   Fixing $FIXED_COUNT file(s) with 600 permissions..."
    find "$BUILD_DIR" -name "*.py" -perm 600 -exec chmod 644 {} \;
fi

# Remove __pycache__ dirs
find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# --- Binary build ------------------------------------------------------------

echo "-> Starting binary build (this may take a few minutes)..."
oc start-build retrieval-hub-bff \
    --from-dir="$BUILD_DIR" \
    --follow \
    -n "$PROJECT" $OC_CTX

# --- Rollout -----------------------------------------------------------------

echo "-> Restarting deployment..."
oc rollout restart deployment/retrieval-hub-bff -n "$PROJECT" $OC_CTX 2>/dev/null || true
oc rollout status deployment/retrieval-hub-bff -n "$PROJECT" $OC_CTX --timeout=300s

# --- Report ------------------------------------------------------------------

SVC_IP=$(oc get service retrieval-hub-bff -n "$PROJECT" $OC_CTX \
    -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")

echo ""
echo "========================================="
echo "Deployment complete"
echo "========================================="
if [ -n "$SVC_IP" ]; then
    echo "Service ClusterIP: ${SVC_IP}:8080"
    echo ""
    echo "The BFF is internal-only (no Route)."
    echo "The nginx UI proxies to http://retrieval-hub-bff:8080/api/"
else
    echo "Warning: could not retrieve Service ClusterIP"
fi
echo "========================================="
