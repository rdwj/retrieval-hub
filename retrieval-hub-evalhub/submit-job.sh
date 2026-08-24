#!/usr/bin/env bash
# Submit a single parameterized eval Job to OpenShift.
#
# Usage:
#   ./retrieval-hub-evalhub/submit-job.sh --context=gpt-oss-120b [options]
#
# Options:
#   --run-id=NAME           Run identifier (default: auto-generated timestamp)
#   --sweep-id=NAME         Sweep group identifier (default: manual)
#   --refine-strategy=STR   "adjacent" or "section" (default: none)
#   --refine-window=N       Window for adjacent refine (default: 2)
#   --query-count=N         Number of queries, 0=all (default: 0)
#   --max-workers=N         Ragas scoring workers (default: 2)
#   --force                 Force re-run all stages
#   --log-level=LEVEL       Log level: DEBUG/INFO/WARNING/ERROR (default: INFO)
#   --project=NAME          OpenShift project/namespace (default: retrieval-hub)

set -euo pipefail

PROJECT="retrieval-hub"
CTX=""
RUN_ID="evalhub-$(date +%Y%m%d-%H%M%S)"
SWEEP_ID="manual"
REFINE_STRATEGY=""
REFINE_WINDOW="2"
QUERY_COUNT="0"
MAX_WORKERS="4"
FORCE="false"
LOG_LEVEL="INFO"

for arg in "$@"; do
    case "$arg" in
        --context=*)          CTX="${arg#--context=}" ;;
        --project=*)          PROJECT="${arg#--project=}" ;;
        --run-id=*)           RUN_ID="${arg#--run-id=}" ;;
        --sweep-id=*)         SWEEP_ID="${arg#--sweep-id=}" ;;
        --refine-strategy=*)  REFINE_STRATEGY="${arg#--refine-strategy=}" ;;
        --refine-window=*)    REFINE_WINDOW="${arg#--refine-window=}" ;;
        --query-count=*)      QUERY_COUNT="${arg#--query-count=}" ;;
        --max-workers=*)      MAX_WORKERS="${arg#--max-workers=}" ;;
        --force)              FORCE="true" ;;
        --log-level=*)        LOG_LEVEL="${arg#--log-level=}" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

OC_CTX=""
if [ -n "$CTX" ]; then
    OC_CTX="--context=$CTX"
fi

# Truncate job name to 63 chars (Kubernetes naming limit)
JOB_NAME="${RUN_ID:0:63}"

IMAGE="image-registry.openshift-image-registry.svc:5000/$PROJECT/retrieval-hub-evalhub:latest"
DB_HOST="retrieval-hub-pg:5432"
LLM_URL="http://gpt-oss-120b-direct.gpt-oss-120b-model.svc:8080"

echo "Submitting eval Job: $JOB_NAME"
echo "  sweep_id=$SWEEP_ID refine=$REFINE_STRATEGY window=$REFINE_WINDOW queries=$QUERY_COUNT"

oc create -f - -n "$PROJECT" $OC_CTX <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB_NAME
  labels:
    app: retrieval-hub-evalhub
    evalhub-sweep: "$SWEEP_ID"
    evalhub-run: "$RUN_ID"
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 43200
  template:
    metadata:
      labels:
        app: retrieval-hub-evalhub
    spec:
      restartPolicy: Never
      containers:
      - name: eval
        image: $IMAGE
        env:
        - name: EVALHUB_DB_URL
          valueFrom:
            secretKeyRef:
              name: retrieval-hub-pg
              key: RETRIEVAL_HUB_DB_URL
        - name: EVALHUB_VECTORS_DB_URL
          valueFrom:
            secretKeyRef:
              name: retrieval-hub-pg
              key: RETRIEVAL_HUB_VECTORS_DB_URL
        - name: EVALHUB_LLM_URL
          value: "$LLM_URL"
        - name: EVALHUB_LLM_MODEL
          value: "/mnt/models"
        - name: EVALHUB_RUN_ID
          value: "$RUN_ID"
        - name: EVALHUB_SWEEP_ID
          value: "$SWEEP_ID"
        - name: EVALHUB_REFINE_STRATEGY
          value: "$REFINE_STRATEGY"
        - name: EVALHUB_REFINE_WINDOW
          value: "$REFINE_WINDOW"
        - name: EVALHUB_QUERY_COUNT
          value: "$QUERY_COUNT"
        - name: EVALHUB_MAX_WORKERS
          value: "$MAX_WORKERS"
        - name: EVALHUB_FORCE
          value: "$FORCE"
        - name: EVALHUB_LOG_LEVEL
          value: "$LOG_LEVEL"
        resources:
          requests:
            memory: 2Gi
            cpu: "1"
          limits:
            memory: 4Gi
            cpu: "2"
        volumeMounts:
        - name: run-data
          mountPath: /opt/app-root/src/runs
      volumes:
      - name: run-data
        emptyDir:
          sizeLimit: 1Gi
EOF

echo ""
echo "Job submitted: $JOB_NAME"
echo ""
echo "Tail logs:"
echo "  oc logs -f job/$JOB_NAME -n $PROJECT $OC_CTX"
echo ""
echo "Check status:"
echo "  oc get job $JOB_NAME -n $PROJECT $OC_CTX"
