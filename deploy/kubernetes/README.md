# deploy/kubernetes/

Kubernetes manifests for deploying retrieval-hub to an OpenShift cluster.

Round 1 ships a single file: `namespace.yaml`. The full deployment story —
peer-component Deployments, Services, Routes, SCCs, RoleBindings, the
eventual Operator and CRDs — lands in later steps per `docs/SYSTEMS.md`
and `docs/operator.md`.

## Apply the namespace

```bash
kubectl apply -f deploy/kubernetes/namespace.yaml
```

Or on OpenShift:

```bash
oc apply -f deploy/kubernetes/namespace.yaml
```

## Namespace conventions

- **Namespace name**: `retrieval-hub`
- **Pod Security Standards**: `restricted` (enforce, audit, warn)
- **All peer components run as non-root** (user 1001) — confirmed in each
  component's Containerfile. No elevated SCCs required.
- **Per-component labels** follow `app.kubernetes.io/name: <component>`,
  `app.kubernetes.io/part-of: retrieval-hub`.

## Current manifests

### `ui/` — demo UI (stage 2 mockup)

Deploys the static PatternFly catalog demo via UBI nginx. Built via an OpenShift binary BuildConfig.

```bash
# Create the BuildConfig (first time only)
oc new-build --name=retrieval-hub-ui --binary=true --strategy=docker \
  --to=retrieval-hub-ui:latest --context=<ctx> -n retrieval-hub
oc patch bc/retrieval-hub-ui --context=<ctx> -n retrieval-hub \
  --type=json -p '[{"op":"add","path":"/spec/strategy/dockerStrategy","value":{"dockerfilePath":"Containerfile"}}]'

# Build and deploy
oc start-build retrieval-hub-ui --from-dir=retrieval-hub-ui --follow --context=<ctx> -n retrieval-hub
oc apply -f deploy/kubernetes/ui/ --context=<ctx> -n retrieval-hub
oc rollout restart deployment/retrieval-hub-ui --context=<ctx> -n retrieval-hub
```

## Future structure

When the full cluster deploy lands, this directory will grow to:

```
deploy/kubernetes/
├── namespace.yaml
├── base/
│   ├── kustomization.yaml
│   ├── core/                 # PostgreSQL statefulset, MinIO, shared resources
│   ├── auth/                 # retrieval-hub-auth Deployment + Service + Route
│   ├── mcp/                  # retrieval-hub-mcp
│   ├── ui/                   # retrieval-hub-ui (frontend + BFF)
│   └── networkpolicies/
├── overlays/
│   ├── dev/
│   ├── staging/
│   └── prod/
└── operator/                 # round 2+ Operator deployment and CRDs
```

Until then, production deploys go through plain `kubectl apply` against the
single namespace manifest plus whatever per-component manifests the peer
components ship in their own subdirectories.

## Why Ansible for local dev but Kubernetes manifests here

Ansible's podman modules give us a consistent local-dev story (see
`../ansible/playbooks/`). The cluster-side target is pure Kubernetes
declarative manifests (and eventually Kustomize overlays + an Operator).
Both are IaC, both are committed to the repo, both are under version control.
The split keeps local-dev complexity out of the cluster manifests and vice
versa.
