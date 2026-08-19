# retrieval-hub

A catalog-driven retrieval platform for AI agents. Every queryable corpus is published as a versioned *source* with a recipe, eval scores, a per-source semantic layer, access policy, and lineage. Agents consume sources through six MCP tools; humans curate sources through an admin UI and a CLI built on the same core library.

Each source carries a **per-source semantic layer** that data owners control: entity definitions, relationship hints, metric definitions, abbreviation glossaries, and vocabulary mappings. The platform's query rewriter uses this semantic context to translate user queries into domain-specific terminology before retrieval, measurably improving hit rates on lay-language queries. The semantic layer is general-purpose and works for any domain (clinical, code, legal, etc.).

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

**[Why platform-managed retrieval](docs/vision-and-roadmap.md#why-platform-managed-retrieval)** makes the case for treating retrieval as a platform concern rather than a per-team bespoke effort. It covers governance, access control, compliance, observability, forensic reconstruction, quality transparency, and the "accidental platform" problem.

**[Provenance posture](docs/vision-and-roadmap.md#provenance-posture)** explains how retrieval-hub produces provenance-aware responses that a trust framework can verify, aligned to the [Trust Bricks](https://wjatx.github.io/trust-bricks/) PTC specification. This is the security differentiator: most retrieval systems return bare chunks with no basis for trust. retrieval-hub returns chunks with content hashes, source classifications, ingestion lineage, and optional cryptographic signatures.

## Understand how

**[MCP tool surface](docs/vision-and-roadmap.md#mcp-tool-surface)** describes the six tools agents use: `list_sources`, `describe_source`, `retrieve`, `refine`, `write`, and `request_access`. The design principle is that agents speak in intent ("get me data relevant to this query") and the source adapter translates intent into mechanism (vector search, text-to-SQL, graph traversal) based on the source's family.

**[Architecture](docs/ARCHITECTURE.md)** is the full system overview: components, data flows, deployment topology, integration points. Start here for how the pieces fit together.

**[Catalog data model](docs/catalog.md)** specifies sources, recipes, physical indexes, rewriter metadata, eval results, and agent write policies. This is the heart of the platform.

## Understand where it's going

**[Vision and roadmap](docs/vision-and-roadmap.md)** is the full positioning document: the organizational case, provenance posture, MCP design, data residency, source onboarding, and phased build plan. Start here for the big picture.

**[Systems index](docs/SYSTEMS.md)** lists every subsystem with its current status (Implemented, Skeleton, Design, or TBD) and links to the relevant design doc.

## Quick start (full demo)

End-to-end: start databases, ingest a corpus, query it, and run the MCP server. Requires Python 3.11+, [Podman](https://podman.io/), and [Ansible](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html) (for the local dev playbooks).

```bash
# 1. Clone and set up
git clone https://github.com/rdwj/retrieval-hub.git
cd retrieval-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ingest]"
pip install -e retrieval-hub-mcp/

# 2. Start local Postgres (catalog on :5434, pgvector on :5433)
scripts/step4_local_up.sh

# 3. Apply catalog migrations
make migrate

# 4. Ingest the VA CPG clinical guidelines corpus
python scripts/ingest_va_cpg.py

# 5. Seed query-rewriter metadata (vocabulary mappings, sample queries)
python scripts/seed_va_cpg_rewriter_metadata.py

# 5b. Seed semantic layer (entity definitions, metrics, abbreviations)
python scripts/seed_va_cpg_semantic_context.py

# 6. Query the corpus
python scripts/query_va_cpg_demo.py "what does the VA CPG recommend for PTSD treatment"

# 7. Test the query rewriter against gpt-oss-120b
python scripts/test_rewriter.py --query "high blood sugar after a meal"

# 8. Start the MCP server (streamable-http on :8000)
python -m retrieval_hub_mcp
```

Step 4 requires the VA CPG corpus files in a sibling `retrieval-hub-data-sources/` directory. If you don't have the corpus, skip steps 4-6 and ingest the code source instead:

```bash
python scripts/ingest_code_repo.py --repo rdwj/retrieval-hub
python scripts/query_code_demo.py "how does the retrieval adapter work"
```

## Quick start (core library only)

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
├── src/retrieval_hub/        # core library (models, schemas, adapters, ingestion, rewriter, semantic layer)
├── retrieval-hub-mcp/        # MCP server (list_sources, describe_source, retrieve)
├── retrieval-hub-ui/         # PatternFly catalog UI (React + Vite)
├── retrieval-hub-bff/        # backend-for-frontend (query playground)
├── retrieval-hub-auth/       # auth service (OAuth 2.1, JWT)
├── prompts/                  # YAML prompt templates (rewriter, etc.)
├── scripts/                  # ingestion, query demos, rewriter smoke test
├── alembic/                  # database migrations
├── tests/                    # unit tests for the core library
├── docs/                     # architecture, subsystem designs, roadmap
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
