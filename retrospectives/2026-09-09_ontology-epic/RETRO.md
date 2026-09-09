# Retrospective: Ontology Epic

**Date:** 2026-09-09
**Effort:** Enterprise ontology registry for cross-source concept mapping
**Issues:** #48 (umbrella), #49-60 (all closed)
**Commits:** 1462889..9ed3475 (28 commits across 9 sessions)

## What We Set Out To Do

Build a first-class ontology registry mapping canonical concept names to per-source entity types, enabling agents to query across heterogeneous sources without knowing source-specific terminology. Six phases: registry foundation, discovery API, hierarchical concepts, cross-concept relationships, authority scoring + benchmark, and doctor + onboarding.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| MCP benchmark pivoted to direct DB | Good pivot | OAuth on deployed MCP server blocked programmatic access |
| Hierarchy expansion split into family-aware channels | Good pivot | Benchmark found 0% hierarchy win rate; doc-family sources need query term expansion, not doc_section filtering |
| missing_mappings/stale checks switched from entity_type to entity name | Good pivot | Document sources map by entity name ("Hypertension"), not entity_type ("condition"). Caught during onboarding verification |
| All 11 sources onboarded (planned 3) | Scope expansion | Low marginal effort after the first 3, gave full coverage and 0 WARN |
| Phase 6 concept-first retrieval deferred | Scope deferral | Registry provides value without fan-out. Filed as #62 |
| No live CronJob deployment | Gap | Manifest written, not oc apply'd |

## What Went Well

- **Doctor-first approach.** Building the health audit before onboarding meant every onboarding step was immediately validated. The doctor caught the entity_type/name mismatch and confirmed 0 WARN after fixes.
- **Benchmark drove real fixes.** 0% hierarchy win rate before the family-aware fix, 58% to 91.7% overall after. Concrete evidence the ontology works.
- **Idempotent scripts.** Onboarding and doctor --apply both use INSERT ON CONFLICT DO NOTHING. Re-running is always safe.
- **Sub-agent delegation.** Maker/checker pattern caught the vectors DB schema mismatch (per-index tables, not a chunks table) before it hit production.
- **Reconciliation housekeeping.** Closed 4 issues, re-scoped 1, archived 3 epic files, filed 4 forward-looking issues in one pass.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| CronJob not tested on cluster | Follow-up | Same pattern as model-registry retro. First scheduled run is the real test |
| Dead mappings check (check 6) untested against cluster | Accept | Needs embedding service. --skip-retrieval is the workaround |
| Authority scores lack real-world validation | Accept | Heuristic-only. No eval comparing score-ranked vs human preference. Part of #63 |
| PubMedBERT recommendation still in onboarding doc | Stale doc | Flagged in eval-convergence retro, still not fixed |

## Action Items

- [ ] Apply CronJob manifest to cluster and verify first scheduled run
- [ ] Run /docs-refresh to catch stale doc references (PubMedBERT, etc.)

## Patterns

**Continue:**
- Sub-agent delegation for parallel work (5th consecutive positive retro)
- Building eval/audit infrastructure before scaling (doctor before onboarding, eval harness before data-products scaling)
- Idempotent, checkpoint-friendly scripts with --dry-run (onboarding, eval pipeline, doctor --apply)

**Start:**
- Live deployment verification as an explicit step. Third retro flagging "manifest written but not applied." Consider adding a deploy-and-verify check to /session-close.
- Stale doc sweep before starting a new epic. PubMedBERT reference is now two retros stale.

**Stop:**
- Nothing systemic.

**Watch:**
- The entity_type vs entity name tension is resolved in the doctor but latent in the semantic_context schema. Graph sources use entity_type as the doc_section value; document sources use entity name. The HITL onboarding pipeline (#61) will need to be explicit about which field is the mapping key.
