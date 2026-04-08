# Platform Component Pattern

A reusable shape for building an AI-layer component that ships as an application on OpenShift AI. The pattern is the one used by `memory-hub`: a core service exposed through MCP, packaged as a Python SDK, driven by a CLI, administered through a small web UI, and managed (eventually) by a Kubernetes Operator. Every piece is its own deployable, but they live together in one repo and share conventions.

The point of writing this down is so that the *next* component (retrieval-hub, eval-hub, whatever-hub) doesn't have to rediscover the layout. None of this is sacred — diverge where the new domain demands it — but starting from a known shape removes a lot of decisions.

## Repo Layout

A single repository with peer top-level component directories. Each component is independently buildable, deployable, and (where it makes sense) independently versioned.

```
<project>/
├── src/<project>/          # Core library: models, services, storage
├── <project>-mcp/          # MCP server (FastMCP 3, streamable-http)
├── <project>-auth/         # Auth service (OAuth2 / JWT issuer)
├── <project>-ui/           # Admin UI (frontend + backend subdirs)
├── <project>-cli/          # End-user CLI
├── sdk/                    # Python SDK published to PyPI
├── deploy/                 # Shared deploy assets (DBs, object store, etc.)
├── alembic/                # DB migrations for the core lib
├── docs/                   # ARCHITECTURE.md, SYSTEMS.md, per-subsystem docs
├── tests/                  # Tests for the core lib
├── ideas/                  # Ideation notes (not docs)
├── retrospectives/         # Retros after major efforts
├── CLAUDE.md               # Project conventions for the agent
├── README.md
├── Makefile
└── pyproject.toml          # Core lib package metadata
```

The core library under `src/<project>/` is the only thing the other components import directly. Everything else talks to the running system over the network — typically the MCP server. This keeps the deployable boundaries honest: if the UI ends up importing from the MCP server directory, you've already drifted from the pattern.

Each peer component (`*-mcp/`, `*-auth/`, `*-ui/`, etc.) carries its own `Containerfile`, `Makefile`, `openshift.yaml`, `deploy.sh`, `pyproject.toml`, `requirements.txt`, `src/`, and `tests/`. They are mini-projects, not modules. This is intentional: it lets each one be built remotely, deployed independently, owned by a different person, and (if it ever matters) extracted to its own repo with no surgery.

## The Components

**Core library (`src/<project>/`).** SQLAlchemy models, the service layer, storage adapters, embedding integration, anything domain-specific. This is the only place "the truth" of the domain lives. The MCP server, auth service, UI backend, and ingestion pipelines all consume it. Tests live in the top-level `tests/`.

**MCP server (`<project>-mcp/`).** The primary external surface. Built with FastMCP 3 over streamable-http (SSE is deprecated). Scaffolded from the fips-agents MCP template — never hand-rolled, and never delegated to a sub-agent, because the template carries test structure, permission handling, and registration patterns that matter. Tools are added through the `/plan-tools` → `/create-tools` → `/exercise-tools` → `/write-system-prompt` → `/update-docs` → `/deploy-mcp` workflow. Agents (Claude Code, LlamaStack, Kagenti, LangGraph, etc.) connect here and never touch storage directly.

**Auth service (`<project>-auth/`).** A small FastAPI service that issues short-lived JWTs via OAuth 2.1 `client_credentials` grant. Having it as its own deployable means the MCP server, SDK, and UI all share one identity story without dragging auth code into each of them. It also means the auth substrate can be swapped (Keycloak, OpenShift OAuth, an internal IdP) without touching the rest of the system.

**Admin UI (`<project>-ui/`).** Two subdirs: `frontend/` (the SPA) and `backend/` (a thin BFF that calls the core service over the wire, never directly). The UI is for operators and administrators — inspecting state, configuring policy, watching audit trails. It is *not* the agent's interface; agents go through MCP.

**CLI (`<project>-cli/`).** A Python CLI for humans — scripting, debugging, one-off ops. Builds on the SDK so it stays thin. Distributed as a `pip install` (or `pipx install` if it grows commands worth isolating).

**SDK (`sdk/`).** Published to PyPI as `<project>` (the friendly name). Wraps the MCP server with a typed Python client. Both async and sync entry points (`method` and `method_sync`). Reads credentials from env vars by default (`<PROJECT>_URL`, `<PROJECT>_CLIENT_ID`, `<PROJECT>_CLIENT_SECRET`) and handles OAuth token caching/refresh transparently. The SDK is what most consumers actually touch — it should feel pleasant.

**Deploy assets (`deploy/`).** Shared infra manifests: PostgreSQL (with pgvector when semantic search is needed), MinIO for object storage, anything else the whole system needs that isn't a `<project>-*` component. Each component's own deployment lives in *its* directory, not here.

**Operator (future).** A Kubernetes Operator (Python via `kopf`, or `operator-sdk`) that owns the lifecycle of the whole thing through CRDs. This is usually the last subsystem to land — start with plain manifests, graduate to an Operator once the configuration surface stabilizes. Manage it as its own peer component (`<project>-operator/`) when it arrives.

## Storage

PostgreSQL is the default for everything that needs structured persistence — the OOTB OpenShift PostgreSQL operator handles HA, backups, and (importantly) FIPS via OS-level OpenSSL. Add `pgvector` when you need semantic search; you don't need a separate vector DB until you've proven you do. Use `MinIO` for object/document storage. Use Apache AGE or simple adjacency tables for graph relationships before reaching for a dedicated graph database — same evolution path memory-hub took. Migrations live under `alembic/` at the repo root and target the core library's models.

## Documentation Layout

Two files do most of the work in `docs/`:

- **`ARCHITECTURE.md`** is the big picture: a system-overview Mermaid diagram, the data-flow sequence diagrams for the most important operations, the deployment topology, and a "What's Decided vs. What's Open" section that's worth keeping honest. One document, read top-to-bottom.
- **`SYSTEMS.md`** is the subsystem inventory: a table of every subsystem with a one-line description, a link to its detail doc, and a status indicator (`Implemented` / `Design` / `Skeleton` / `TBD`). Define what those statuses *mean* in the same file. Add a dependency-graph Mermaid below the table and a recommended build order. This file is the map; it's how someone new finds their way in.

Each subsystem then gets its own doc (`memory-tree.md`, `governance.md`, `mcp-server.md`, etc.) under `docs/`. Integration with external systems (LlamaStack, Kagenti, etc.) gets a subdirectory. Keep `ideas/` for half-formed thoughts and `retrospectives/` for post-effort reflection — neither belongs in `docs/`.

## Conventions

The conventions are inherited from the global CLAUDE.md but worth restating because they shape how the components fit together:

- Red Hat UBI9 base images everywhere. Podman, not Docker. `Containerfile`, not `Dockerfile`.
- Build remotely on x86_64 when targeting OpenShift from a Mac (`--platform linux/amd64` if building locally).
- FIPS compliance assumed unless told otherwise — delegate crypto to OS-level OpenSSL and pick libraries accordingly (e.g. Go 1.24's FIPS 140-3 module for MinIO).
- FastAPI for HTTP services, FastMCP 3 for MCP, `pytest` for tests with an 80% coverage target.
- `chmod 644` on source files before container builds (the Write tool creates 600).
- Conventional commits scoped by subsystem: `mcp-server: Add semantic_search tool`, `sdk: Switch to async token refresh`.
- The agent uses `/pre-commit` before committing and follows the sub-agent delegation rules in the global `CLAUDE.md`.

## When to Follow This Pattern (and When Not)

Follow it when you're building a *platform component* — something other agents and humans will integrate with, that needs its own identity, its own admin surface, its own deploy story, and that you expect to evolve over months. The cost of the layout is real (six-ish deployables to keep in sync) and only pays off at that scale.

Don't follow it for a single-purpose service or an experiment. A FastAPI app in one directory with a Containerfile is fine; you can grow into this pattern later by promoting the original code to `src/<project>/` and adding peer directories as the need appears. The shape is additive.
