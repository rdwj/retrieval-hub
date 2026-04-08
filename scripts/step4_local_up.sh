#!/usr/bin/env bash
# Thin wrapper: bring up local dev dependencies for step 4 via Ansible.
#
# The real work lives in deploy/ansible/playbooks/local_all_up.yml — this
# script exists so developers who just want a shell command don't have to
# remember the ansible-playbook invocation.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ansible-playbook \
  -i deploy/ansible/inventory/local \
  deploy/ansible/playbooks/local_all_up.yml \
  "$@"
