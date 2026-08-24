#!/usr/bin/env bash
# Deploy the EvalHub container to OpenShift via binary build.
#
# Usage: ./retrieval-hub-evalhub/deploy.sh [project-name] [--context=name]
#
# Run from the repo root so the script can find the core library source,
# eval scripts, and the QA dataset.

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
echo "EvalHub Container Build"
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

echo "-> Applying OpenShift resources (BuildConfig, ImageStream, PVC)..."
oc apply -f "$SCRIPT_DIR/openshift.yaml" -n "$PROJECT" $OC_CTX

# --- Build context -----------------------------------------------------------

BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

echo "-> Creating build context in $BUILD_DIR..."

# Core library (installed as a package inside the container)
mkdir -p "$BUILD_DIR/core-lib/src"
cp -r "$REPO_ROOT/src/retrieval_hub" "$BUILD_DIR/core-lib/src/"
cp "$REPO_ROOT/pyproject.toml" "$BUILD_DIR/core-lib/"
[ -f "$REPO_ROOT/README.md" ] && cp "$REPO_ROOT/README.md" "$BUILD_DIR/core-lib/"

# EvalHub runner (installed as a package inside the container)
mkdir -p "$BUILD_DIR/evalhub-runner"
cp -r "$SCRIPT_DIR/src/evalhub_runner" "$BUILD_DIR/evalhub-runner/"
cp "$SCRIPT_DIR/src/pyproject.toml" "$BUILD_DIR/evalhub-runner/"

# Eval script (copied standalone, accessed via PYTHONPATH)
mkdir -p "$BUILD_DIR/scripts"
cp "$REPO_ROOT/scripts/eval_answer_quality.py" "$BUILD_DIR/scripts/"

# QA dataset (baked into the image)
mkdir -p "$BUILD_DIR/eval"
cp "$REPO_ROOT/eval/autorag/qa_dataset_v2.json" "$BUILD_DIR/eval/qa_dataset_v2.json"

# Prompt templates (needed by RewriterService)
cp -r "$REPO_ROOT/prompts" "$BUILD_DIR/prompts"

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
oc start-build retrieval-hub-evalhub \
    --from-dir="$BUILD_DIR" \
    --follow \
    -n "$PROJECT" $OC_CTX

# --- Report ------------------------------------------------------------------

echo ""
echo "========================================="
echo "Build complete"
echo "========================================="
echo "Image: image-registry.openshift-image-registry.svc:5000/$PROJECT/retrieval-hub-evalhub:latest"
echo ""
echo "Submit eval jobs with:"
echo "  ./retrieval-hub-evalhub/submit-job.sh --context=$CTX"
echo ""
echo "Submit a sweep with:"
echo "  ./retrieval-hub-evalhub/submit-sweep.sh sweeps/refine-strategies.yaml --context=$CTX"
echo "========================================="
