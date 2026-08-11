# Operator (`retrieval-hub-operator`) — future

The Operator is the future subsystem that owns the lifecycle of retrieval-hub through Kubernetes Custom Resources. It does not exist yet, and **deliberately should not exist yet**. This doc captures the shape we expect it to take so that when the time comes, the design isn't a surprise — but the time is not now.

## Why this is deferred

The platform pattern is explicit: start with plain manifests and Kustomize overlays, graduate to an Operator once the configuration surface has stopped moving. retrieval-hub is in the design-and-prototype phase. The configuration surface is changing every time we touch a doc. Building an Operator now would mean building it against a moving target, and the result would be either too rigid (we'd be fighting the Operator every time we changed something) or so loose that it wouldn't be a real Operator.

The right time to write the Operator is when:

- The peer components and their configuration have been stable across at least a few production deployments.
- The configuration surface has stopped growing significantly between releases.
- Operations on the system (upgrade, scale, restore from backup, key rotation, recovery from a bad release) have happened enough times that the runbook patterns are clear.
- A second team — somebody who isn't us — wants to deploy retrieval-hub and is asking for declarative management.

Until those conditions hold, plain manifests + Kustomize + a small number of `make deploy` targets are sufficient and cheaper. The cost of using plain manifests is lower than the cost of fighting an Operator with the wrong abstractions baked into it.

## When the time comes

When we do write the Operator, this is roughly the shape we expect.

### Deployment

A peer top-level component, `retrieval-hub-operator/`, with the same Containerfile / Makefile / openshift.yaml structure as the other peer components. Built remotely on an x86_64 host, deployed as its own Deployment in a cluster-namespace appropriate for an Operator (typically `openshift-operators` or a dedicated namespace). It runs with a ServiceAccount that has the cluster-scoped permissions it needs to manage retrieval-hub instances across whatever namespaces the cluster admin authorizes.

### Framework choice

Two real options:

- **`kopf`** — a Python framework for Kubernetes Operators. The same language as the rest of retrieval-hub. Lower ceremony, faster iteration, easier to have one team own. Mature and battle-tested.
- **`operator-sdk`** with the Helm or Ansible plugins, or with Go. Heavier, more integration with the broader OpenShift Operator ecosystem (OperatorHub, OLM). Right answer if we want to ship retrieval-hub as a certified OpenShift Operator on OperatorHub.

The working assumption is **`kopf`** for v1, with the option to migrate to a Go operator-sdk implementation if we ever want OperatorHub certification. The migration cost is real but bounded — the CRDs themselves are language-agnostic.

### CRDs

Three Custom Resources, in roughly increasing scope:

**`RetrievalHub`** (cluster-scoped or namespace-scoped, TBD) — represents a deployed instance of retrieval-hub. Spec includes:
- Versions of each peer component (mcp, auth, ui)
- Storage configuration (Postgres connection, MinIO endpoint)
- Auth backend selection (`local` / `openshift_oauth` / `oidc_external` / `external_jwt_validator`)
- vLLM endpoint reference
- AI Assets integration toggle
- Resource budgets for ingestion runs
- Headline LLMs

The Operator reconciles this into the underlying Deployments, Services, Routes, ConfigMaps, and Secrets. Editing the CR is how an admin upgrades a component, switches auth backends, changes the headline LLM list, etc. — without touching individual Kubernetes objects.

**`Source`** — represents a source in the catalog, declared as a Kubernetes object. Spec includes the source's recipe, rewriter metadata, sample prompts, access policy, refresh cadence. The Operator reconciles this into a catalog entry by calling the catalog's API. This is what lets infrastructure-as-code teams manage sources through GitOps (ArgoCD, Flux) the same way they manage everything else in their cluster.

**`RewriterPrompt`** (only relevant for the rare override case) — represents a rewriter prompt object. Same idea as `Source` — GitOps-managed prompts.

The Operator does **not** own ingestion runs or eval runs as CRDs. Those are operational events, not declarative state, and shoehorning them into the reconciliation model would be a category error. They stay as the existing run model managed through the SDK / CLI / UI.

### Reconcile loops

Standard Operator pattern: watch CRs, compute desired state, diff against actual state, apply diff. Specifically:

- A `RetrievalHub` reconciler watches one CR per instance, and on every change recomputes the desired Deployments / Services / Routes / ConfigMaps and applies them. This is the path that handles version upgrades, configuration changes, and rolling restarts.
- A `Source` reconciler watches `Source` CRs and pushes their contents into the catalog through the catalog API (using a service-account JWT issued or validated by the configured auth backend). On startup, the reconciler does a sweep to make sure every catalog entry that came from a CR is still in sync.
- A `RewriterPrompt` reconciler does the same thing for override prompt objects.

Reconciliation is **idempotent** and **non-destructive**: if an admin manually edits a deployment that the Operator manages, the Operator restores the desired state from the CR (with a warning event). If a catalog entry exists that wasn't created from a `Source` CR, the Operator leaves it alone — it does not delete catalog entries that weren't declared through the Operator.

### Upgrade strategy

The Operator supports two upgrade modes for the retrieval-hub instance it manages:

- **Rolling** — peer components are upgraded one at a time, with health-check gates between each. The default for production.
- **Recreate** — the whole instance is taken down and brought back up. Faster, but causes downtime. Used for dev environments and for breaking changes that require coordinated upgrades.

The Operator also handles **schema migrations** for the catalog database. When upgrading to a version of the core library that ships new alembic migrations, the Operator runs the migrations as a Kubernetes Job before starting the new component versions. If the migrations fail, the upgrade is aborted and the previous version stays running.

## The boundary the Operator does not cross

A few things the Operator is **not** for, even after it exists:

- It is not the place for source-level access policy. That stays in the catalog, enforced by the core library.
- It is not the place for eval gating. Eval results live in the catalog, and the publish gate is enforced by the catalog code, not by the Operator.
- It is not the place for ingestion orchestration. Ingestion runners are their own thing.
- It is not a substitute for the SDK or CLI. Source owners and agent developers use those; the Operator is for *deployment-level* operations performed by a cluster admin.

The mental model: the Operator manages the *deployment* of retrieval-hub. Everything else continues to work the way it works in the non-Operator deployment.

## What's Decided

- **The Operator is deferred.** We do not write it until plain manifests + Kustomize overlays start hurting and the configuration surface has stabilized.
- **`kopf` is the working framework choice** for the eventual implementation, with operator-sdk in Go as the migration target if we ever pursue OperatorHub certification.
- **Three CRDs** — `RetrievalHub`, `Source`, `RewriterPrompt` — covering deployment configuration and declarative source management, but not operational events (ingestion runs, eval runs).
- **Reconciliation is idempotent and non-destructive.** Catalog entries not created via CR are left alone.
- **Schema migrations run as a Job before component upgrades.**
- **The Operator manages deployment, not the catalog's domain logic.**

## What's Open

- **Whether the Operator should be cluster-scoped, namespace-scoped, or both.** Real clusters want both modes. Decide when there's a real install to do.
- **The exact Source CRD shape.** It will mirror the catalog model in [`catalog.md`](catalog.md), but the conversion between YAML manifest and database row needs careful design — round-trips, defaulting, validation, error messages.
- **OperatorHub certification.** Real value if we want retrieval-hub installable from OperatorHub, real cost in the form of moving to operator-sdk + Go. Defer until there's a customer asking.
- **GitOps story.** ArgoCD / Flux integration is a function of the CRDs being well-designed; the Operator doesn't need to know about ArgoCD specifically. But documenting the GitOps pattern is its own work.
- **Backup and restore.** Probably belongs in the Operator (a `Backup` CR that snapshots the Postgres database and the MinIO checkpoint store?), probably not in v1 of the Operator.
- **All of this, fundamentally.** This doc is a sketch. Real Operator design happens when the conditions in "Why this is deferred" are met.
