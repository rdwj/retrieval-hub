# retrieval-hub — deploy/

Infrastructure-as-code for retrieval-hub. Two deployment targets:

1. **Local dev** on a developer's machine via **Ansible + podman**
2. **OpenShift cluster** via **Kubernetes manifests** (and eventually the retrieval-hub Operator, per `docs/operator.md`)

Both targets start from the same artifacts so a local dev environment is a faithful scale model of the eventual cluster deploy.

## Layout

```
deploy/
├── README.md                         # this file
├── ansible/
│   ├── inventory/
│   │   └── local                     # localhost inventory, used for dev setup
│   └── playbooks/
│       ├── local_pgvector_up.yml     # start a pgvector podman container on localhost:5433
│       ├── local_pgvector_down.yml   # stop + remove the pgvector container
│       ├── local_catalog_pg_up.yml   # start the catalog Postgres container on localhost:5434
│       ├── local_catalog_pg_down.yml # stop + remove the catalog Postgres container
│       └── local_all_up.yml          # convenience: run both *_up playbooks in sequence
└── kubernetes/
    ├── namespace.yaml                # the `retrieval-hub` namespace declaration
    └── README.md                     # cluster-deploy notes (round 2+)
```

## Local dev with Ansible

**Prerequisites:** podman, ansible-core (`pip install ansible` or `brew install ansible`).

**Bring everything up:**

```bash
ansible-playbook -i deploy/ansible/inventory/local deploy/ansible/playbooks/local_all_up.yml
```

This runs two podman containers on the loopback interface:

- **`retrieval-hub-pgvector`** on `localhost:5433` — the vector store for per-source physical indexes. Image: `pgvector/pgvector:pg16`.
- **`retrieval-hub-catalog-pg`** on `localhost:5434` — the retrieval-hub catalog database. Image: `postgres:16`.

Both containers persist their data to podman-managed volumes (`retrieval-hub-pgvector-data`, `retrieval-hub-catalog-pg-data`) so stopping and restarting preserves state.

**Environment variables the core library will read:**

```bash
export RETRIEVAL_HUB_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@localhost:5434/retrievalhub"
export RETRIEVAL_HUB_VECTORS_DB_URL="postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
```

**Tear everything down:**

```bash
ansible-playbook -i deploy/ansible/inventory/local deploy/ansible/playbooks/local_catalog_pg_down.yml
ansible-playbook -i deploy/ansible/inventory/local deploy/ansible/playbooks/local_pgvector_down.yml
```

The down playbooks stop and remove the containers but preserve the data volumes by default. Pass `-e remove_volumes=true` to delete the volumes too.

## Why Ansible for local dev

It would be shorter to ship a `docker-compose.yml` or a couple of `podman run` scripts, but shipping Ansible playbooks for local dev is deliberate:

1. **The same language reaches the cluster.** When retrieval-hub's production deploy story materializes (round 2+), it will use Ansible for cluster setup — either directly or through an Ansible-backed Operator. Using Ansible locally means the automation pattern is consistent across environments and developers become familiar with the same tools.
2. **IaC-by-default.** Every cluster-side concern (namespaces, SCCs, RoleBindings, secrets, container registry auth) is more naturally expressed in Ansible than in a shell script. Starting there avoids a mid-project rewrite.
3. **The `scripts/` wrappers stay thin.** Scripts like `scripts/step4_local_up.sh` are one-liners that call the right playbook, so developers who want a shell command still get one.

## Cluster deploy (round 2+)

See `deploy/kubernetes/` for the canonical Kubernetes namespace definition. The full cluster deploy — Operator, CRDs, SCCs, service accounts, routes, operator-managed secrets — lands later per the build order in `docs/SYSTEMS.md`. For now `namespace.yaml` is the single cluster artifact we own.

When the cluster deploy lands, the expected structure is:

```
deploy/kubernetes/
├── namespace.yaml                    # retrieval-hub namespace (already exists)
├── operator/                         # Operator deployment + CRDs (round 2+)
├── overlays/
│   ├── dev/                          # dev-cluster kustomization
│   ├── staging/                      # staging overlay
│   └── prod/                         # production overlay
└── base/                             # base manifests (round 2+)
```

The parallel structure to `deploy/ansible/` is intentional: Ansible playbooks run against local podman *and* against cluster nodes, while Kubernetes manifests are the declarative target for the control plane.

## What does not belong here

- **Source code** — lives under `src/`, `retrieval-hub-auth/`, `retrieval-hub-ui/frontend/`. This directory is pure infra.
- **Secrets** — deploy-time secrets come from Kubernetes Secrets (in-cluster) or developer-local `.env` files (never committed). Ansible playbooks read credentials from environment variables or vault, never from hardcoded values.
- **Data** — ingestion corpora, MLflow runs, Grafana dashboards all live elsewhere. This is plumbing, not payload.
