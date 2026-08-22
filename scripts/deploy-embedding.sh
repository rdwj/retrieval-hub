#!/usr/bin/env bash
# Deploy an embedding model to OpenShift.
#
# Usage:
#   ./scripts/deploy-embedding.sh <model> --context=<ctx> [--namespace=<ns>]
#
# Models:
#   tei-pubmedbert      TEI PubMedBERT (CPU, port 8080)
#   vllm-snowflake      vLLM Snowflake Arctic (GPU, port 8000)
#
# Run from the repo root.

set -euo pipefail

usage() {
    cat <<EOF
Usage: $0 <model> --context=<ctx> [--namespace=<ns>]

Models:
  tei-pubmedbert      TEI PubMedBERT (CPU, port 8080)
  vllm-snowflake      vLLM Snowflake Arctic (GPU, port 8000)

Options:
  --context=<name>    OpenShift context (REQUIRED)
  --namespace=<name>  Target namespace (default: retrieval-hub)
EOF
    exit 1
}

MODEL=""
CTX=""
NAMESPACE="retrieval-hub"

for arg in "$@"; do
    case "$arg" in
        --context=*) CTX="${arg#--context=}" ;;
        --namespace=*) NAMESPACE="${arg#--namespace=}" ;;
        -*) echo "Unknown option: $arg"; usage ;;
        *) MODEL="$arg" ;;
    esac
done

if [ -z "$MODEL" ]; then
    echo "ERROR: Model argument is required."
    echo ""
    usage
fi

if [ -z "$CTX" ]; then
    echo "ERROR: --context is required (TEI and Snowflake may live on different clusters)."
    echo ""
    usage
fi

OC_CTX="--context=$CTX"
OC_NS="-n $NAMESPACE"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Model-to-manifest mapping ------------------------------------------------

case "$MODEL" in
    tei-pubmedbert)
        MANIFEST="$REPO_ROOT/deploy/openshift/retrieval-hub/embedding/tei.yaml"
        DEPLOY_NAME="retrieval-hub-embedding"
        SVC_NAME="retrieval-hub-embedding"
        PORT=8080
        POD_SELECTOR="app=retrieval-hub,component=embedding"
        HAS_ROUTE=false
        ;;
    vllm-snowflake)
        MANIFEST="$REPO_ROOT/deploy/openshift/retrieval-hub/embedding/vllm-snowflake.yaml"
        DEPLOY_NAME="vllm-snowflake-embedding"
        SVC_NAME="vllm-snowflake-embedding"
        PORT=8000
        POD_SELECTOR="app=retrieval-hub,component=embedding,model=snowflake-arctic"
        HAS_ROUTE=true
        ;;
    *)
        echo "ERROR: Unknown model '$MODEL'."
        echo ""
        usage
        ;;
esac

# --- Banner -------------------------------------------------------------------

echo "========================================="
echo "RetrievalHub Embedding Model Deployment"
echo "========================================="
echo "Model:     $MODEL"
echo "Namespace: $NAMESPACE"
echo "Context:   $CTX"
echo "Manifest:  $MANIFEST"
echo ""

# --- Preflight checks ---------------------------------------------------------

if ! oc whoami $OC_CTX &>/dev/null; then
    echo "ERROR: Not logged in to OpenShift context '$CTX'. Run 'oc login' first."
    exit 1
fi

if ! oc get namespace "$NAMESPACE" $OC_CTX &>/dev/null; then
    echo "ERROR: Namespace $NAMESPACE does not exist on context $CTX."
    exit 1
fi

# --- Apply manifest -----------------------------------------------------------

echo "-> Applying manifest..."
if [ "$NAMESPACE" != "retrieval-hub" ]; then
    sed "s/namespace: retrieval-hub/namespace: $NAMESPACE/g" "$MANIFEST" \
        | oc apply -f - $OC_NS $OC_CTX
else
    oc apply -f "$MANIFEST" $OC_NS $OC_CTX
fi

# --- Rollout ------------------------------------------------------------------

echo "-> Waiting for rollout..."
oc rollout status deployment/"$DEPLOY_NAME" $OC_NS $OC_CTX --timeout=600s

echo "-> Waiting for pod readiness..."
oc wait pod -l "$POD_SELECTOR" --for=condition=Ready $OC_NS $OC_CTX --timeout=600s

# --- Report -------------------------------------------------------------------

echo ""
echo "========================================="
echo "Deployment complete"
echo "========================================="
echo "Service URL: http://${SVC_NAME}.${NAMESPACE}.svc.cluster.local:${PORT}"

if [ "$HAS_ROUTE" = true ]; then
    ROUTE_HOST=$(oc get route "$DEPLOY_NAME" $OC_NS $OC_CTX \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$ROUTE_HOST" ]; then
        echo "Route URL:   https://${ROUTE_HOST}/"
    else
        echo "Warning: could not retrieve route URL."
    fi
else
    echo "(ClusterIP only — no external Route)"
fi
echo "========================================="
