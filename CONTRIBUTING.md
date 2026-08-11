# Contributing to retrieval-hub

Thanks for your interest in contributing. This guide covers how the repo is laid out, how to set up a development environment, the conventions we follow, and how to file issues and PRs.

If anything here is unclear, file an issue and tag it `documentation`.

## Repo layout

retrieval-hub is a monorepo following the platform-component pattern. The core library lives at `src/retrieval_hub/` and peer components are added as separate top-level directories. See [`docs/SYSTEMS.md`](docs/SYSTEMS.md) for the per-subsystem inventory and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system overview.

- **Maintainers** have merge rights and own project board triage.
- **Contributors** can file issues, open PRs, and deploy to their own clusters. No approval needed to file issues.

All participation is subject to our [Code of Conduct](CODE_OF_CONDUCT.md).

**Questions and discussion:** use [GitHub Discussions](../../discussions) for questions, ideas, and anything that is not a concrete bug or feature request. Issues are for actionable work items.

## Development setup

### Core library (src/retrieval_hub/)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q
```

### UI (retrieval-hub-ui/frontend/)

```bash
cd retrieval-hub-ui/frontend
npm install
npm run build
```

### Auth service (retrieval-hub-auth/)

```bash
cd retrieval-hub-auth
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q
```

### Local data stores

Ansible playbooks in `deploy/ansible/playbooks/` bring up local PostgreSQL + pgvector instances:

```bash
ansible-playbook deploy/ansible/playbooks/local_all_up.yml
```

## Filing issues

> **Security vulnerabilities are the exception to everything below: do not file a public issue.** Use GitHub's private vulnerability reporting instead. See [`SECURITY.md`](SECURITY.md).

Use issue templates when available (`bug_report`, `feature_request`, `design_proposal`). The rules:

- **Every issue starts in the Backlog column** of the project board. Issues flow Backlog, In Progress, Done.
- **File issues under your own GitHub identity.** Do not add AI attribution to issue authors. Other developers need to know who to contact about an issue; the human owner is the point of contact.
- **No internal-tooling issues on this public repo.** If something internal to your dev environment is broken, mention it in conversation rather than filing a public issue that reveals private infrastructure details.

### Picking up an issue

1. Find an issue in the project board Backlog column. `good first issue` is a reasonable starting point.
2. Assign yourself. If you want to discuss approach first, leave a comment.
3. Move it to In Progress when you start work.
4. Open a PR that links the issue (`Closes #NN` in the PR description).
5. If you cannot finish, unassign yourself and leave a comment summarizing what you learned and where you got stuck.

## Pull requests

1. **Read the relevant design doc first.** Most subsystems have one in `docs/`.
2. **Create a branch off `main`.** Branch names: `<subsystem>/<short-description>` (e.g. `mcp/add-retrieve-tool`) or `issue-NN-<short-description>`.
3. **Keep PRs small and single-purpose.** One issue per PR where possible. If a change grows past ~500 lines of non-generated diff, consider splitting it.
4. **Run the relevant test suite locally** before opening the PR.
5. **CI must pass before merge.** A PR with failing CI will not be merged.
6. **Don't commit secrets.** Run `gitleaks detect --source .` locally before pushing.
7. **Open the PR with a clear description** that links the issue number and references the design doc.
8. **Expect review from a maintainer.** Every PR requires approval from at least one maintainer who is not the author.
9. **Be ready to iterate.** We optimize for the right design, not the fastest merge.

## Commit messages

Use the conventional commit format with a subsystem prefix:

```
subsystem: Description in imperative mood

Optional body explaining the *why*, with context that a future
maintainer reading the log will need.

Closes #NN.
```

Examples:

- `core: Add clinical_document adapter with structure-preserving parsing`
- `mcp: Implement retrieve tool with adapter dispatch`
- `ui: Connect catalog page to BFF backend`

Imperative mood: write "Add foo" not "Adds foo" or "Added foo." Body explains why; the diff explains what.

If your commit was assisted by an AI tool, add an `Assisted-by:` trailer (e.g., `Assisted-by: Claude Code (Opus 4.6)`). Do not add `Co-authored-by:` trailers for AI tools; the human author is the author of record. `Co-authored-by:` is fine (and encouraged) for human pairing.

This project does not require a DCO sign-off or CLA; contributions are accepted under the inbound=outbound Apache-2.0 terms in the License section below.

## Coding conventions

These conventions are enforced by review, not by linters (mostly).

- **Python**: FastAPI for services. Pydantic v2 for data models. SQLAlchemy 2.0 for the database layer. `pytest` for tests. `ruff` for linting where configured.
- **Containers**: Podman, not Docker. `Containerfile`, not `Dockerfile`. Red Hat UBI9 base images only.
- **Architecture**: Build `linux/amd64` containers when targeting OpenShift from a Mac (`podman build --platform linux/amd64`).
- **File permissions**: `chmod 644` source files before container builds. OpenShift's non-root container UIDs cannot read 600-permission files.
- **No early optimization.** Get basic functionality working first. Do not add abstraction for hypothetical future requirements.
- **Don't mock to work around errors.** Let broken things stay visibly broken so they get fixed. Mocks belong in tests, not in production code.
- **Match the existing style.** A new Pydantic model should look like the existing Pydantic models in the same file.

## Documentation expectations

- **Update docs in the same PR as the code change.** A new feature with a stale design doc is worse than a new feature with no doc.
- **`SYSTEMS.md` and `ARCHITECTURE.md` are the repo's front door.** Keep them current. If you add or remove a subsystem, update both.
- **Per-subsystem docs in `docs/`** are the design source of truth. If implementation drifts from design, update the design first or file an issue tracking the drift.

## License

By submitting a contribution, you agree that your contribution will be licensed under the project's [Apache License 2.0](LICENSE).

---

Copyright 2026 Red Hat, Inc. and retrieval-hub contributors. Apache 2.0.
