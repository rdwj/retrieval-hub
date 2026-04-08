#!/usr/bin/env bash
# Thin wrapper: tear down local dev dependencies for step 4 via Ansible.
#
# Stops and removes both containers. Data volumes are preserved by default.
# Pass --remove-volumes to also delete the volumes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

EXTRA_VARS=""
for arg in "$@"; do
  if [[ "$arg" == "--remove-volumes" ]]; then
    EXTRA_VARS="-e remove_volumes=true"
  fi
done

ansible-playbook \
  -i deploy/ansible/inventory/local \
  deploy/ansible/playbooks/local_pgvector_down.yml \
  $EXTRA_VARS

ansible-playbook \
  -i deploy/ansible/inventory/local \
  deploy/ansible/playbooks/local_catalog_pg_down.yml \
  $EXTRA_VARS
