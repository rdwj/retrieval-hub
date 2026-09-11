# Retrospective: Ontology v2 Epic

**Date:** 2026-09-11
**Effort:** Self-improvement and concept-first retrieval for the ontology registry
**Issues:** #61, #62, #63, #64, #68 (all closed)
**Commits:** 961a64b..12e5974 (~20 commits across 4 sessions)

## What We Set Out To Do

Build on the v1 ontology registry with five capabilities: automated
onboarding with HITL (#61), concept-first retrieval (#62), eval-driven
self-improvement (#63), query success monitoring (#64), and wider
authority score signals (#68). The goal was a self-maintaining ontology
where agents query by concept, runtime monitoring tracks what works,
and scores adjust automatically from observed retrieval performance.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Phase order: #68 shipped before #62 | Good pivot | Wider score range (0.632-0.980) gave concept-first retrieval meaningful authority weights for RRF |
| Score normalization added to Phase 4 | Good pivot | Phase 3 dry-run showed all scores clamping to 1.0. Added min-max normalization [0.3, 1.0] to make eval adjustments visible |
| "Dashboard or report for ops" replaced by CLI | Scope deferral | `--from-metrics` flag on self-improvement CLI is more useful at this stage than a dashboard. Dashboard filed as future work |
| BM25 hybrid retrieval landed mid-epic (#65) | External | Invalidated the benchmark's authority_correlation metric but didn't block the epic |

## What Went Well

- **Eval-driven design loop.** Each phase produced data that informed the next. The benchmark found the 1.0-ceiling clamp, which motivated normalization, which validated the self-improvement pipeline with 19 distinct adjusted scores (0.676-1.0).
- **Lesson application from v1.** `flag_modified()` for JSON columns (v1 gap) was applied immediately when the same issue hit during entity discovery (7aec39e).
- **Test coverage trajectory.** 125 ontology tests (up from ~50 at epic start). Every new module has unit tests; monitoring also has integration tests.
- **Idempotent patterns throughout.** Onboarding, doctor --apply, self-improvement, score normalization: all safe to re-run.
- **Sub-agent delegation.** Continued to work well for parallelizing implementation and review.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Alembic migration `d4e5f6a7b8c9` not applied to cluster | Fix before next deploy | Run migration when deploying MCP server |
| MCP server not redeployed with monitoring instrumentation | Fix before next deploy | Part of #70 (platform-ops) |
| PubMedBERT stale doc references (4 files) | Follow-up | 2 retros stale. Run /docs-refresh |
| CronJob manifest not verified on cluster | Follow-up | 3 retros stale. Part of #70 (platform-ops) |
| `pubmed-hypertension` uses different embedding model, silently drops from concept queries | Accept | Not blocking; would need model alignment or adapter-level fallback |
| `_check_confidence` false positive on multi-source path (server.py:856) | Accept | Pre-existing, not introduced by this epic |

## Action Items

- [ ] Apply Alembic migration `d4e5f6a7b8c9` to cluster DB before next MCP deploy
- [ ] Redeploy MCP server with monitoring instrumentation (#70)
- [ ] Run /docs-refresh to fix PubMedBERT references (3rd retro flagging this)
- [ ] Verify CronJob manifest is applied and running (3rd retro flagging this)

## Patterns

**Continue:**
- Eval-driven design loops (benchmark -> findings -> fix -> re-benchmark). 2nd consecutive positive retro.
- Sub-agent delegation with maker/checker pattern. 6th consecutive positive retro.
- Idempotent scripts with --dry-run everywhere.
- Session planning files that sequence phases with explicit definitions of done.

**Start:**
- Deploy-and-verify as a gated step. The migration and MCP redeploy gaps are the same class of problem as v1's CronJob gap: code ships, infra doesn't follow. Consider a deploy checklist in /session-close.
- Stale doc sweeps before starting a new epic. PubMedBERT reference is now 3 retros old. Run /docs-refresh as a pre-epic step.

**Stop:**
- Nothing systemic.

**Watch:**
- Score normalization is global min-max: adding one extreme-scoring source shifts all other scores. If source count grows past ~20, consider switching to percentile-based normalization.
- The monitoring table will grow linearly with query volume. No retention policy yet. Add a cleanup job if the table exceeds ~1M rows.
