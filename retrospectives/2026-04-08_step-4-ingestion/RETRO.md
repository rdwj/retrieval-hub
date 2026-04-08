# Retrospective: Step 4 — Real Corpus Ingestion

**Date:** 2026-04-08
**Effort:** Git initialization + incremental commits, step 4 implementation (ingestion pipeline, document adapter, retrieval API, IaC layer, fallback corpus, tests), end-to-end verification subagent run, bug-fix cycle
**Phase:** Storming, first real data test
**Commits:** `0965235`..`8424a72` (all 9 commits on `origin/main` are from this session arc; commits 6–9 are the step 4 work proper: `edb52c0` pipeline, `192fc59` IaC + scripts, `a935ca0` tests/deps, `8424a72` fixes)

## What We Set Out To Do

The foundation retro identified two next steps: initialize git with the foundation baseline (the "fix now" item), and pick between step 3 (MCP server) or step 4 (real corpus). The user picked step 4 with an explicit IaC constraint: "whatever you're going to deploy to the cluster, make a namespace and use an ansible playbook or other iac approach." Keep delegating work to subagents but inspect what they return.

The implicit goal: get from tested-but-empty scaffolds to a running pipeline that embeds real content, stores it in real pgvector, and answers queries with semantically meaningful results. The vertical slice moves from hypothetical to demonstrable.

## What Changed

| Change | Type | Rationale |
|---|---|---|
| IaC-first local dev via Ansible + committed Kubernetes namespace | Good pivot | User-directed mid-session. Local dev and cluster deploy share one automation language from day one. Shell scripts became thin wrappers around `ansible-playbook`. |
| End-to-end verification in a subagent before calling step 4 done | Good pivot | User-initiated suggestion ("are you able to run the ingestion in a sub agent?"). Load-bearing — caught four bugs and produced 5/5 query hits as concrete evidence. |
| Fallback corpus as the primary test path, `--try-network` as opt-in | Good pivot | Reproducibility beat realism for the first verification. Let the worker complete in one run instead of fighting docs.redhat.com rate limits. |
| Incremental commits (5 baseline + 3 step-4 + 1 fix) instead of one blob | Good pivot | Commit history tells a readable story; supports `git bisect` if ever needed. |
| Step 3 (MCP server) held until after step 4 | Scope deferral | User call. MCP server needs real data to develop against; step 4 provides it. Out-of-order vs `SYSTEMS.md`, intentional. |
| `--try-network` against real docs.redhat.com | Scope deferral | Code path exists but untested against real Red Hat docs HTML. Docling behavior on real content is unverified. |
| Production ingestion runners (Tekton/Jobs) | Scope deferral | Hand-run scripts are sufficient for step 4's purpose. Production orchestration lands in the future step 12. |
| First step-4 background worker crashed at tool 52 with an API 500 | Refinement | Infrastructure blip, not a scope issue. Inspected the partial state; the worker's library code was high-quality. Took over directly and finished without relaunching. |
| `deploy/ansible/inventory/local` Jinja-in-INI bug | Refinement | Caught by verification subagent. Fixed in `8424a72`. |
| `deploy/ansible/playbooks/local_all_up.yml` `import_playbook`-inside-tasks bug | Refinement | Caught by verification subagent. Fixed in `8424a72`. |
| `pyproject.toml` `[ingest]` extra missing `einops` | Refinement | `nomic-embed-text-v1.5` loads remote code that imports einops. Caught by verification subagent at model-load time. Fixed in `8424a72`. |
| `load_fallback_corpus` including `README.md` | Refinement | Meta-content about the corpus, not corpus content. Caught by verification subagent. Fixed in `8424a72` with a skip-stem list. |

## What Went Well

- **The platform pattern held up under its first real test.** 5/5 query demos hit the expected document at rank 1, with healthy score gaps to next-best hits (0.827 top vs 0.77x rank 2 on the OAuth query). The data model, adapter dispatch, and retrieval path all work end-to-end against real 768-dimensional embeddings in real pgvector.
- **`retrieval_hub.retrieval.api.query()` is the exact function a future MCP tool will call.** The vertical slice is now one `/plan-tools` workflow away from being reachable through MCP. No rework expected when the tool surface lands.
- **Verification subagent run produced specific, actionable findings.** Four bugs, all with clear causes and mechanical fixes, all fixed same session. This is the retro-and-verification loop working as designed — having high confidence in code is fine when the feedback loops catch what slips through.
- **Recovery from the crashed worker was fast.** ~5 minutes of "what did the worker get done before crashing" investigation before confirming the library code was usable and taking over directly. No drama, no relaunch.
- **IaC layer is structured for both local and cluster from day one.** Ansible playbooks for podman + a committed Kubernetes namespace manifest. When cluster deploy lands in a later round, the automation pattern is already in place.
- **Git init + first push was clean.** Five coherent baseline commits, pre-commit gitleaks scanning, `.gitleaks.toml` allowlist for the known false-positive paths, private GitHub repo at `github.com/rdwj/retrieval-hub`, first push landed without issues.
- **The existing test suite kept working through multiple rounds of edits.** 94 core + 66 auth tests stayed green across enum-name fixes, mypy type argument changes, the fallback corpus fix, and `register.py` changes. Tests did real work.
- **Worker delegation + inspection is a proven pattern.** Three to four workers this session (library scaffold, UI verification context, step-4 initial attempt, step-4 verification). The main agent stayed on coordination and synthesis; workers did focused implementation. When something broke, inspection did its job.

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| `SYSTEMS.md` not updated to reflect step 4 done before step 3 | Follow-up | Update next session; note that both core library and document adapter are verified end-to-end and MCP server is unblocked |
| No root-level "how to run the demo" quick-start in `README.md` | Follow-up | Add a section or a `docs/operations/running-step4-locally.md` next session so a fresh clone can discover the demo flow |
| `--try-network` path never exercised | Follow-up | Run against real docs.redhat.com once to see if Docling + HTTP fetching work on real content |
| Auth service and core library not wired together at runtime | Accept for now | `ValidatedIdentity` ↔ `Identity` mapping exists in code and tests but has not been exercised in a real request path. Step 3 (MCP server) will force this. |
| Cold-start ingestion wall time unknown | Accept | Verification run had the nomic model already cached. First-time run includes a ~500 MB model download. Low risk, just not measured. |
| Query CLI latency dominated by per-invocation model load (~5-7s) | Accept | Expected for a CLI. Long-running MCP server will see sub-100ms per query after first load. |
| Fallback corpus is small (8 docs, 16 chunks, 5125 tokens) | Accept | Small enough to miss chunker edge cases that only surface at scale. Worth stress-testing when a larger corpus is ingested. |
| Root `.gitignore` and `retrieval-hub-auth/.gitignore` not audited for consistency | Accept | Both cover the common cases. Probably fine, unverified. |

## Action Items

- [ ] Update `SYSTEMS.md` to reflect the out-of-order step sequencing and step 4's verified-end-to-end status
- [ ] Add a root-level quick-start section to `README.md` or a `docs/operations/running-step4-locally.md` for demo discoverability
- [ ] Run `--try-network` against real docs.redhat.com once to validate the Docling + HTTP fetching path
- [ ] Step 3 (MCP server skeleton) when ready — the vertical slice is unblocked
- [ ] `/plan-tools` workflow to design the MCP tool inventory against the now-real Red Hat AI content

## Patterns

Reviewed against the foundation retro's "Start / Try / Continue" list.

**From foundation retro, still valid:**

- **Continue: worker delegation for focused implementation.** 3–4 workers this session. Still working.
- **Continue: fast pivot loops during storming.** The IaC constraint and the verification subagent request both arrived mid-session and were handled without ceremony.
- **Continue: "deployable anywhere" as a hard commitment.** Reinforced by the IaC layer — local dev and cluster deploy use the same automation language.
- **Foundation's "try: tag external-API claims as verified vs assumption":** Reviewed and **explicitly dropped** as a rule. Having high confidence in code is fine when tests, verification runs, and retros are doing their job as the feedback loop. Adding a lower-confidence rule to prevent rare errors trades high cost for low value. Bugs happen; the retro catches them; the fix lands; move on.

**Start (new this retro):**

- **Verification subagent for new infrastructure or features that are hard to exercise from the main agent.** Containers, IaC, heavy dependencies, model loads — anything the main agent structurally can't test cheaply. Not a lower-confidence rule; a focused safety net where the cost of shipping unverified is high. Validated this session by finding four real bugs on a single verification pass.

**Continue (new or reinforced this retro):**

- **Incremental commits with conventional format and `Assisted-by` trailers.** The 5+3+1 commit structure is readable top-to-bottom and supports `git bisect`.
- **Fallback-first testing.** Reproducible verification paths (committed fallback corpus) with opt-in "try real infrastructure" paths (`--try-network`). Let the verification run complete in one go without fighting external rate limits.
- **Pre-commit gitleaks + `.gitleaks.toml` allowlists.** Automation works; 9 commits scanned; zero secrets found. No friction, real coverage.
- **Inspect-partial-state-and-finish-directly on worker crashes.** When a background worker hits an API error mid-run, the right move is to inspect what landed, judge whether the output is usable, and either finish directly or relaunch. No ceremony.
</content>
</invoke>