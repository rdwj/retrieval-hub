#!/usr/bin/env bash
# Deploy the RetrievalHub auth service to OpenShift via binary build.
#
# Usage: ./retrieval-hub-auth/deploy.sh [project-name] [--context=name]
#
# Run from the repo root.

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
echo "RetrievalHub Auth Service Deployment"
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
IMAGE_REF="image-registry.openshift-image-registry.svc:5000/$PROJECT/retrieval-hub-auth:latest"
sed "s|image: retrieval-hub-auth:latest|image: $IMAGE_REF|g" \
    "$SCRIPT_DIR/openshift.yaml" \
    | oc apply -f - -n "$PROJECT" $OC_CTX

# --- Build context -----------------------------------------------------------

BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

echo "-> Creating build context in $BUILD_DIR..."

# Auth service source
mkdir -p "$BUILD_DIR/src"
cp -r "$SCRIPT_DIR/src/retrieval_hub_auth" "$BUILD_DIR/src/"
cp "$SCRIPT_DIR/pyproject.toml" "$BUILD_DIR/"
cp "$SCRIPT_DIR/Containerfile" "$BUILD_DIR/"

# Fix 600 permissions from Claude Code's Write tool
FIXED_COUNT=$(find "$BUILD_DIR" -name "*.py" -perm 600 2>/dev/null | wc -l | tr -d ' ')
if [ "$FIXED_COUNT" -gt "0" ]; then
    echo "   Fixing $FIXED_COUNT file(s) with 600 permissions..."
    find "$BUILD_DIR" -name "*.py" -perm 600 -exec chmod 644 {} \;
fi

find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# --- Binary build ------------------------------------------------------------

echo "-> Starting binary build..."
oc start-build retrieval-hub-auth \
    --from-dir="$BUILD_DIR" \
    --follow \
    -n "$PROJECT" $OC_CTX

# --- Rollout -----------------------------------------------------------------

echo "-> Restarting deployment..."
oc rollout restart deployment/retrieval-hub-auth -n "$PROJECT" $OC_CTX 2>/dev/null || true
oc rollout status deployment/retrieval-hub-auth -n "$PROJECT" $OC_CTX --timeout=300s

# --- Report ------------------------------------------------------------------

echo ""
echo "========================================="
echo "Auth service deployment complete"
echo "========================================="
echo "Service: retrieval-hub-auth:8080 (internal)"
echo "JWKS:    http://retrieval-hub-auth:8080/.well-known/jwks.json"
echo "========================================="
