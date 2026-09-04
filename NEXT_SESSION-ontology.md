# Next Session — Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #49, #50, #51, #52, #53, #54, #55, #56

## Next: Phase 1 — Registry foundation (#49, #51)

The schema and migration work is the foundation. Build the
`ontology_mapping` table, seed it from the existing SemanticContext
entity aliases, and wire `retrieve` to resolve doc_section values
against the registry instead of (or in addition to) per-source aliases.

### Work

1. Design the `ontology_mapping` table: `id`, `canonical_name`,
   `source_slug`, `local_name`, unique constraint on
   (canonical_name, source_slug). Consider whether to add
   `relationship_type` (equivalence vs. broader/narrower) now or
   defer to Phase 3.
2. Write the Alembic migration.
3. Write a seed script that reads existing SemanticContext entity
   aliases from all sources and populates the registry. The three
   graph sources (FHIR, SNOMED, Hetionet) were seeded with aliases
   in the graph-quality epic — these should populate automatically.
4. Update `_expand_doc_section` in `SourceAdapter` (base.py) to
   check the ontology registry in addition to per-source aliases.
   The registry lookup should be a single SQL query per retrieve
   call, not N queries.
5. Add tests: registry CRUD, seed idempotency, doc_section expansion
   via registry.
6. Verify with the integration test suite (the 8-test treatment plan
   workflow should still pass with the registry path active).

### Definition of done

- `ontology_mapping` table exists with Alembic migration
- Registry seeded from existing entity aliases (19 entities across
  3 graph sources)
- `retrieve` resolves doc_section via registry (with per-source
  alias as fallback)
- All existing tests pass, new registry tests pass
- Integration tests pass against live cluster

### Constraints

- The per-source alias resolution in `_expand_doc_section` should
  remain as a fallback for sources that haven't been registered.
  The registry is additive, not a replacement.
- No schema changes to `SemanticContext` — the registry is a
  separate table, not a modification of the existing per-source
  metadata.
- Stop-and-ask before: any changes to the Source model or existing
  Alembic migration chain.

## Remaining epic phases

The arc goes from lightweight registry (Phase 1-2) through biomedical
hierarchy support (Phase 3-4) to production governance (Phase 5-6).
Phases 1-2 are the minimum viable ontology. Phases 3-4 make it
competitive with Apache Atlas and Stardog. Phases 5-6 approach
Palantir/Databricks territory. The coupling between RAG and ontology
tightens incrementally — direct source access never goes away.

See `docs/research-enterprise-ontology-platforms.md` for the landscape
research informing this design.

### Phase 1: Registry foundation (#49, #51)

Schema, migration, seed from existing aliases, wire retrieve to use
the registry for doc_section expansion. Replaces the per-source alias
hack with a real table while keeping aliases as fallback.

**Definition of done:** `ontology_mapping` table exists, seeded, and
retrieve uses it. Integration tests pass.

**Dependencies:** None. The per-source aliases from graph-quality
provide the seed data.

**Parallel-ok:** Yes — independent of all other epics.

### Phase 2: Discovery API + onboarding auto-populate (#50, #52)

MCP tool (`list_concepts` or `describe_ontology`) for agents to query
the registry at runtime. Auto-populate registry entries when a new
source is onboarded via the ingestion pipeline.

**Definition of done:** Agents can call the MCP tool and get back all
canonical concepts with per-source mappings. New source onboarding
writes registry entries automatically.

**Dependencies:** Phase 1 (registry must exist).

**Parallel-ok:** No — requires Phase 1's table.

### Phase 3: Hierarchical concepts (#53)

Add parent/child (is-a) edges between canonical concepts. Query-time
expansion walks the hierarchy: searching for "Cardiovascular Disease"
automatically includes "Hypertension" subtypes. SNOMED-CT's hierarchy
(already in Memgraph) provides the seed data.

**Definition of done:** Registry supports parent_concept_id. Retrieve
expands doc_section by walking the hierarchy. SNOMED-CT hierarchy
navigable via concept-level queries.

**Dependencies:** Phase 1 (registry table). Phase 2 nice-to-have
(discovery API makes hierarchy browsable).

**Parallel-ok:** Yes with Phase 2.

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

**Parallel-ok:** Yes with Phase 3.

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

**Parallel-ok:** Yes — can run concurrently with Phases 3-4.

### Phase 6 (stretch): Concept-first retrieval

`retrieve(concept="Condition")` without naming a source. The platform
fans out to all sources with that concept and merges results. Tightest
coupling of RAG and ontology. Opt-in — direct source-level access
remains the default.

**Definition of done:** New `concept` parameter on retrieve. Fan-out
to matching sources. Results tagged with source provenance. Direct
source access unchanged.

**Dependencies:** Phases 1-3 minimum.

**Parallel-ok:** No — culmination of the arc.

---

## What this covers (and what it doesn't)

**In scope:**
- Ontology registry schema and API (#48, #49, #50)
- Retrieve integration with registry (#51)
- Source onboarding auto-populate (#52)
- Hierarchical concepts (#53)
- Cross-concept relationships (#54)
- Disambiguation and drift detection (#55, #56)
- Concept-first retrieval (stretch, no issue yet)

**Out of scope (other epics own):**
- Production ingestion runners (#27, platform-reliability)
- Operator with CRDs (#25)
- CLI/SDK peer components (#17, #18)

## Watch out for

- The Alembic migration chain — check `alembic/versions/` for the
  latest head before creating a new migration.
- The registry seed script should be idempotent (safe to re-run).
- Per-source alias fallback must remain functional for sources not
  yet in the registry.

## If blocked

- If Alembic migration is complex, prototype with raw SQL first
  and formalize later.
- Phase 2 (MCP tool) can be developed against a hardcoded registry
  before Phase 1's migration lands.
