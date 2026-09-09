# Next Session -- Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #56, #57

## Next: Ontology doctor implementation + drift detection

The hierarchy fix shipped (session 2026-09-08, second session) and all
three benchmark dimensions now show positive results (91.7% overall
win rate). The ontology doctor skill spec is written. Two tracks for
the next session:

1. **Implement the ontology doctor script**

   The spec is at `.claude/skills/ontology-doctor/SKILL.md`. Write
   `scripts/ontology_doctor.py` implementing the 9-check catalog.
   Start with the static checks (1-5, 7-9) since they only need the
   catalog DB. Add the dead mapping check (6) last since it requires
   the embedding service.

   The implementation should follow the benchmark script's DB access
   pattern (direct SQLAlchemy session, same connection strings).

   **Definition of done:** `python scripts/ontology_doctor.py` runs
   against the cluster DB and produces a health report. `--apply`
   adds missing exact-match mappings and re-runs authority scores.

2. **Drift detection (#56)**

   Periodic validation that mapped local_names still exist in source
   data. This overlaps with the ontology doctor's stale mapping check
   (check 2), so the implementation should share code. The CronJob
   would run the doctor in `--skip-retrieval` mode on a schedule.

   **Definition of done:** CronJob manifest in
   `deploy/openshift/retrieval-hub/ontology-doctor/` that runs the
   doctor script periodically and alerts on WARN findings.

**Sequencing:** Implement the doctor first (concrete, spec done), then
wire up drift detection as a scheduled run of the doctor.

**Constraints for the session:**
- The doctor script must be independently runnable (no MCP client).
- Use `127.0.0.1` not `localhost` for Postgres connections.
- `--apply` must be idempotent (INSERT ON CONFLICT DO NOTHING).
- After `--apply` adds mappings, re-run `compute_authority_scores`.

**Session start protocol:**
- Read `.claude/skills/ontology-doctor/SKILL.md` for the full spec.
- Port-forward catalog DB to 5434.
- Start with the missing mappings check (simplest, most actionable).
- Stop-and-ask before: implementing `--apply` (modifies the DB).
- Close ritual: session summary + `/plan-next-session`.

## What landed this session (2026-09-08, hierarchy fix + doctor design)

Phase 5c shipped: family-aware hierarchy expansion. Hierarchy went
from 0% win rate to 100%. Overall ontology win rate: 91.7%.

Phase 5d design shipped: `/ontology-doctor` skill spec with 9-check
catalog. Implementation is the next session.

**Commits**: 2c7dbde (hierarchy fix), d59f72f (doctor spec)

**Prior sessions (same day):** Phases 1-5a shipped (registry
foundation through authority scoring). Benchmark shipped (Phase 5b
partial -- benchmark done, drift detection pending).

## Remaining epic phases

### Phase 5b: Drift detection (#56)

Periodic validation that mapped local_names still exist in source
data. Implemented as a scheduled run of the ontology doctor. Alerts
on stale mappings. Overlaps with doctor check 2.

**Definition of done:** CronJob runs on schedule, alerts on stale
mappings. Stale mappings are flagged but not auto-removed.

**Dependencies:** Doctor implementation (next session).

### Phase 5d: Ontology doctor skill

Design is done. Implementation is the next session.

**Definition of done:** `scripts/ontology_doctor.py` implements all
9 checks, produces console and JSON reports, `--apply` adds missing
mappings with authority score recomputation.

**Dependencies:** None (spec is done).

### Phase 6 (stretch): Concept-first retrieval

`retrieve(concept="Condition")` without naming a source. The platform
fans out to all sources with that concept and merges results.

**Definition of done:** New `concept` parameter on retrieve. Fan-out
to matching sources. Results tagged with source provenance.

**Dependencies:** Phases 1-5c (done).

## Watch out for

- Alembic migration chain -- current head is `c3d4e5f6a7b8`.
- The MCP server uses alias imports: `OntologyConceptModel`,
  `OntologyRelationshipModel`. The ORM classes are `OntologyConcept`
  and `OntologyRelationship`.
- Authority scores are advisory -- don't gate retrieval on them.
- Per-source alias fallback (`SourceAdapter._expand_doc_section`)
  must remain functional for sources not yet in the registry.
- The benchmark monkey-patches `_resolve_embedding_endpoint` and
  `expand_doc_section_via_registry`. The expansion monkey-patch now
  returns `ExpansionResult` and accepts `**_kw` for the
  `source_family` keyword arg. If those signatures change, update
  the benchmark.
- `expand_doc_section_via_registry` returns `ExpansionResult`, not
  `list[str] | None`. Callers must unpack `.doc_section` and
  `.query_terms`.
- `refine()` does NOT call `expand_doc_section_via_registry`. The
  refine path has no ontology expansion. The previous planning doc
  was wrong about this.
- All sources are `curated` status. Family weight is the primary
  authority signal.

## If blocked

- If the doctor implementation is larger than expected, start with
  just the static checks (skip dead mappings / retrieval checks).
- #56 drift detection can be deferred -- it's just a scheduled run
  of the doctor once implemented.
