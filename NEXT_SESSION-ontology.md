# Next Session — Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #53, #54, #55, #56

## Next: Phase 3 — Hierarchical concepts (#53)

The registry is flat: "Hypertension" and "Condition" are separate
canonical concepts even though Hypertension IS-A Condition in SNOMED.
This session adds parent/child edges so that searching for "Condition"
automatically expands to include its subtypes.

1. **#53 — Add parent/child (is-a) edges to the ontology registry**

   Add a `parent_canonical_name` column to the `ontology_mapping` table
   (nullable, self-referential on canonical_name). Create an Alembic
   migration extending the existing `c7a9e2f1d834` head.

   Design choice: store hierarchy on the canonical concept, not on
   individual source mappings. A concept's position in the hierarchy
   is source-independent — "Hypertension" is a subtype of "Condition"
   regardless of which source mentions it.

   Implementation steps:

   a. **Schema + migration.** Add `parent_canonical_name` to
      `OntologyMapping` in `src/retrieval_hub/models/ontology.py`.
      New Alembic migration. Consider whether this should be a
      separate table (`ontology_concept` with `name` + `parent_name`)
      or stay on the existing mapping table — the mapping table has
      one row per (canonical, source, local), so the parent would be
      repeated across all mappings of the same canonical. A separate
      concept table is cleaner but adds a join. Discuss with user.

   b. **Seed from Memgraph.** Write a script
      `scripts/seed_ontology_hierarchy.py` that reads SNOMED IS_A edges
      from Memgraph and sets `parent_canonical_name` on matching registry
      rows. The SNOMED source is `snomed-ct-hypertension`; its entity
      types map to canonical concepts via the existing registry.

   c. **Expand doc_section via hierarchy.** Extend
      `expand_doc_section_via_registry()` in
      `src/retrieval_hub/retrieval/api.py` to walk parent→child edges.
      When a user searches for "Condition", the expansion should include
      "Hypertension" (and any other children). Depth limit to prevent
      runaway traversal on deep hierarchies.

   d. **Extend describe_ontology.** Add optional `include_hierarchy`
      parameter (default false) to the `describe_ontology` MCP tool.
      When true, each concept includes its parent and children. This
      lets agents browse the hierarchy programmatically.

   e. **Tests.** Unit tests for hierarchy traversal in
      `tests/test_ontology/`. MCP tool tests for the hierarchy parameter
      in `retrieval-hub-mcp/tests/test_server.py`.

**Sequencing.** Schema first (a), then seed (b), then retrieval
expansion (c) and MCP tool update (d) can be parallel. Tests (e)
alongside each step.

**Constraints for the session:**
- The Alembic migration chain — current head is `c7a9e2f1d834`.
  Check `alembic/versions/` before creating the new migration.
- Memgraph connectivity — need port-forward or direct access to
  the cluster's Memgraph instance to read IS_A edges. If Memgraph
  is unreachable, the seed script can be developed against a mock
  and tested later.
- Do not modify the existing `expand_doc_section_via_registry`
  behavior for flat lookups — hierarchy expansion should be additive.

**Session start protocol:**
- Premise checks: confirm `ontology_mapping` table has 53 rows on
  cluster DB (port-forward 5434). Confirm Memgraph is reachable
  (port-forward 7687) and has IS_A edges in the SNOMED source.
  Run `git log --oneline -5` to verify no unexpected commits landed.
  Check the Alembic head matches `c7a9e2f1d834`.
- Rules with history: the MCP server deploys to gpt-oss-120b cluster
  context (not mcp-rhoai). Container deploys need explicit dep
  verification and memory sizing (see CLAUDE.md lessons learned).
  Use `127.0.0.1` not `localhost` for local Postgres connections.
- Stop-and-ask before: any changes to the `ontology_mapping` table's
  existing columns or unique constraint. Any Alembic migration that
  drops or renames existing columns. Any changes to
  `expand_doc_section_via_registry`'s existing flat-lookup behavior.
- Close ritual: session summary + `/plan-next-session` per convention.

### Definition of done

- `ontology_mapping` (or a new `ontology_concept` table) supports
  parent/child relationships between canonical concepts.
- Alembic migration applied to cluster DB.
- SNOMED IS_A hierarchy seeded into the registry.
- `expand_doc_section_via_registry` walks parent→child edges when
  expanding doc_section filters (with depth limit).
- `describe_ontology` MCP tool can return hierarchy information.
- All existing tests pass, new tests for hierarchy traversal.

## Remaining epic phases

The arc goes from lightweight registry (Phase 1-2) through biomedical
hierarchy support (Phase 3-4) to production governance (Phase 5-6).
Phases 1-2 are the minimum viable ontology. Phases 3-4 make it
competitive with Apache Atlas and Stardog. Phases 5-6 approach
Palantir/Databricks territory. The coupling between RAG and ontology
tightens incrementally — direct source access never goes away.

See `docs/research-enterprise-ontology-platforms.md` for the landscape
research informing this design.

### Phase 4: Cross-concept relationship types (#54)

Registry captures relationship types between concepts ("Compound
treats Disease", "Gene associates Disease"). Agents discover traversal
paths programmatically instead of relying on hardcoded refine
strategies.

**Definition of done:** Registry stores canonical relationship types.
MCP tool returns relationships between concepts. Agents can ask "how
are Compound and Disease related?"

**Dependencies:** Phase 2 (done). Benefits from Phase 3 hierarchy.

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

**Dependencies:** Phases 1-3 minimum.

## What landed last session (2026-09-08)

Phase 2 shipped: `describe_ontology` MCP tool with concept/source_slug
filters, shared `populate_ontology_for_source()` library for incremental
registry population, onboard_source.py hook. 15 new tests.

See `session-summaries/2026-09-08-ontology-discovery-api.md`.

**Closed:** #50 — MCP tool, #52 — auto-populate during onboarding

**Commits:** 2e53ed8 — feat: Add describe_ontology MCP tool and
ontology auto-populate library

**Prior session (same day):** Phase 1 shipped — ontology_mapping table
with Alembic migration, seed script with union-find cross-source
grouping, expand_doc_section_via_registry(). 53 rows seeded across
5 sources.

**Closed:** #49 — schema and migration, #51 — retrieve uses registry

## Watch out for

- The Alembic migration chain — current head is `c7a9e2f1d834`.
  Check before creating new migrations.
- The MCP server package (`retrieval-hub-mcp/`) has its own
  `requirements-deploy.txt` — any new dependencies need adding there.
- Per-source alias fallback must remain functional for sources not
  yet in the registry. The registry is additive, not a replacement.
- Memgraph connection details may need port-forward setup. Check
  the graph-quality session summaries for the correct namespace and
  service name.
- The hierarchy design decision (column on existing table vs. new
  concept table) should be settled at session start, not mid-implementation.

## If blocked

- If Memgraph is unreachable, the schema + migration + retrieval
  expansion can all be developed and tested without SNOMED data.
  Use synthetic hierarchy data in tests (e.g., Disease→Condition→
  Hypertension chain). Seed from Memgraph in a follow-up.
- If the hierarchy design turns out to be larger than expected,
  Phase 4 (relationship types, #54) is independently workable and
  also benefits from Phase 2's discovery API.
