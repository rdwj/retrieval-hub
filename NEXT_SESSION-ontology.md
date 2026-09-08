# Next Session — Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #54, #55, #56

## Next: Phase 4 — Cross-concept relationship types (#54)

The registry captures concept equivalence (Phase 1-2) and hierarchy
(Phase 3), but not relationships between concepts. Agents can't
discover that "Compound treats Disease" or ask "how are Compound and
Disease related?" This session adds canonical relationship types so
agents can discover traversal paths programmatically.

1. **#54 — Add cross-concept relationship types to the ontology registry**

   New `ontology_relationship` table storing canonical relationships
   between concepts: `(source_concept, relationship, target_concept)`.
   Source-independent, like `ontology_concept`.

   **Data sources for seeding:**
   - Memgraph has 30 distinct edge types. The Hetionet-style edges
     use a `Subject___verb___Object` naming pattern (e.g.,
     `Compound___treats___Disease`, `Disease___associates___Gene`)
     which maps directly to (source_concept, relationship,
     target_concept) triples.
   - FHIR edges use structural names (`HAS_SUBJECT`,
     `PART_OF_ENCOUNTER`, `DIAGNOSED_WITH`) that also encode
     concept relationships but need translation to canonical form.
   - No sources currently have `relationship_hints` in their
     `semantic_context`, so seeding comes from Memgraph edge types.

   Implementation steps:

   a. **Schema + migration.** New `OntologyRelationship` model in
      `src/retrieval_hub/models/ontology_relationship.py` with
      columns: `id` (PK, auto), `source_concept` (FK to
      ontology_concept.name), `relationship` (String),
      `target_concept` (FK to ontology_concept.name), `source_slug`
      (nullable — null means cross-source canonical, non-null means
      observed in that source), `created_at`. Unique constraint on
      `(source_concept, relationship, target_concept, source_slug)`.
      New Alembic migration extending head `a1b2c3d4e5f6`.

   b. **Seed from Memgraph.** Write
      `scripts/seed_ontology_relationships.py` that reads distinct
      edge types from Memgraph, parses the `Subject___verb___Object`
      pattern, maps subjects and objects to ontology_concept names,
      and inserts relationship rows. Include a `--synthetic` flag
      that seeds from the known Hetionet edge types without requiring
      a live Memgraph connection. Also handle FHIR-style structural
      edges (map `DIAGNOSED_WITH` to a canonical
      `(Patient, diagnosed_with, Condition)` relationship, etc.).

   c. **Extend describe_ontology MCP tool.** Add optional
      `include_relationships` parameter (default false). When true,
      each concept includes its relationships (both outgoing and
      incoming). Also consider a standalone query mode: when
      `concept` is provided with `include_relationships=True`,
      return all relationships involving that concept.

   d. **Tests.** Unit tests for the model and relationship queries
      in `tests/test_ontology/test_relationships.py`. MCP tool tests
      for the relationship parameter in
      `retrieval-hub-mcp/tests/test_server.py`.

**Sequencing.** Schema first (a), then seed (b), then MCP tool (c).
Tests (d) alongside each step. The MCP tool update is the most
visible deliverable — it's what agents consume.

**Design decisions to settle at session start:**
- Should `source_slug` be on the relationship table (tracking which
  source a relationship was observed in) or should relationships be
  purely canonical (source-independent)? Leaning toward including
  `source_slug` nullable — canonical relationships have null slug,
  source-specific observations have a slug. This parallels how
  ontology_mapping works (source-specific) vs ontology_concept
  (source-independent).
- Should the `relationship` column store a verb string ("treats",
  "associates") or a structured name ("Compound_treats_Disease")?
  Leaning toward the verb alone since source and target concepts
  are already separate columns.

**Constraints for the session:**
- Alembic migration chain — current head is `a1b2c3d4e5f6`.
  Check `alembic/versions/` before creating the new migration.
- MCP server imports: `OntologyConcept` (Pydantic schema) name
  collides with the ORM model. The current code uses
  `OntologyConceptModel` alias for the ORM import. Follow the
  same pattern for any new ORM model used in the MCP server.
- No sources have `relationship_hints` in semantic_context yet.
  Seeding comes from Memgraph edge types only.

**Session start protocol:**
- Premise checks: confirm `ontology_concept` table has 44 rows and
  25 parent edges on cluster DB (port-forward 5434). Confirm
  Memgraph is reachable (port-forward 7687) and has the expected
  30 edge types. Run `git log --oneline -5` to verify no unexpected
  commits. Check Alembic head matches `a1b2c3d4e5f6`.
- Rules with history: MCP server deploys to gpt-oss-120b cluster
  context (not mcp-rhoai). Container deploys need explicit dep
  verification and memory sizing. Use `127.0.0.1` not `localhost`
  for local Postgres connections. ORM model name collisions in the
  MCP server need aliased imports.
- Stop-and-ask before: any changes to ontology_concept's existing
  columns or constraints. Any Alembic migration that drops or
  renames existing columns. Adding FKs from ontology_relationship
  to ontology_concept (confirm the concept names in the seed data
  all exist in ontology_concept before inserting).
- Close ritual: session summary + `/plan-next-session` per
  convention.

### Definition of done

- `ontology_relationship` table stores canonical relationship types
  between concepts.
- Alembic migration applied to cluster DB.
- Relationships seeded from Memgraph edge types (or synthetic).
- `describe_ontology` MCP tool returns relationships when requested.
- Agents can ask "how are Compound and Disease related?" and get
  back "treats", "palliates", etc.
- All existing tests pass, new tests for relationship queries.

## Remaining epic phases

The arc goes from lightweight registry (Phase 1-2) through biomedical
hierarchy support (Phase 3-4) to production governance (Phase 5-6).
Phases 1-2 are the minimum viable ontology. Phases 3-4 make it
competitive with Apache Atlas and Stardog. Phases 5-6 approach
Palantir/Databricks territory. The coupling between RAG and ontology
tightens incrementally — direct source access never goes away.

See `docs/research-enterprise-ontology-platforms.md` for the landscape
research informing this design.

### Phase 5: Quality and governance (#55, #56)

Disambiguation ranking (score mappings by provenance and usage) and
drift detection (periodic validation that mapped local_names still
exist in source data). Production hardening for when source count
grows.

**Definition of done:** Validation CronJob runs, alerts on stale
mappings. Authority scores influence concept resolution when
conflicts arise.

**Dependencies:** Phases 1-2 (done). Benefits from Phase 3-4 data but
doesn't require them.

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

Phase 3 shipped: `ontology_concept` table with parent/child IS-A
edges, hierarchy-aware `expand_doc_section_via_registry` (BFS,
depth limit 5), `describe_ontology` `include_hierarchy` parameter,
seed script with `--synthetic` flag. 25 IS-A edges seeded. 16 new
tests.

See `session-summaries/2026-09-08-ontology-hierarchical-concepts.md`.

**Closed:** #53 — hierarchical concepts

**Commits:** ed13694 — feat: Add hierarchical concepts to ontology
registry

**Prior sessions (same day):** Phase 1 (1462889) and Phase 2
(2e53ed8) also shipped. Closed #49, #50, #51, #52.

## Watch out for

- Alembic migration chain — current head is `a1b2c3d4e5f6`.
- The MCP server uses `OntologyConceptModel` alias to avoid name
  collision with the Pydantic `OntologyConcept` schema. Follow
  the same alias pattern for new ORM models in the server.
- Memgraph edge types use two naming conventions: Hetionet-style
  `Subject___verb___Object` (structured, easy to parse) and
  FHIR-style `SCREAMING_SNAKE` (structural, needs manual mapping).
  The seed script needs to handle both.
- The `ontology_concept` table only has 44 rows. FK references from
  ontology_relationship must match existing concept names. The seed
  script should validate concept existence before inserting.
- Per-source alias fallback must remain functional for sources not
  yet in the registry.

## If blocked

- If Memgraph is unreachable, the schema + migration + MCP tool
  extension can all be developed with synthetic relationship data
  in tests. Use the known Hetionet edge types as synthetic seed
  data: Compound treats Disease, Disease associates Gene, etc.
- If the relationship table design turns out to be larger than
  expected, Phase 5 (governance, #55/#56) is independently workable.
