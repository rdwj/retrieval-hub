# CLI (`retrieval-hub-cli`)

The CLI is the human-driven command-line interface to retrieval-hub. It is built on the SDK, lives in its own peer component (`retrieval-hub-cli/`), and exists for the cases where the UI is the wrong tool: scripting, ad-hoc ops, source-owner workflows that benefit from being in the editor, debugging from a shell, automation in pipelines.

This document describes the command surface, how it's organized, the conventions, and what the common workflows look like. The implementation is small — most commands are five lines that delegate to the SDK — but the *shape* of the command surface is what makes the CLI feel coherent.

## Where it lives

`retrieval-hub-cli/` is a peer top-level component in the repo, with its own `Containerfile`, `pyproject.toml`, and tests. It is distributed as:

- A `pip install retrieval-hub-cli` (or `pipx install retrieval-hub-cli`) Python package — the primary distribution path.
- A container image, for callers who want to run it inside a Job or a Tekton Task without having a Python environment to manage.

The CLI imports the SDK. It does **not** import the core library. If a CLI command needs to do something the SDK doesn't expose, the right answer is to add the operation to the SDK first, then have the CLI call it. This keeps the layering honest.

## Conventions

A few conventions apply to every command in the CLI. They are deliberately the same as memory-hub's CLI so that anyone who has used one feels at home in the other.

- **Command shape**: `retrieval-hub <noun> <verb> [args] [--flags]`. Nouns are domain objects (`source`, `recipe`, `metadata`, `run`, etc.); verbs are actions (`list`, `show`, `create`, `ingest`, `publish`).
- **Output format defaults to human-readable.** Tables for collections, key-value blocks for single objects, color/emphasis where the terminal supports it.
- **`--json`** on any command produces structured JSON suitable for piping into `jq` or another tool. CLI output is split into "what humans see" and "what scripts see" by this single flag, not by separate command variants.
- **`--quiet`** suppresses informational output, leaving only errors and the final result. Useful in pipelines.
- **`--verbose` / `-v`** prints what the CLI is doing under the hood (which SDK calls, which auth flow, etc.). Multiple `-v`s increase verbosity.
- **`--help`** at every level. `retrieval-hub source --help` lists `source` verbs; `retrieval-hub source ingest --help` shows arguments and examples.
- **Exit codes**: 0 for success, non-zero for error. The non-zero codes are stable and documented (`retrieval-hub --help-exit-codes`).
- **Auth via env vars**, inherited directly from the SDK. The CLI does not invent its own auth configuration — if the SDK works, the CLI works.

The CLI is built with `typer` (which is built on `click`) for ergonomic command definition. This is the same toolkit memory-hub's CLI uses, so the commits, the test patterns, and the help-text style transfer cleanly.

## Commands by persona

The command surface is organized by domain object, but it's easier to think about by persona. Three personas use the CLI, in roughly this order of weight.

### Source owner

The heaviest user. Source owners use the CLI to manage their sources end-to-end without going through the UI when they prefer the editor.

**Create a source from a recipe file:**
```
retrieval-hub source create \
    --recipe ./va-cpg-recipe.yaml \
    --slug va-clinical-guidelines \
    --owner-team clinical-informatics
```

The recipe file is a YAML document of the same shape as the `recipe` field in [`catalog.md`](catalog.md), authored in the source owner's editor. The CLI validates it, posts it to the SDK, and reports the new source's id and URL on the admin UI for one-click follow-up.

**Inspect a source:**
```
retrieval-hub source show va-clinical-guidelines
retrieval-hub source show va-clinical-guidelines --json
```

The human format prints a structured block: name, family, status, recipe headline, retrieval pattern declaration, headline evals, last refresh. The `--json` form is the full source record.

**Trigger an ingestion run:**
```
retrieval-hub source ingest va-clinical-guidelines
retrieval-hub source ingest va-clinical-guidelines --refresh-mode incremental
retrieval-hub source ingest va-clinical-guidelines --dry-run --sample 100
```

Ingestion is long-running; the CLI streams stage events from the SDK and prints them as they arrive. Ctrl-C detaches the CLI from the run but does **not** cancel the run — to cancel, use `retrieval-hub run cancel <run-id>`.

**Edit and test the rewriter metadata:**
```
retrieval-hub metadata edit va-clinical-guidelines
# opens $EDITOR on the current rewriter_metadata yaml; writes it back on save

retrieval-hub metadata test va-clinical-guidelines \
    --query "what should I do for someone with high blood sugar after a meal"

retrieval-hub metadata test-suite va-clinical-guidelines
# runs the source's frozen test cases and prints pass/fail

retrieval-hub metadata diff va-clinical-guidelines --vs-version 3
# diff vs a previous metadata version
```

This is the editor-driven counterpart to the UI's rewriter metadata editor. Source owners who live in vim/emacs/cursor will use this path; the UI is for everyone else.

**Publish, retire, unpublish:**
```
retrieval-hub source publish va-clinical-guidelines
# enforces the publish gate (healthy index, eval, sample prompt) before publishing

retrieval-hub source unpublish va-clinical-guidelines
retrieval-hub source retire va-clinical-guidelines --reason "superseded by va-cpg-2026"
```

Publish enforces the same gates the UI enforces — they live in the core library, so the CLI inherits them. If a gate fails, the CLI prints exactly which gate and what would need to be done to satisfy it.

**Sample prompts and access policy:**
```
retrieval-hub source set-sample-prompt va-clinical-guidelines \
    --llm-family granite-3-* \
    --file ./prompts/va-granite.txt

retrieval-hub source set-access va-clinical-guidelines \
    --visibility restricted \
    --allowed-groups clinical-agents,reviewers
```

### Agent developer

The agent developer's CLI use is mostly browse and test. They are not allowed to mutate.

**Browse the catalog:**
```
retrieval-hub source list
retrieval-hub source list --family clinical_document
retrieval-hub source list --has-rewriter --visibility public
retrieval-hub source list --json | jq '.[] | select(.evals[0].score.recall_at_5 > 0.75)'
```

**Look at a source:**
```
retrieval-hub source show rh-product-docs
retrieval-hub source recipe rh-product-docs                     # just the recipe
retrieval-hub source evals rh-product-docs                       # just the eval results
retrieval-hub source sample-prompts rh-product-docs --llm granite-3.3-8b-instruct
retrieval-hub source mcp-config rh-product-docs                  # MCP config snippet for an agent runtime
```

`mcp-config` is the "copy MCP config" affordance that the UI exposes as a button — rendered to the terminal so it can be piped or copy-pasted into an agent runtime configuration file.

**Test a query:**
```
retrieval-hub query rh-product-docs "how do I configure OpenShift Pipelines"
retrieval-hub query rh-product-docs "..." --top-k 20 --pattern vector_with_filters --filter document_type=guide
retrieval-hub query rh-product-docs "..." --use-rewrite
retrieval-hub rewrite va-clinical-guidelines "what should I do for someone with high blood sugar after a meal"
```

`query` is the playground equivalent — paste a question, see the hits, with lineage information on each hit. `rewrite` calls the rewriter directly without retrieval, useful for inspecting what the rewriter is producing.

### Platform admin

Platform admins use the CLI for audit, governance, and incident response. The commands are read-mostly with a few targeted mutators.

**Audit:**
```
retrieval-hub audit source va-clinical-guidelines --since 2026-04-01
retrieval-hub audit identity client:agent-langgraph-prod-01 --since 2026-04-06
retrieval-hub audit writes --source clinical-notes-staging --since 24h
```

These query the audit trail described in [`auth.md`](auth.md) and [`catalog.md`](catalog.md). Output is structured (tables for human, JSON for scripts).

**Access review:**
```
retrieval-hub source access-review --visibility restricted
# lists every restricted source, its allowed_groups, and the most recent access decisions
```

**Disable / re-enable a source in an incident:**
```
retrieval-hub source disable va-clinical-guidelines --reason "incident-2026-04-07"
retrieval-hub source enable va-clinical-guidelines
```

Disable is a soft retire that returns a structured `source_disabled` error on retrieval but does not change lineage or destroy data. This is what platform admins reach for in an incident; full retire is for when a source is truly going away.

**System health:**
```
retrieval-hub health
# checks: catalog DB reachable, vLLM reachable, auth service reachable,
#         backend(s) reachable, recent ingestion run failures, oldest stale source
```

## Configuration files

Most users will be fine with env vars alone. For users who manage multiple retrieval-hub deployments (dev, stage, prod), the CLI supports a config file at `~/.config/retrieval-hub/config.yaml`:

```yaml
profiles:
  dev:
    url: https://retrieval-hub-mcp.dev.example.com
    auth_url: https://retrieval-hub-auth.dev.example.com
    client_id: ${RETRIEVAL_HUB_DEV_CLIENT_ID}
    client_secret: ${RETRIEVAL_HUB_DEV_CLIENT_SECRET}
  prod:
    url: https://retrieval-hub-mcp.prod.example.com
    auth_url: https://retrieval-hub-auth.prod.example.com
    client_id: ${RETRIEVAL_HUB_PROD_CLIENT_ID}
    client_secret: ${RETRIEVAL_HUB_PROD_CLIENT_SECRET}

default_profile: dev
```

Profile selection is `retrieval-hub --profile prod ...` or `RETRIEVAL_HUB_PROFILE=prod`. Env vars override profile fields, so a profile can be a "template" that env vars complete.

In the inherited-auth case, the profile uses `token` (or `token_command` to call out to a token-providing tool) instead of `client_id`/`client_secret`.

## Output examples

A `source show` looks like this (color stripped):

```
$ retrieval-hub source show va-clinical-guidelines

Source: VA Clinical Practice Guidelines
  slug:        va-clinical-guidelines
  family:      clinical_document
  status:      published
  visibility:  public
  owner:       clinical-informatics

Recipe (v2):
  parser:      docling + clinical-postprocessor
  chunker:     clinical-section, 512 tok / 64 overlap
  embedding:   nomic-embed-text-v1.5 (768d)
  backend:     pgvector  (idx_va_cpg_v2)

Retrieval:
  default:     vector_ann
  supported:   vector_ann, vector_with_filters
  top_k_max:   50

Active index:
  pidx_01HXZ...  built 2026-04-05  18,402 docs  health: ok

Rewriter:
  enabled:        yes (uses shared core rewriter)
  metadata v:     4
  vocab mappings: 53
  sample queries: 12
  default LLM:    granite-3.3-8b-instruct

Headline evals:
  granite-3.3-8b-instruct   R@5: 0.74   MRR: 0.68   (rewrite +0.27 R@5)
  llama-3.3-70b-instruct    R@5: 0.78   MRR: 0.71   (rewrite +0.22 R@5)
  gpt-4o                    R@5: 0.79   MRR: 0.74   (rewrite +0.18 R@5)

Last refreshed: 2026-04-05 (cadence: weekly)
Agent writes:   not allowed
```

A `query` with the playground renderer:

```
$ retrieval-hub query va-clinical-guidelines "what should I do for high blood sugar after a meal" --use-rewrite

Rewrites used (3):
  1. VA/DoD clinical practice guideline postprandial hyperglycemia management
  2. type 2 diabetes mellitus postprandial glucose treatment recommendation
  3. insulin therapy postprandial glucose elevation

Hits (10, deduplicated):
  1. [0.91] VA/DoD CPG: Management of Type 2 Diabetes Mellitus (2023)
            §4.2 Postprandial Glucose Targets
            "Postprandial glucose levels should be targeted at..."
            pidx_01HXZ... · recipe v2

  2. [0.87] VA/DoD CPG: Management of Type 2 Diabetes Mellitus (2023)
            §5.1 Insulin Therapy in Adults
            ...
```

These are the kinds of outputs a source owner or agent developer wants to glance at. `--json` produces the structured form.

## What's Decided

- **`retrieval-hub-cli/` is its own peer component**, distributed as a PyPI package and a container image.
- **Built on the SDK**, never imports the core library directly.
- **`<noun> <verb>` command shape**, with `--json` for scripting and `--help` at every level.
- **Auth via env vars, inherited from the SDK**, with optional config file profiles for multi-environment users.
- **Source-owner commands cover the full lifecycle**: create, ingest, edit recipe, edit rewriter metadata, test rewrites, publish, retire, set sample prompts, set access.
- **Agent-developer commands are read-mostly**: list, show, query, rewrite, mcp-config snippet generation.
- **Platform-admin commands cover audit, access review, disable/enable, system health.**
- **Streaming for long-running operations** (ingestion runs, multi-source queries), with Ctrl-C detaching cleanly without cancelling the underlying work.
- **Built with `typer`**, same as memory-hub.

## What's Open

- **Whether the CLI ships shell completion** out of the box. `typer` makes it easy; the question is whether we maintain it for bash, zsh, fish, or just zsh. Probably zsh + bash.
- **Whether `metadata edit` should round-trip through a temp file or use a server-side editing flow.** Round-trip is simpler; server-side gives optimistic-locking semantics for free.
- **The set of operations available against multiple sources at once** (`retrieval-hub source list ... | xargs retrieval-hub source ingest`). Round-1 commands are mostly single-source; bulk operations are useful but shouldn't be added without thinking about safety.
- **Whether `retrieval-hub source disable` is the right verb** vs. `quarantine` or similar. "Disable" is clear but slightly overloaded.
- **Pre-built shell aliases for the most common commands.** Tempting to ship a `rh` short alias; reasonable to defer to the user's own shell config.
