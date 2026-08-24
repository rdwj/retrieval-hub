#!/usr/bin/env bash
# Submit multiple parameterized eval Jobs from a sweep YAML definition.
#
# Usage:
#   ./retrieval-hub-evalhub/submit-sweep.sh sweeps/refine-strategies.yaml \
#       --context=gpt-oss-120b
#
# Jobs run sequentially because the model-cache PVC is ReadWriteOnce.
# Each job must finish before the next can mount the PVC.

set -euo pipefail

SWEEP_FILE=""
CTX=""
PROJECT="retrieval-hub"

for arg in "$@"; do
    case "$arg" in
        --context=*)  CTX="${arg#--context=}" ;;
        --project=*)  PROJECT="${arg#--project=}" ;;
        *.yaml|*.yml) SWEEP_FILE="$arg" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ -z "$SWEEP_FILE" ]; then
    echo "Usage: $0 <sweep-file.yaml> [--context=name]"
    exit 1
fi

if [ ! -f "$SWEEP_FILE" ]; then
    echo "ERROR: Sweep file not found: $SWEEP_FILE"
    exit 1
fi

OC_CTX=""
CTX_FLAG=""
if [ -n "$CTX" ]; then
    OC_CTX="--context=$CTX"
    CTX_FLAG="--context=$CTX"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse sweep YAML using Python
SWEEP_JSON=$(python3 -c "
import yaml, json, sys
with open('$SWEEP_FILE') as f:
    data = yaml.safe_load(f)
json.dump(data, sys.stdout)
")

SWEEP_ID=$(echo "$SWEEP_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['sweep_id'])")
DESCRIPTION=$(echo "$SWEEP_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('description',''))")
RUN_COUNT=$(echo "$SWEEP_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['runs']))")

echo "========================================="
echo "EvalHub Sweep: $SWEEP_ID"
echo "========================================="
echo "Description: $DESCRIPTION"
echo "Runs: $RUN_COUNT"
echo "Mode: sequential (ReadWriteOnce PVC)"
echo ""

COMPLETED=0
FAILED_COUNT=0

for i in $(seq 0 $((RUN_COUNT - 1))); do
    RUN_PARAMS=$(echo "$SWEEP_JSON" | python3 -c "
import json, sys
runs = json.load(sys.stdin)['runs']
run = runs[$i]
parts = []
parts.append('--run-id=' + run['run_id'])
if run.get('refine_strategy', ''):
    parts.append('--refine-strategy=' + run['refine_strategy'])
if run.get('refine_window'):
    parts.append('--refine-window=' + str(run['refine_window']))
if run.get('query_count'):
    parts.append('--query-count=' + str(run['query_count']))
if run.get('max_workers'):
    parts.append('--max-workers=' + str(run['max_workers']))
if run.get('force'):
    parts.append('--force')
print(' '.join(parts))
")

    RUN_ID=$(echo "$SWEEP_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['runs'][$i]['run_id'])")
    # Truncate to match Kubernetes job name (submit-job.sh truncates to 63 chars)
    JOB_NAME="${RUN_ID:0:63}"

    echo "-----------------------------------------"
    echo "Run $((i + 1))/$RUN_COUNT: $RUN_ID"
    echo "-----------------------------------------"

    if "$SCRIPT_DIR/submit-job.sh" \
        --sweep-id="$SWEEP_ID" \
        --project="$PROJECT" \
        $CTX_FLAG \
        $RUN_PARAMS; then

        echo "Waiting for job $JOB_NAME to complete..."
        while true; do
            JOB_COMPLETE=$(oc get job "$JOB_NAME" -n "$PROJECT" $OC_CTX \
                -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
            JOB_FAILED=$(oc get job "$JOB_NAME" -n "$PROJECT" $OC_CTX \
                -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || echo "")
            if [ "$JOB_COMPLETE" = "True" ]; then
                echo "  Run $RUN_ID completed successfully"
                COMPLETED=$((COMPLETED + 1))
                break
            elif [ "$JOB_FAILED" = "True" ]; then
                echo "  WARNING: Run $RUN_ID FAILED"
                echo "  Check logs: oc logs job/$JOB_NAME -n $PROJECT $OC_CTX"
                FAILED_COUNT=$((FAILED_COUNT + 1))
                break
            fi
            sleep 30
        done
    else
        echo "  ERROR: Failed to submit job $RUN_ID"
        FAILED_COUNT=$((FAILED_COUNT + 1))
    fi
    echo ""
done

echo "========================================="
echo "Sweep complete: $SWEEP_ID"
echo "========================================="
echo "  Completed: $COMPLETED / $RUN_COUNT"
echo "  Failed:    $FAILED_COUNT / $RUN_COUNT"
echo ""
echo "Check results in the eval register:"
echo "  SELECT er.case_id, er.metrics, er.payload"
echo "  FROM eval_result er"
echo "  JOIN eval_run r ON er.eval_run_id = r.id"
echo "  WHERE r.triggered_by LIKE 'evalhub:%'"
echo "  ORDER BY er.created_at;"
echo "========================================="
