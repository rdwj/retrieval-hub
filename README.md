# retrieval-hub

A catalog-driven retrieval platform for AI agents. Every queryable corpus is published as a versioned *source* with a recipe, eval scores, sample prompts, rewriter metadata, access policy, and lineage. Agents consume sources through six MCP tools; humans curate sources through an admin UI and a CLI built on the same core library.

**Status: early development.** Design documentation and a scaffolded core library are in place. See [`docs/SYSTEMS.md`](docs/SYSTEMS.md) for the build order and the status of every subsystem.

## See it

The fastest way to understand what retrieval-hub does is to run the UI mockup. It uses static data (no backend required) but shows the full catalog experience: source cards, detail views with eval scores and rewriter config, a query playground, and an admin dashboard.

Prerequisites: [Node.js](https://nodejs.org/) 18+.

```bash
git clone https://github.com/rdwj/retrieval-hub.git
cd retrieval-hub/retrieval-hub-ui/frontend
npm install
npm run dev
```

Open http://localhost:5173. The landing page has a guided tour that walks through the key features.

## Understand why

**[Why platform-managed retrieval](docs/operatorhub-roadmap.md#why-platform-managed-retrieval)** makes the case for treating retrieval as a platform concern rather than a per-team bespoke effort. It covers governance, access control, compliance, observability, forensic reconstruction, quality transparency, and the "accidental platform" problem.

**[Provenance posture](docs/operatorhub-roadmap.md#provenance-posture)** explains how retrieval-hub produces provenance-aware responses that a trust framework can verify, aligned to the [Trust Bricks](https://wjatx.github.io/trust-bricks/) PTC specification. This is the security differentiator: most retrieval systems return bare chunks with no basis for trust. retrieval-hub returns chunks with content hashes, source classifications, ingestion lineage, and optional cryptographic signatures.

## Understand how

**[MCP tool surface](docs/operatorhub-roadmap.md#mcp-tool-surface)** describes the six tools agents use: `list_sources`, `describe_source`, `retrieve`, `refine`, `write`, and `request_access`. The design principle is that agents speak in intent ("get me data relevant to this query") and the source adapter translates intent into mechanism (vector search, text-to-SQL, graph traversal) based on the source's family.

**[Architecture](docs/ARCHITECTURE.md)** is the full system overview: components, data flows, deployment topology, integration points. Start here for how the pieces fit together.

**[Catalog data model](docs/catalog.md)** specifies sources, recipes, physical indexes, rewriter metadata, eval results, and agent write policies. This is the heart of the platform.

## Understand where it's going

**[OperatorHub roadmap](docs/operatorhub-roadmap.md)** maps the arc from the current state to an installable Kubernetes operator on operatorhub.io, in six phases. Includes the phased build plan, risk register, and dependency graph.

**[Systems index](docs/SYSTEMS.md)** lists every subsystem with its current status (Implemented, Skeleton, Design, or TBD) and links to the relevant design doc.

## Quick start (core library)

```bash
python3 -m venv .venv
source .venv/bin/activate

make install      # install the core library + dev tooling
make test         # run the unit test suite
make migrate      # apply alembic migrations against $RETRIEVAL_HUB_DB_URL
```

The default database URL points at a local Postgres for development; override it via the `RETRIEVAL_HUB_DB_URL` environment variable.

## Layout

```
retrieval-hub/
├── src/retrieval_hub/        # core library (models, schemas, adapters, ingestion)
├── retrieval-hub-ui/         # PatternFly catalog UI (React + Vite)
├── retrieval-hub-auth/       # auth service (OAuth 2.1, JWT)
├── alembic/                  # database migrations
├── tests/                    # unit tests for the core library
├── docs/                     # architecture, subsystem designs, roadmap
├── ideas/                    # project origin: problem statement, vision, scope
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
