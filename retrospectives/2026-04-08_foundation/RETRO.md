# Retrospective: retrieval-hub Foundation

**Date:** 2026-04-08
**Effort:** From `/imagine` through design rounds 1–2, integration docs, vertical slice steps 1–2, and stage-2 UI mockup
**Phase:** Storming (brainstorming + foundation scaffolding)
**Issues / commits:** None — project is pre-git. Initializing version control is an action item from this retro.

## What we set out to do

retrieval-hub started as a `/imagine` session: a platform component for OpenShift AI that provides **curated retrieval sources for RAG-enabled agents**, modeled on memory-hub, presenting sources as cards in the RHOAI catalog style, with **per-source query rewriting** as the differentiator. MCP tools for agents, enterprise data management, deployable anywhere.

Notably, the first session surfaced that **this is already on Red Hat's published roadmap**. The user considered not continuing, and chose to proceed anyway — partly because something concrete and demonstrable would be useful for customers in the meantime, and partly because it serves as a usable example of the `/imagine` → design → scaffold workflow. That honest positioning discussion shaped the rest of the work: **"build what I'd use with customers, and if the other team ships something better sooner, go use that."**

The implicit goal that emerged: get retrieval-hub from an idea to something runnable enough to demo, with design docs substantial enough to hand to a customer engineer, and with the first two components of the vertical slice scaffolded and green.

## What changed

Three categories, reframed from the first-draft discussion. This is a storming phase — **pivots and refinements are the expected shape of the work**, not defects. "Missed requirements" would be the wrong framing for most of what's below.

### Design pivots (improved the design through discussion)

| Change | Rationale |
|---|---|
| MCP read-only → read + data writes for agents | User pushback late in round 1. Forced `agent_write_policy` + `sources.write` scope + three write modes (append / upsert / annotate). Better design: data writes into curated sources are in scope, catalog mutation stays humans-only. |
| Rewriter: bespoke per-source prompts → shared core + source metadata | Single biggest design improvement. Lowers the barrier to enabling rewriting from "write a prompt" to "declare vocabulary mappings." The differentiator is now accessible to every source owner, not just ones who'll invest in prompt engineering. |
| Observability: native query log → delegate to Prometheus + Grafana | "Reuse anything we can" directive. retrieval-hub emits metrics + OpenTelemetry traces; admin UI deep-links to Grafana for query volumes, latency, per-identity usage, anomaly detection. No native query log. |
| Eval execution: own orchestrator → primarily import from LlamaStack/Ragas | "Just be able to import those." LlamaStack's `/v1alpha/eval` + Ragas is the production happy path; retrieval-hub pre-populates `retrieved_contexts` and asks Ragas to score. Native orchestrator is the standalone fallback. |
| Eval scores on card: full per-LLM table → composite best-score + drill-down | Card scannability. Keeps the one load-bearing signal (max Recall@5 + LLM name + rewrite lift on that LLM) visible; per-LLM breakdown is one click away. |
| Admin view: separate owner dashboard → shared admin view with scope filter | Source owners see the same admin dashboard filtered to sources they own. Less UI code, same mental model. |
| Auth production default: retrieval-hub-auth issues JWTs → `external_jwt_validator` against Keycloak | In Kagenti deploys, the gateway mints audience-scoped tokens; retrieval-hub-auth validates and translates claims. Own-issuance becomes the dev/fallback path. |

### Scope deferrals (consciously pushed to round 2 or later)

| Deferral | Reason |
|---|---|
| Permission request workflow (inbox, approval) | Round 2. Round 1 is a `mailto:` link pre-populated with the requester's identity, current groups, required groups, and a use-case template. |
| Admin: anomaly detection, top consumers, write activity drill-down | Round 2. Round 1 ships three panels (cluster health, top sources, recent changes) plus deep-links to Grafana. |
| AutoRAG full integration | Considered, not committed. Primary role narrowed to recipe optimization (not eval data generation, which now has LlamaStack + Ragas as a competitor). |
| Operator + CRDs | Explicitly deferred until the configuration surface stabilizes. Plain manifests + Kustomize in the meantime. |
| Steps 3–15 of SYSTEMS.md build order | MCP server skeleton, first adapter, `/plan-tools`, rewriter, multi-corpus rollout, SDK/CLI, ingestion runners, evaluation integration, AI Assets registration — all queued up in the build order, none started yet. |
| UI stage 3 (real SPA + BFF implementation) | Deferred. Stage 2 mockup is clickable with mock data; real implementation waits on step 3 (MCP) and step 4 (first adapter + real corpus). |

### Refinements from iteration (caught via feedback during storming)

| Refinement | How it surfaced |
|---|---|
| Research-backed corrections to LlamaStack claims | Research subagent pass caught: `/v1/connectors` doesn't exist (it's `toolgroups`), `/v1/eval` is `/v1alpha/eval`, Ragas doesn't compute Recall@k/MRR/NDCG, LlamaStack is TP not GA on RHOAI 3.0–3.3, v0.7.0 removed `tool_groups` API. Applied as hard corrections before coding. |
| Research-backed corrections to MLflow claims | Research subagent pass caught: MLflow is **not** part of RHOAI 3.x (`managementState: Removed` in 3.3), prompt registry is GA in 3.x (not 2.x), client auth is env-var-only (no token API), RHOAI dashboard-proxied URL doesn't accept service account auth. |
| UI jargon on cards (R@5, embedding model, chunker, retrieval patterns) without tooltips | User screenshot feedback after the stage-2 mockup ran. Fixed same turn with above-row labels + Popovers for rich explanations + Tooltips for inline jargon. |
| Domain tag duplication with family/status/visibility badges | Same user screenshot feedback. Fixed by cleaning up all 8 mock sources + adding a render-time filter in `DomainTags` as a safety net. |
| `python-multipart` runtime dep for FastAPI `Form()` parsing in auth service | Caught by the step-2 claude-worker during implementation, not documented in `auth.md`. Added to `pyproject.toml` with a comment; flagged in the worker's open questions. |

## What went well

- **The initial "should you even do this" framing.** The `/imagine` session surfaced the RHOAI roadmap overlap honestly up front, gave the user a real choice, and shaped the pragmatic posture ("if the other team ships better sooner, we use that") that governed every design decision afterward. **This is one of the most valuable outputs of the session, not despite being a skeptical moment but because of it.**
- **Design docs stayed coherent across revisions.** 23 docs + ~5,800 lines, cross-referenced, with consistent "What's Decided / What's Open" sections that survived multiple rounds of updates.
- **Platform overlap analysis in `integrations/README.md`.** The "a meaningful fraction of round-1 design was duplicating things the cluster already provides" framing was load-bearing. Without it, we'd still be designing a native query log, a native experiment tracker, and a native token issuer.
- **The differentiator is intact.** Through all the corrections and restructurings, the per-source rewriter metadata model — the thing that makes retrieval-hub uniquely retrieval-hub — survived unchanged.
- **Two clean scaffolds.** Step 1 (`src/retrieval_hub/`, 68 tests, 96% cov) and step 2 (`retrieval-hub-auth/`, 66 tests, 95% cov) both ended lint-clean, well-tested, and independently buildable. FIPS-friendly crypto in both. Worker delegation was effective.
- **Research subagents produced hard corrections, not guesses.** The LlamaStack + MLflow research passes found and fixed multiple wrong claims before any code was written against them. Cheap insurance.
- **Runnable UI mockup.** Stage 1 (data dictionary) → stage 2 (React + PatternFly + mock data) → stage-2-iteration (labels + tooltips) in one session. User clicked on it, screenshotted a card, gave feedback, and the feedback landed in the same turn.
- **Storming-appropriate pace.** Pivots landed quickly and without ceremony. When the user said "rewriter should be shared core + metadata," the restructure was in the docs within one turn. When they said "delegate observability to Grafana," the new integration doc was drafted same turn. Fast loops.
- **The `/imagine` skill itself got validated.** The user shared it with other developers this week based on how this session went. That's external evidence that the ideation workflow produces useful artifacts, not just internal-to-this-session value.

## Gaps identified

| Gap | Severity | Resolution |
|---|---|---|
| **No git repo.** Hundreds of files of real work exist on disk with no version control, no commit history, no branches, no diff-of-work record. | Fix now | Initialize git, commit foundation baseline in coherent chunks (docs / step 1 / step 2 / UI mockup / retros), before any further work. |
| **Vertical slice isn't a running system yet.** Step 1 and step 2 are independently buildable but not wired together. `ValidatedIdentity` (auth) and `Identity` (core lib) haven't been verified to map at runtime. | Next session | Step 3 (MCP server skeleton) is what wires them and proves the foundation runs end-to-end. |
| **No real corpus ingested.** Everything about the data model is conjectural until the first source adapter runs against real content. Mock data is realistic-looking but hasn't been pressure-tested. | Follow-up | Step 4 (first adapter + Red Hat product docs hand-run). |
| **UI mockup TypeScript types hand-written, not generated from core library schemas.** When stage 3 (real SPA + BFF) lands, there's type-drift risk. | Follow-up | When stage 3 starts, regenerate types from the Pydantic schemas (or keep them hand-written with a test that asserts parity). |
| **External API shapes based on research, not verified against real deployments.** Kagenti `MCPServer` CRD, LlamaStack `/v1alpha/eval` params, MLflow `managementState` in RHOAI 3.3 — all flagged as "verify before committing" in the docs, but unverified. | Follow-up | Verify on first real deployment, update docs if reality differs. |
| **PatternFly 5 `ToolbarFilter.chips` deprecation warnings** in UI browser console. | Accept | Known; not fixed in mockup. Address before stage 3 ships. |
| **1 MB CSS + 575 KB JS chunk sizes** in UI build. | Accept | Normal for PatternFly without code-splitting. Address with `manualChunks` before production. |
| **5 npm audit vulnerabilities** in UI transitive dev-dep chains (2 moderate, 3 high). | Accept for mockup | Address before any real deploy. |
| **No project-root `CLAUDE.md`.** Global CLAUDE.md covers conventions but a project-specific one could capture retrieval-hub-specific commands (make targets, workflow notes). | Follow-up | Create when there are enough project-specific conventions worth writing down. |

## Action items

**Immediate (before any more substantive work):**

- [ ] Initialize git repo and commit the foundation baseline
- [ ] Decide next session's focus: step 3 (MCP server, proves the end-to-end loop) vs. step 4 (first adapter + real corpus, exercises the data model)

**Follow-up (track, don't block):**

- [ ] Step 3: MCP server skeleton from fips-agents template, wired to `retrieval-hub-auth.tokens.validator`
- [ ] Step 4: First source adapter (`document` family) + hand-run ingestion of Red Hat product docs
- [ ] Step 5: `/plan-tools` workflow against the now-functional core library
- [ ] Verify Kagenti `MCPServer` CRD shape when Kagenti lands on the target cluster
- [ ] Verify LlamaStack `/v1alpha/eval` + Ragas metric set against a real RHOAI 3.x install
- [ ] Address PatternFly 5 deprecation warnings before UI stage 3
- [ ] Decide UI type-generation story (generate from Pydantic schemas vs. keep hand-written with parity test)

## Patterns

This is the first retro for the project — no cross-retro history to pattern-match against yet. What I'd flag as **continue** / **try** / **watch** going forward:

**Continue:**

- **The honest "should you even do this" framing on new projects.** It's what makes `/imagine` produce usable artifacts instead of wishful ones.
- **Fast pivot loops during storming.** Don't treat design changes as failures when the point of storming is to find out what the design should be.
- **Research subagents before coding against external APIs.** Cheap insurance; caught real problems this session.
- **Worker delegation for focused implementation work.** Step 1, step 2, and the UI mockup were all well-suited to claude-worker delegation. Main agent stays on synthesis.
- **"What's Decided / What's Open" sections in every design doc.** Kept the docs honest across multiple revision rounds.
- **"Deployable anywhere" as a hard commitment** locked in early. Every integration doc has a standalone fallback because of it.

**Try:**

- **Initialize git on day one of any new project.** This should be a `/imagine` or project-bootstrap habit, not a thing to remember later.
- **Tag external-API claims in docs as `[verified against <source>, <date>]` or `[assumption, needs verification]`.** Would make the "what needs a research pass" audit trivial instead of requiring re-reading.
- **Schedule a quick "jargon pass" after any UI mockup ships** — even a one-off. Walk a card and ask "what here is unlabeled and not self-documenting?" Would have caught the card-jargon issue before the user had to.

**Watch:**

- **Documentation vs. implementation drift.** 23 design docs is a lot. If we keep writing docs faster than we test them against running code, we risk designing things that don't survive contact with reality. The vertical slice (steps 3–5) is the first real pressure test. If we get through step 5 and find that half the round-1 docs need rewriting, that's a signal to slow the doc pace.
- **The "roadmap overlap" tension.** The pragmatic posture works for now, but if Red Hat's roadmap item lands mid-project, we need a clean moment to decide whether retrieval-hub retires, migrates, or stays as an opinionated alternative. Not a gap; a thing to track.
