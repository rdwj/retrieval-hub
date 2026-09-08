# Next Session — Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #56, #57

## Next: Family-aware hierarchy expansion + ontology doctor skill

The benchmark (session 2026-09-08) validated cross-source resolution
(80% win rate) and relationship discovery (100% win rate), but found
that hierarchy expansion hurts retrieval on non-graph sources (0%
win rate). The next session has two tracks:

1. **Fix hierarchy expansion for document-family sources**

   Child concept names (e.g., "Metformin", "PHQ-9") don't exist as
   `doc_section` values in clinical_document sources. The current
   expansion adds them to the doc_section filter, which matches
   nothing. The fix: detect the target source's family and, for
   document-family sources, inject child names into the query text
   instead of the doc_section filter.

   Implementation in `expand_doc_section_via_registry` — add a
   family check and return expanded terms separately. The retrieval
   API's `query()` function would accept an optional `query_expansion`
   parameter that appends terms before embedding.

   **Definition of done:** Re-run the benchmark and show hierarchy
   queries producing positive lift on document-family sources.

2. **Design the ontology doctor skill (`/ontology-doctor`)**

   A Claude Code skill that analyzes ontology health and proposes
   fixes. This is a design session — the goal is a skill spec, not
   working code. Decisions needed:

   - **Scope of analysis**: What checks does the doctor run?
     - Dead mappings: local_names that produce zero retrieval hits
     - Family mismatches: hierarchy expansions that harm retrieval
     - Score clustering: authority scores too narrow to differentiate
     - Missing mappings: source entity types not in the registry
     - Stale mappings: local_names that no longer exist in source data
       (overlaps with #56 drift detection)
   - **Fix vs. propose**: Does the doctor auto-fix or generate a
     report for human review? Probably report-first with an `--apply`
     flag for safe fixes (like adding missing mappings).
   - **Deployment target**: Run against the deployed server (needs
     OAuth handling) or require port-forwards to cluster DB?
   - **Skill interface**: What arguments does `/ontology-doctor` take?
     Specific source? Specific concept? Full audit?
   - **Output format**: JSON report, human-readable table, or both?
     Should it create GitHub issues for findings?

   **Definition of done:** Skill spec written to
   `.claude/skills/ontology-doctor.md` with trigger rules, check
   catalog, output format, and example invocations. Implementation
   is a follow-on session.

**Sequencing:** Fix hierarchy expansion first (smaller, concrete),
then design the ontology doctor skill (larger, needs design decisions).

**Constraints for the session:**
- Hierarchy fix changes `expand_doc_section_via_registry` and the
  `query()` function signature. Both are core retrieval code — needs
  tests.
- The ontology doctor design should account for the OAuth-protected
  MCP endpoint (the benchmark had to use direct DB access for this
  reason).
- Use `127.0.0.1` not `localhost` for Postgres connections.

**Session start protocol:**
- Premise checks: verify port-forward to 5434 is active, embedding
  service on 8081, run benchmark smoke test to confirm baseline.
- Read `docs/ontology-benchmark-findings.md` for full analysis.
- Stop-and-ask before: changes to the `query()` function signature
  (affects all callers).
- Close ritual: session summary + `/plan-next-session`.

## What landed last session (2026-09-08 benchmark)

Benchmark shipped: 12 paired queries across 3 dimensions, deterministic
harness using direct DB access, full metrics with report.

Key findings:
- Cross-source resolution: 80% win rate, +6.2 avg hit lift
- Relationship discovery: 100% win rate, +7.0 avg hit lift
- Hierarchy expansion: 0% win rate, -4.5 avg hit lift (family mismatch)
- Authority score correlation: not significant (r=0.04, p=0.77)

See `docs/ontology-benchmark-findings.md` and
`session-summaries/2026-09-08-ontology-benchmark.md`.

**Commits:** b7d9c01 (benchmark), (next commit: findings + session summary)

**Prior sessions (same day):** Phases 1-5a shipped. Closed
#49, #50, #51, #52, #53, #54, #55.

## Remaining epic phases

The arc goes from lightweight registry (Phase 1-2) through biomedical
hierarchy support (Phase 3-4) to production governance (Phase 5-6).
Phases 1-5a are done. #57 (benchmarking) validated cross-source and
relationship dimensions. Hierarchy needs a fix before Phase 6.

### Phase 5b: Drift detection (#56)

Periodic validation that mapped local_names still exist in source
data. A CronJob that queries each source's semantic_context entities
and flags stale mappings (local_name no longer in the source's
entity list). Alerts on stale mappings.

**Definition of done:** Validation CronJob runs on schedule, alerts
on stale mappings. Stale mappings are flagged but not auto-removed.

**Dependencies:** Phases 1-2 (done). Independent of hierarchy fix.

### Phase 5c: Family-aware hierarchy expansion

Fix `expand_doc_section_via_registry` to detect source family and
route hierarchy expansion to query text (document sources) vs.
doc_section filter (graph sources). Re-run benchmark to validate.

**Definition of done:** Hierarchy benchmark queries show positive
lift. No regression in cross-source or relationship dimensions.

**Dependencies:** Benchmark (done). Blocks Phase 6.

### Phase 5d: Ontology doctor skill

Claude Code skill that audits ontology health: dead mappings, family
mismatches, score clustering, missing mappings, stale mappings.
Report-first with optional `--apply` for safe fixes.

**Definition of done:** Skill spec + working implementation that
runs the benchmark harness and additional checks, produces a report.

**Dependencies:** Benchmark (done), hierarchy fix (5c, recommended).

### Phase 6 (stretch): Concept-first retrieval

`retrieve(concept="Condition")` without naming a source. The platform
fans out to all sources with that concept and merges results. Tightest
coupling of RAG and ontology. Opt-in — direct source-level access
remains the default.

**Definition of done:** New `concept` parameter on retrieve. Fan-out
to matching sources. Results tagged with source provenance. Direct
source access unchanged.

**Dependencies:** Phases 1-3 (done), hierarchy fix (5c).

## Watch out for

- Alembic migration chain — current head is `c3d4e5f6a7b8`.
- The MCP server uses alias imports to avoid Pydantic/ORM name
  collisions: `OntologyConceptModel`, `OntologyRelationshipModel`.
  The ORM classes are `OntologyConcept` and `OntologyRelationship`.
- Authority scores are advisory — don't gate retrieval on them.
- Per-source alias fallback (`SourceAdapter._expand_doc_section`)
  must remain functional for sources not yet in the registry.
- The benchmark harness monkey-patches `_resolve_embedding_endpoint`
  and `expand_doc_section_via_registry`. If those signatures change,
  update the benchmark.
- `expand_doc_section_via_registry` has TWO callers: the retrieval
  API `query()` function and the refine path. Both must be updated
  for the hierarchy fix.
- All sources are `curated` status — status weight provides no
  differentiation. Family weight is the primary authority signal.

## If blocked

- If the hierarchy fix proves architecturally complex, start with the
  ontology doctor skill design (independent of the fix).
- #56 (drift detection) is independently workable and doesn't depend
  on the benchmark or hierarchy fix.
