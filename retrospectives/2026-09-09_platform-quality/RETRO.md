# Retrospective: Platform Quality — BM25 Hybrid Retrieval

**Date:** 2026-09-09
**Effort:** Add BM25 lexical search alongside vector ANN for document-family sources, fused via Reciprocal Rank Fusion
**Issues:** #65 (closed), #71 (follow-up: remaining sources + EvalHub comparison)
**Commits:** 3dbe255..667ccfd (3 commits, single session)

## What We Set Out To Do

Add a tsvector column to pgvector index tables, implement BM25 full-text
search, and fuse BM25 + vector ANN results using RRF. This was identified
across 3 prior sessions and the code-source retro as the single biggest
retrieval quality improvement available: navigation queries (exact terms,
acronyms, definitional lookups) are systematically underserved by
vector-only search.

The plan had 6 steps: schema change, write path, backfill, retrieval
logic, tests, verification. All 6 shipped.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Scoped to va-cpg only (not all sources) | Scope deferral | Ship and verify on one source before rolling out. Other sources tracked in #71 |
| No formal EvalHub comparison | Scope deferral | Ad-hoc SQL comparison confirmed the lift qualitatively. Formal eval tracked in #71 |
| MCP OAuth token expired mid-verification | One-off obstacle | Verified via adapter directly against cluster DB instead of through MCP tool |

No architectural pivots. The RRF approach from the plan shipped as designed.

## What Went Well

- **Plan-to-ship in one session.** The 6-step plan was well-scoped and
  sequenced correctly (schema before write path before backfill before
  retrieval logic). No surprises.
- **Backfill was clean.** 53,001 rows across 15 tables, idempotent on
  re-run. The script took ~16 seconds.
- **Verification showed real improvement.** For "PTSD screening criteria",
  vector and BM25 produced almost entirely disjoint top-3 results. Hybrid
  merged them to surface an assessment chunk at rank 1 that neither
  retriever alone ranked first.
- **Opt-in design.** Recipe-level `retrieval.hybrid: true` means zero
  risk to existing sources. Can roll out incrementally.
- **Tests covered the right things.** 9 new tests for RRF fusion logic,
  BM25 SQL structure, hybrid wiring, and DDL changes. All existing tests
  continued passing (529 passed, 0 regressions).

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Hybrid enabled on 1 of ~10 eligible sources | Follow-up | #71 |
| No EvalHub quantitative comparison | Follow-up | #71 |
| `plainto_tsquery` doesn't handle hyphenated acronyms (CBT-P → zero results) | Accept | Vector search covers these; BM25 is complementary, not a replacement |
| MCP OAuth re-auth needed for live MCP tool verification | Fix now | Re-auth in next session |

## Action Items

- [x] Close #65
- [x] File follow-up #71 (remaining sources + EvalHub comparison)
- [ ] Re-auth MCP server OAuth token in next session

## Patterns

Compared with prior retros (code-source, data-products, model-registry,
eval-convergence, ontology, platform-ops):

**Continue:**
- Sub-agent delegation for parallel work. Seventh consecutive positive
  retro. Implementation, test writing, and deployment all delegated.
- Deploy-and-verify as part of the session. This retro did what ontology
  and model-registry retros flagged as missing: deployed the MCP server
  and ran real queries against cluster data before calling it done.
- Smoke tests before full runs. Dry-run of backfill, raw SQL verification
  of tsvector data, adapter-level comparison before attempting MCP tool.

**Start:**
- Nothing new. The workflow for this epic was tight.

**Stop:**
- Nothing systemic.
