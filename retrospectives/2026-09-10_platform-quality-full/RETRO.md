# Retrospective: Platform Quality + Onboarding Pipeline

**Date:** 2026-09-10
**Effort:** BM25 hybrid retrieval, automated entity discovery, pipeline completeness for new source onboarding
**Issues:** #65 (closed), #71 (closed), #61 (closed)
**Commits:** 56b4ce9..a24222a (9 commits across one extended session)

## What We Set Out To Do

The session started with a single-phase epic: add BM25 hybrid retrieval
(#65). The plan was schema changes, retrieval logic, backfill, and
verification.

What actually happened: #65 shipped in the first third of the session,
then the scope expanded organically through three follow-on efforts:
- #71: enable hybrid on all sources, run EvalHub comparison
- Pipeline audit: wire hybrid and ontology into the default pipeline
- #61: LLM-based entity discovery with HITL review

Each expansion was user-directed and made sense in context. The session
ended with all three issues closed.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Scope grew from 1 issue to 3 | Good pivot | Each issue was a natural follow-on; finishing them now avoids context loss |
| Entity discovery shipped without HITL initially | Scope deferral then completed | Built the engine first (#61 partial), added CLI review later when user asked to finish |
| EvalHub runner needed a fix for missing args | One-off bug | `keywords_file`, `system_prompt`, `source_name` attrs missing from Namespace |
| SQLAlchemy JSON mutation bug | One-off bug | `flag_modified` needed for `semantic_context` -- caught by running against real data, not tests |

## What Went Well

- **Context_precision tripled.** The EvalHub comparison showed hybrid
  retrieval improved context_precision from 0.272 to 0.729 (+168%).
  Answer relevancy and faithfulness also improved slightly. This is
  the strongest quantitative result in the project's history.
- **Entity discovery worked across all domains.** The LLM extracted
  domain-appropriate entities for clinical (drug classes, biomarkers),
  aviation (components, manufacturers, FAA standards), literary
  (characters, locations, events), and code (models, adapters, APIs)
  sources. 188 entities and 186 ontology mappings across 11 sources.
- **Pipeline is complete for new sources.** A new source ingested
  through `pipeline.ingest()` now gets: tsvector + GIN index, hybrid
  retrieval enabled by default, LLM entity discovery, ontology mapping,
  and doctor validation. Zero manual steps for the core path.
- **Deploy-and-verify as standard practice.** Both the MCP server
  (build #26) and EvalHub (build #9) were deployed and verified with
  real queries during the session. Eighth retro, second consecutive
  where deployment happened as part of the session.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| `flag_modified` needed for JSON columns | Fixed | `7aec39e` -- both pipeline.py and onboard_source.py |
| Evalhub runner missing 3 Namespace attrs | Fixed | `d865b90` |
| Entity discovery quality unreviewed for existing sources | Accept | LLM output looked reasonable; CLI review tool now exists for future use |
| Earlier platform-quality retro only covers #65 | Accept | This retro supersedes it for the full session |
| MCP OAuth token expired, live MCP tool verification skipped | Accept | Verified via adapter directly; deployed code is the same |
| Graph-family sources not enriched with entity discovery | Accept | Their entities map to node types (Disorder, Compound, etc.), which is correct for graph structure |

## Action Items

- [x] Close #65, #71, #61
- [x] Fix `flag_modified` bug (`7aec39e`)
- [x] Fix evalhub runner missing attrs (`d865b90`)
- [x] Update data owner guide and README (`ae0f667`)
- [ ] Update NEXT_SESSION-ontology-v2.md to reflect #61 closure (Phase 5 done)

## Patterns

Compared with prior retros (8 total):

**Continue:**
- Sub-agent delegation for parallel work. Eighth consecutive positive
  retro.
- Deploy-and-verify as part of the session. Second consecutive retro
  where this happened. The earlier "Start" item from three retros ago
  has become standard practice.
- Quantitative verification before closing. The EvalHub comparison
  gave hard numbers, not just "it looks right."

**Start:**
- **Test JSON column mutations against a real DB.** The `flag_modified`
  bug was invisible to mocked tests and only caught by running against
  Postgres. Consider adding an integration test that round-trips a JSON
  column update for any code that modifies `semantic_context` or
  `rewriter_metadata`.
- **Check EvalHub runner compatibility before submitting Jobs.** The
  missing Namespace attrs cost a failed Job and a rebuild cycle. A
  smoke-test script that imports `eval_answer_quality` and constructs
  the Namespace locally would catch this class of issue before the
  cluster build.

**Stop:**
- Nothing systemic.
