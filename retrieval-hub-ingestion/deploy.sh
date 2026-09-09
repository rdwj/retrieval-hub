#!/usr/bin/env bash
# Build and push the RetrievalHub ingestion image via OpenShift binary build.
#
# Usage:
#   ./retrieval-hub-ingestion/deploy.sh [--context=name] [--source=slug]
#
# --source=slug  Include source data in the build context. The data is
#                read from ../retrieval-hub-data-sources/<slug>/ relative
#                to the repo root. Without --source, the data/ directory
#                in the image is empty (use a PVC mount instead).
#
# Run from the repo root so the script can find the core library and scripts.

set -euo pipefail

PROJECT="retrieval-hub"
CTX=""
SOURCE=""

for arg in "$@"; do
    case "$arg" in
        --context=*) CTX="${arg#--context=}" ;;
        --source=*) SOURCE="${arg#--source=}" ;;
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
echo "RetrievalHub Ingestion Image Build"
echo "========================================="
echo "Project:   $PROJECT"
[ -n "$CTX" ] && echo "Context:   $CTX"
[ -n "$SOURCE" ] && echo "Source:    $SOURCE"
echo "Repo root: $REPO_ROOT"
echo ""

# --- Preflight ---------------------------------------------------------------

if ! oc whoami $OC_CTX &>/dev/null; then
    echo "ERROR: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

# Ensure BuildConfig exists
if ! oc get bc retrieval-hub-ingestion -n "$PROJECT" $OC_CTX &>/dev/null 2>&1; then
    echo "-> Creating BuildConfig..."
    oc apply -f "$REPO_ROOT/deploy/openshift/retrieval-hub/ingestion-buildconfig.yaml" \
        -n "$PROJECT" $OC_CTX
fi

# --- Build context -----------------------------------------------------------

BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

echo "-> Creating build context in $BUILD_DIR..."

# Core library
mkdir -p "$BUILD_DIR/core-lib/src"
cp -r "$REPO_ROOT/src/retrieval_hub" "$BUILD_DIR/core-lib/src/"
cp "$REPO_ROOT/pyproject.toml" "$BUILD_DIR/core-lib/"
[ -f "$REPO_ROOT/README.md" ] && cp "$REPO_ROOT/README.md" "$BUILD_DIR/core-lib/"

# Ingestion scripts
mkdir -p "$BUILD_DIR/scripts"
cp "$REPO_ROOT"/scripts/ingest_*.py "$BUILD_DIR/scripts/"

# Source data (optional)
mkdir -p "$BUILD_DIR/data"
if [ -n "$SOURCE" ]; then
    DATA_SOURCES_DIR="$REPO_ROOT/../retrieval-hub-data-sources"
    case "$SOURCE" in
        hetionet)
            SRC_DATA="$DATA_SOURCES_DIR/hetionet/hypertension-subgraph"
            if [ -d "$SRC_DATA" ]; then
                mkdir -p "$BUILD_DIR/data/hetionet"
                cp "$SRC_DATA"/*.tsv "$BUILD_DIR/data/hetionet/"
                echo "   Included hetionet data ($(du -sh "$BUILD_DIR/data/hetionet" | cut -f1))"
            else
                echo "WARNING: Hetionet data not found at $SRC_DATA"
            fi
            ;;
        tale-of-two-cities)
            SRC_DATA="$DATA_SOURCES_DIR/tale-of-two-cities"
            if [ -d "$SRC_DATA" ]; then
                mkdir -p "$BUILD_DIR/data/tale-of-two-cities"
                cp "$SRC_DATA"/*.html "$BUILD_DIR/data/tale-of-two-cities/" 2>/dev/null || \
                    cp "$SRC_DATA"/*.htm "$BUILD_DIR/data/tale-of-two-cities/" 2>/dev/null || true
                echo "   Included tale-of-two-cities data"
            else
                echo "WARNING: Tale of Two Cities data not found at $SRC_DATA"
            fi
            ;;
        *)
            echo "WARNING: Unknown source '$SOURCE'. No data included."
            echo "   Supported: hetionet, tale-of-two-cities"
            echo "   Add new sources to this script's case block."
            ;;
    esac
fi

# Containerfile
cp "$SCRIPT_DIR/Containerfile" "$BUILD_DIR/"

# Fix 600 permissions
FIXED_COUNT=$(find "$BUILD_DIR" -name "*.py" -perm 600 2>/dev/null | wc -l | tr -d ' ')
if [ "$FIXED_COUNT" -gt "0" ]; then
    echo "   Fixing $FIXED_COUNT file(s) with 600 permissions..."
    find "$BUILD_DIR" -name "*.py" -perm 600 -exec chmod 644 {} \;
fi

# Remove __pycache__
find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# --- Binary build ------------------------------------------------------------

echo "-> Starting binary build (this may take several minutes)..."
oc start-build retrieval-hub-ingestion \
    --from-dir="$BUILD_DIR" \
    --follow \
    -n "$PROJECT" $OC_CTX

echo ""
echo "========================================="
echo "Ingestion image build complete"
echo "========================================="
echo "Image: image-registry.openshift-image-registry.svc:5000/$PROJECT/retrieval-hub-ingestion:latest"
echo ""
echo "Run a Job:"
echo "  oc create -f deploy/openshift/retrieval-hub/ingestion-job-hetionet.yaml \\"
echo "    -n $PROJECT $OC_CTX"
echo "========================================="
