# Next Session — Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #55, #56, #57

## Next: Phase 5a — Disambiguation and authority ranking (#55)

The registry has 44 concepts mapped across 5 sources, but all mappings
are treated equally. When two sources disagree on what "Condition" means,
there's no signal for which mapping is more authoritative. This session
adds provenance-based scoring so concept resolution can prefer the most
reliable mapping when conflicts arise.

1. **#55 — Disambiguation and authority ranking for concept mappings**

   Add an `authority_score` column to `ontology_mapping` (default 1.0)
   that ranks mappings by provenance quality. Higher scores win when
   multiple sources map different local names to the same canonical
   concept and a consumer needs to pick one.

   Implementation steps:

   a. **Schema + migration.** New `authority_score` column on
      `ontology_mapping` (Float, default 1.0, not null). New Alembic
      migration extending head `b2c3d4e5f6a7`.

   b. **Scoring heuristics.** Script or library function that computes
      authority scores based on available signals:
      - Source status weight: `published` > `curated` > `draft`
      - Mapping count: concepts with more cross-source agreement
        score higher per source
      - Source family weight: domain-specific sources (e.g., SNOMED
        for clinical terms) rank higher than general-purpose ones
      Scores are relative within a canonical concept group, not
      globally comparable.

   c. **Extend describe_ontology.** When a concept has multiple
      source mappings, sort by authority_score descending. Add
      `authority_score` to the `OntologyConceptMapping` Pydantic
      schema so agents can see the ranking.

   d. **Seed initial scores.** Script that computes scores for all
      existing mappings using the heuristics above. Idempotent
      (re-running updates, doesn't duplicate).

   e. **Tests.** Unit tests for scoring heuristics. MCP tool tests
      verifying sort order reflects authority scores.

**Sequencing.** Schema first (a), then scoring logic (b), then MCP
tool (c), then seed (d). Tests alongside each step.

**Constraints for the session:**
- Alembic migration chain — current head is `b2c3d4e5f6a7`.
- MCP server import alias pattern: `OntologyRelationshipModel` for
  ORM models used alongside Pydantic schemas of similar names.
- Authority scores are advisory, not enforced — agents see them but
  the platform doesn't filter out low-scoring mappings.
- Do not change the existing `expand_doc_section_via_registry`
  behavior. Hierarchy expansion should continue to return all
  matching concepts regardless of score.

**Session start protocol:**
- Premise checks: confirm ontology_mapping table has expected row
  count on cluster DB (port-forward 5434). Run `git log --oneline -5`
  to verify no unexpected commits. Check Alembic head matches
  `b2c3d4e5f6a7`. Verify MCP server is running with relationship
  support (`describe_ontology` with `include_relationships=True`
  returns data).
- Rules with history: MCP server deploys to gpt-oss-120b cluster
  context (not mcp-rhoai). Container deploys need explicit dep
  verification and memory sizing. Use `127.0.0.1` not `localhost`
  for local Postgres connections.
- Stop-and-ask before: any changes to ontology_mapping's existing
  columns or constraints. Any Alembic migration that drops or
  renames existing columns.
- Close ritual: session summary + `/plan-next-session` per
  convention.

### Definition of done

- `authority_score` column on `ontology_mapping` with default 1.0.
- Scoring heuristics compute scores from source status, mapping
  count, and source family.
- `describe_ontology` returns mappings sorted by authority_score.
- Agents can see which mapping is most authoritative for a concept.
- All existing tests pass, new tests for scoring logic.

## Remaining epic phases

The arc goes from lightweight registry (Phase 1-2) through biomedical
hierarchy support (Phase 3-4) to production governance (Phase 5-6).
Phases 1-4 are done. Phases 5-6 are production hardening and
concept-first retrieval. #57 (benchmarking) validates the foundation
before further investment.

See `docs/research-enterprise-ontology-platforms.md` for the landscape
research informing this design.

### Phase 5b: Drift detection (#56)

Periodic validation that mapped local_names still exist in source
data. A CronJob that queries each source's semantic_context entities
and flags stale mappings (local_name no longer in the source's
entity list). Alerts on stale mappings.

**Definition of done:** Validation CronJob runs on schedule, alerts
on stale mappings. Stale mappings are flagged but not auto-removed.

**Dependencies:** Phases 1-2 (done). Independent of Phase 5a.

### Benchmarking: Ontology-assisted vs. raw retrieval (#57)

Quantitative comparison of agent retrieval quality with and without
the ontology layer. Tests cross-source concept resolution, hierarchy
expansion, and relationship discovery. Validates whether the ontology
investment improves agent outcomes.

**Definition of done:** Benchmark suite with paired query sets.
Recall@k, query construction success, and agent task completion
metrics reported with and without ontology tools.

**Dependencies:** Phases 1-4 (done), MCP server redeployed (done).

### Phase 6 (stretch): Concept-first retrieval

`retrieve(concept="Condition")` without naming a source. The platform
fans out to all sources with that concept and merges results. Tightest
coupling of RAG and ontology. Opt-in — direct source-level access
remains the default.

**Definition of done:** New `concept` parameter on retrieve. Fan-out
to matching sources. Results tagged with source provenance. Direct
source access unchanged.

**Dependencies:** Phases 1-3 minimum (done). Phase 4 relationships
enrich the fan-out with traversal strategies.

## What landed last session (2026-09-08)

Phase 4 shipped: `ontology_relationship` table with cross-concept
relationship types (treats, binds, diagnosed_with, etc.), seed script
parsing Memgraph and FHIR edges, `describe_ontology`
`include_relationships` parameter. 13 relationships seeded. Partial
unique index fix for NULL source_slug idempotency. MCP server
redeployed.

See `session-summaries/2026-09-08-ontology-cross-concept-relationships.md`.

**Closed:** #54 — cross-concept relationship types

**Commits:** 4e66d02, 7bf42fb, 1fded0b, cbb8ef9

**Prior sessions (same day):** Phases 1-3 also shipped (1462889,
2e53ed8, ed13694). Closed #49, #50, #51, #52, #53.

**Filed:** #57 — Benchmark ontology-assisted vs. raw retrieval

## Watch out for

- Alembic migration chain — current head is `b2c3d4e5f6a7`.
- The MCP server uses alias imports to avoid Pydantic/ORM name
  collisions: `OntologyConceptModel`, `OntologyRelationshipModel`.
  Follow the same pattern for any new ORM model used in the server.
- Authority scores should be advisory — don't gate retrieval on them.
  Agents see the scores and can choose to weight results accordingly.
- The scoring heuristics are a starting point. Real-world tuning will
  come from the benchmarking work (#57).
- Per-source alias fallback must remain functional for sources not
  yet in the registry.

## If blocked

- If the authority_score design turns out to be larger than expected,
  #56 (drift detection) is independently workable.
- #57 (benchmarking) can start independently — it measures the
  existing Phase 1-4 features, not Phase 5.
- If scoring heuristics are unclear, start with a simple
  source-status-based weight (published=1.0, curated=0.8, draft=0.5)
  and iterate from benchmarking results.
