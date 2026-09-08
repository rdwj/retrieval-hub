# Next Session — Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #49, #50, #51, #52, #53, #54, #55, #56

## Next: Phase 2 — Discovery API + onboarding auto-populate (#50, #52)

The registry exists and is seeded (53 rows, 5 sources), but agents
can't see it and new sources don't populate it automatically. This
session makes the registry visible and self-maintaining.

1. **#50 — MCP tool to describe cross-source concept mappings**
   Add a `describe_ontology` tool to the MCP server that returns all
   canonical concepts with their per-source local names. The tool
   should accept an optional `concept` parameter to filter to a single
   canonical name, and an optional `source_slug` to show only mappings
   for one source. Without parameters, it returns the full registry.
   The response should be agent-friendly: grouped by canonical concept,
   each listing its source mappings with local names.

   Key files: `retrieval-hub-mcp/src/retrieval_hub_mcp/server.py`
   (existing MCP tool definitions), `src/retrieval_hub/models/ontology.py`
   (OntologyMapping model). Follow the pattern of existing tools like
   `list_sources` or `describe_source`.

2. **#52 — Auto-populate registry during source onboarding**
   When `scripts/onboard_source.py` completes onboarding (after ingestion
   and eval), read the source's `semantic_context.entities` and upsert
   ontology_mapping rows. Reuse the union-find grouping logic from
   `scripts/seed_ontology_registry.py` — but only for the new source's
   entities against existing registry entries, not a full re-seed.

   The auto-populate should also work when `semantic_context` is set
   after onboarding (e.g., via `seed_graph_entity_aliases.py` or
   `seed_va_cpg_semantic_context.py`). Consider extracting the
   grouping + upsert logic into a library function in
   `src/retrieval_hub/ontology/` that both the seed script and
   onboard script can call.

**Sequencing.** #50 first (the MCP tool is independent and immediately
testable). #52 second (auto-populate hooks into onboard_source.py and
benefits from the MCP tool for verification).

**Constraints for the session:**
- The MCP server code is in `retrieval-hub-mcp/`, a separate package
  from the core `src/retrieval_hub/`. The tool handler gets a catalog
  session via `Depends(get_catalog_session)` — same pattern as retrieve.
- Do not modify the existing seed script's behavior — the library
  extraction should be additive, keeping the CLI script working as-is.

**Session start protocol:**
- Premise checks: confirm `ontology_mapping` table has 53 rows on
  cluster DB (port-forward 5434). Confirm the MCP server's tool list
  in `server.py` — check for any tools added by parallel sessions.
  Run `git log --oneline -5` to verify no unexpected commits landed.
- Rules with history: the MCP server deploys to gpt-oss-120b cluster
  context (not mcp-rhoai). Container deploys need explicit dep
  verification and memory sizing (see CLAUDE.md lessons learned).
- Stop-and-ask before: any changes to the Source model or existing
  Alembic migration chain. Any modifications to onboard_source.py's
  existing flow (the ontology hook should be additive, not restructuring).
- Close ritual: session summary + `/plan-next-session` per convention.

### Definition of done

- `describe_ontology` MCP tool returns canonical concepts with
  per-source mappings. Tested via mcp-test-mcp or direct invocation.
- New source onboarding writes ontology_mapping rows automatically
  when the source has semantic_context.entities.
- Grouping + upsert logic extracted to a shared function usable by
  both the seed script and onboard pipeline.
- All existing tests pass, new tests for the MCP tool and
  auto-populate logic.

## Remaining epic phases

The arc goes from lightweight registry (Phase 1-2) through biomedical
hierarchy support (Phase 3-4) to production governance (Phase 5-6).
Phases 1-2 are the minimum viable ontology. Phases 3-4 make it
competitive with Apache Atlas and Stardog. Phases 5-6 approach
Palantir/Databricks territory. The coupling between RAG and ontology
tightens incrementally — direct source access never goes away.

See `docs/research-enterprise-ontology-platforms.md` for the landscape
research informing this design.

### Phase 3: Hierarchical concepts (#53)

Add parent/child (is-a) edges between canonical concepts. Query-time
expansion walks the hierarchy: searching for "Cardiovascular Disease"
automatically includes "Hypertension" subtypes. SNOMED-CT's hierarchy
(already in Memgraph) provides the seed data.

**Definition of done:** Registry supports parent_concept_id. Retrieve
expands doc_section by walking the hierarchy. SNOMED-CT hierarchy
navigable via concept-level queries.

**Dependencies:** Phase 1 (done). Phase 2 nice-to-have (discovery API
makes hierarchy browsable).

### Phase 4: Cross-concept relationship types (#54)

Registry captures relationship types between concepts ("Compound
treats Disease", "Gene associates Disease"). Agents discover traversal
paths programmatically instead of relying on hardcoded refine
strategies.

**Definition of done:** Registry stores canonical relationship types.
MCP tool returns relationships between concepts. Agents can ask "how
are Compound and Disease related?"

**Dependencies:** Phase 2 (needs the discovery API to surface
relationships).

### Phase 5: Quality and governance (#55, #56)

Disambiguation ranking (score mappings by provenance and usage) and
drift detection (periodic validation that mapped local_names still
exist in source data). Production hardening for when source count
grows.

**Definition of done:** Validation CronJob runs, alerts on stale
mappings. Authority scores influence concept resolution when
conflicts arise.

**Dependencies:** Phases 1-2. Benefits from Phase 3-4 data but
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

Phase 1 shipped: ontology_mapping table with Alembic migration, seed
script with union-find cross-source grouping, and
expand_doc_section_via_registry() in retrieval/api.py. 53 rows seeded
across 5 sources. Migration and seed applied to cluster DB.

**Closed:** #49 — schema and migration, #51 — retrieve uses registry

**Commits:** 1462889 — feat: Add ontology_mapping registry for
cross-source concept resolution

## Watch out for

- The Alembic migration chain — check `alembic/versions/` for the
  latest head (currently `c7a9e2f1d834`) before creating new migrations.
- The MCP server package (`retrieval-hub-mcp/`) has its own
  `requirements-deploy.txt` — any new dependencies need adding there.
- Per-source alias fallback must remain functional for sources not
  yet in the registry. The registry is additive, not a replacement.
- The integration/conftest.py `pytest_collection_modifyitems` hook
  skips ALL tests when catalog DB is unreachable. Run tests with
  `--ignore=tests/integration` for unit tests.

## If blocked

- If the MCP server deploy is problematic, the `describe_ontology`
  tool can be developed and tested locally against mcp-test-mcp
  without deploying.
- If onboard_source.py is mid-refactor from another epic, the
  auto-populate can be a standalone script (like the seed script)
  that reads a source slug and populates its registry entries.
- Phase 3 (hierarchical concepts) is independent of Phase 2's
  MCP tool and could be started in parallel if needed.
