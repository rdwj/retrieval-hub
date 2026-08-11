# retrieval-hub

retrieval-hub is a catalog-driven retrieval platform: every queryable corpus is published as a versioned *source* with a recipe, evals, sample prompts, rewriter metadata, access policy, and lineage. Agents and humans both consume sources through a single MCP surface; humans curate sources through an admin UI and a CLI built on top of the same core library.

**Status: early development.** This repository currently contains design documentation under `docs/` and a scaffolded core library implementing the catalog data model. Peer components (MCP server, auth service, admin UI, CLI, SDK) are not yet built. See [`docs/SYSTEMS.md`](docs/SYSTEMS.md) for the build order and the status of every subsystem.

## What this is

The system shape, the components, and the design rationale all live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The catalog data model — the heart of the platform — is specified in [`docs/catalog.md`](docs/catalog.md). The repo layout is the platform-component pattern from [`docs/PLATFORM_COMPONENT_PATTERN.md`](docs/PLATFORM_COMPONENT_PATTERN.md): the core library lives at `src/retrieval_hub/`, and peer components (`retrieval-hub-mcp/`, `retrieval-hub-ui/`, etc.) are added as separate top-level directories as they come online.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate

make install      # install the core library + dev tooling
make test         # run the unit test suite
make migrate      # apply alembic migrations against $RETRIEVAL_HUB_DB_URL
```

The default database URL points at a local Postgres for development; override it via the `RETRIEVAL_HUB_DB_URL` environment variable.

## Running the UI demo

The `retrieval-hub-ui/` directory contains a PatternFly mockup of the catalog interface. It runs entirely on static data — no backend required.

A demo instance may be available on request. The landing page explains the value proposition and includes a guided tour that walks through the key features. The catalog, source detail views, query playground, and admin page are all available from the nav.

### Running locally

Prerequisites: [Node.js](https://nodejs.org/) 18+.

```bash
git clone https://github.com/rdwj/retrieval-hub.git
cd retrieval-hub/retrieval-hub-ui/frontend
npm install
npm run dev
```

Then open http://localhost:5173.

## Layout

```
retrieval-hub/
├── src/retrieval_hub/        # core library (models, schemas, policy)
├── retrieval-hub-ui/         # PatternFly catalog UI (React + Vite)
├── retrieval-hub-auth/       # auth service
├── alembic/                  # database migrations
├── tests/                    # unit tests for the core library
├── docs/                     # architecture, subsystem designs
├── pyproject.toml
├── Makefile
└── Containerfile             # core-library image (UBI9 Python 3.11)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding conventions, and the PR workflow.

## License

Copyright 2026 Red Hat, Inc. Licensed under the [Apache License, Version 2.0](LICENSE).

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md). Do not file public issues for security concerns.

## Code of Conduct

This project follows the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md).
