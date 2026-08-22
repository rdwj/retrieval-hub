# Retrospective: Data Products Epic

**Date:** 2026-08-22
**Effort:** Take RetrievalHub from one dataset to three, test cross-dataset reasoning, build onboarding tooling, measure source selection at scale
**Commits:** `aba4d0a`..`a78aa4b` (4 commits, Phases 4-7 in this session; Phases 1-3 in prior sessions)

## What We Set Out To Do

Seven phases to answer the questions that matter for a multi-source retrieval platform:

1. Can we ingest a second domain (biomedical literature)?
2. Can we ingest a third domain (aviation maintenance)?
3. Do chunking parameters transfer across domains?
4. Can an agent discover and select the right sources without domain-specific instructions?
5. Can a domain expert onboard a new source without engineering help?
6. At what catalog size does source selection break down?
7. What do the findings mean for the paper?

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Phase 5 pivoted from "write docs" to "build scaffolding tool" | Good pivot | Existing docs (`guide-data-owner.md`, `onboarding-journey-va-cpg.md`) already covered the process. The real gap was tooling, not documentation. |
| Model ID changed mid-experiment (Sonnet 4 deprecated, Sonnet 5 no temperature) | Bug fix | `claude-sonnet-4-20250514` returned 404. Sonnet 5 rejects the `temperature` parameter. Required two code fixes. |
| Phase 6 false start due to MCP cache | Bug fix | FastMCP's `cache_ttl=3600` cached `list_sources` results. Synthetic sources were invisible until MCP server restart. First three scale runs were invalid and had to be re-run. |
| PubMed source missing from catalog DB during Phase 6 | Bug fix | `pubmed-hypertension` had been dropped from the catalog (unknown cause). Re-registered as catalog-only entry for the scale experiment. |

## What Went Well

- **Velocity.** Four phases (4-7) delivered in a single session. The eval harness, written once in Phase 4, was reused without modification for Phase 6. The sub-agent delegation pattern works well for parallel implementation tasks.
- **The experiment design for Phase 6 was efficient.** Synthetic sources with no physical index tested source selection behavior without requiring real data ingestion. 50 synthetics with 3 deliberate confusers produced a clear signal.
- **Phase 4's findings were genuinely useful.** The "over-query is the safer default" result directly informed Phase 6's design and will shape #34's design. The v1 prompt iteration that made things worse was as valuable as the v0 baseline that worked.
- **Cross-domain chunking findings were definitive.** Three corpora, three different optima, no ambiguity. The Ragas confirmation step prevented false confidence.
- **Scaffolding tool (Phase 5) was well-received.** 43 tests, Makefile target, description guidance baked in from Phase 4 findings. The pipeline from finding to tool was tight.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| MCP server cache invalidation not handled | Follow-up | FastMCP `cache_ttl=3600` caused stale `list_sources` results after source registration. Need either a cache-bust mechanism or shorter TTL for catalog tools. |
| PubMed source vanished from catalog DB | Watch | Unknown cause. May have been a parallel session or migration. The catalog DB doesn't have audit logging for source deletions. |
| No live MCP server smoke test in the session | Accept | Phase 4 eval harness tested against the live MCP server, but the harness creates its own MCP sessions. The persistent MCP server's cached state diverged from the DB. |
| Scale experiment didn't test 24-source intermediate | Accept | Jumped from 14 to 54. The precision plateau between 14 and 54 suggests 24 wouldn't have added signal, but we don't know for certain. |
| Generated ingestion scripts not tested with real data | Accept | `new_source.py` output compiles and `--help` works, but nobody has used it to ingest an actual corpus yet. The first real use will be the test. |

## Action Items

- [ ] Investigate MCP server cache behavior: is `cache_ttl=3600` applied server-side or only as a client hint? If server-side, reduce for catalog tools or add cache invalidation on source registration.
- [ ] Add catalog DB audit logging for source deletions/status changes (would have caught the PubMed disappearance).
- [ ] First real use of `new_source.py`: onboard a 4th source using only the scaffolding tool and data owner guide. Document friction points.

## Patterns

Compared with prior retros (code-source-epic, model-registry-and-health):

**Continue:**
- Sub-agent delegation for parallel implementation. All three epics used this, all three benefited. The data-products epic ran the most agents in parallel (Phase 4: 3 concurrent writers; Phase 7: 2 concurrent writers).
- Building eval infrastructure that gets reused. The Phase 4 eval harness served Phase 6 without changes. The chunking sweep methodology from Phase 3 was already proven in prior sessions.
- Inventory/discovery before building. Phase 5 discovered the existing docs were adequate, pivoting to tooling. Phase 6's synthetic approach avoided the cost of real ingestion.

**Start:**
- Restart the MCP server (or verify cache freshness) before running evals that depend on catalog state. This session lost time to stale cache.
- Pin model IDs to non-deprecated versions. The `claude-sonnet-4-20250514` deprecation was a session-day surprise. Check model availability at session start or use alias IDs (`claude-sonnet-5`) rather than dated versions.

**Stop:**
- Nothing to stop. Scope stayed tight across all phases. No unnecessary abstractions or premature optimization.

**Watch:**
- Catalog DB stability. Two issues this session: PubMed source missing, VA CPG in DRAFT status. Neither had a clear cause. As more epics run in parallel, catalog state management needs attention.
