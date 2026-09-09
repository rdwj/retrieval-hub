# Next Session -- Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #56, #58, #59, #60

## Next: Implement the ontology doctor script

The spec is at `.claude/skills/ontology-doctor/SKILL.md`. Write
`scripts/ontology_doctor.py` implementing the 9-check catalog. The
doctor is the prerequisite for drift detection (#56) and for
onboarding new sources to the ontology (#58, #59, #60) — its
missing-mappings check discovers what to map.

1. **Static checks against the catalog DB (checks 1, 7, 8, 9)**

   Start here — simplest SQL, most immediately useful. Missing
   mappings (1) and duplicates (7) are GROUP BY queries against
   `ontology_mapping`. Orphan concepts (8) and dangling relationships
   (9) are set-difference queries against `ontology_concept` and
   `ontology_relationship`.

   The DB access pattern matches the benchmark script: direct
   SQLAlchemy session, same connection strings. The models are already
   importable from `retrieval_hub.models`.

2. **Source-aware static checks (checks 2, 3, 4, 5)**

   Stale mappings (2) needs `semantic_context` JSON from the `source`
   table and, for graph sources, `doc_section` values from the vectors
   DB. Family mismatches (3) joins concepts, mappings, and sources.
   Score clustering (4) is pure analysis of `authority_score`. Coverage
   gaps (5) is heuristic — use family grouping as the domain proxy,
   skip the "content mentions" sub-check (too expensive, low value).

3. **Dead mapping check (check 6, requires embedding service)**

   Last, since it needs the embedding port-forward. Uses
   `retrieval_hub.retrieval.api.query()` with monkey-patched embedding
   endpoint, same approach as the benchmark.

4. **`--apply` for safe fixes**

   After all checks report, `--apply` adds missing exact-match
   mappings (INSERT ON CONFLICT DO NOTHING for idempotency), then
   re-runs `compute_authority_scores`. Stop-and-ask before
   implementing this since it modifies the DB.

**Definition of done:** `python scripts/ontology_doctor.py` runs
against the cluster DB and produces a health report covering all 9
checks. `--apply` adds missing mappings with authority score
recomputation. `--skip-retrieval` and `--json` flags work. Tests
exist for the static checks.

**Constraints for the session:**
- The script must be independently runnable (no MCP client needed).
- Use `127.0.0.1` not `localhost` for Postgres connections.
- `--apply` must be idempotent.
- After `--apply` adds mappings, re-run `compute_authority_scores`.
- Keep the script under 512 lines if possible — extract check
  functions into a module if it grows.

**Session start protocol:**
- Premise checks: read `.claude/skills/ontology-doctor/SKILL.md`
  for the full spec. Port-forward catalog DB to 5434. Verify the
  `ontology_mapping`, `ontology_concept`, and `ontology_relationship`
  tables have data (`SELECT COUNT(*) FROM ...`).
- Rules with history: `127.0.0.1` not `localhost` for Postgres.
  `--apply` is idempotent — INSERT ON CONFLICT DO NOTHING.
- Stop-and-ask before: implementing `--apply` (modifies the DB);
  any changes to ORM models or the authority scoring formula.
- Close ritual: session summary + `/plan-next-session`.

## What landed last session (2026-09-08)

Phase 5c shipped: family-aware hierarchy expansion. `ExpansionResult`
separates doc_section filter values from query expansion terms.
Hierarchy benchmark: 0% → 100% win rate. Overall: 58% → 91.7%.

Phase 5d design shipped: `/ontology-doctor` skill spec, 9-check
catalog. #57 (benchmarking) closed as shipped.

Filed #58 (pubmed mappings), #59 (aircraft mappings), #60
(clinicaltrials mappings) for expanding ontology coverage to untested
sources.

**Commits:** 2c7dbde..ab8aa93 (main)

**Prior sessions (same day):** Phases 1-5a shipped (registry
foundation through authority scoring). Benchmark shipped.

## Remaining epic phases

### Phase 5b: Drift detection (#56)

Periodic validation that mapped local_names still exist in source
data. Implemented as a scheduled run of the ontology doctor in
`--skip-retrieval` mode. Alerts on stale mappings.

**Definition of done:** CronJob manifest in
`deploy/openshift/retrieval-hub/ontology-doctor/` that runs the
doctor script periodically and alerts on WARN findings.

**Dependencies:** Doctor implementation (this session).

### Phase 5e: Onboard new sources to ontology (#58, #59, #60)

Add ontology mappings for pubmed-hypertension (clinical_document),
aircraft-maintenance (technical_document), and
clinicaltrials-hypertension (tabular). Use the doctor's
missing-mappings check to discover entity types, then add mappings
and re-run the benchmark with new queries.

**Dependencies:** Doctor implementation (this session).

### Phase 6 (stretch): Concept-first retrieval

`retrieve(concept="Condition")` without naming a source. Fan-out
to all sources with that concept and merge results.

**Dependencies:** Phases 1-5c (done).

## Watch out for

- Alembic migration chain — current head is `c3d4e5f6a7b8`.
- The MCP server uses alias imports: `OntologyConceptModel`,
  `OntologyRelationshipModel`. The ORM classes are `OntologyConcept`
  and `OntologyRelationship`.
- Authority scores are advisory — don't gate retrieval on them.
- `expand_doc_section_via_registry` returns `ExpansionResult`, not
  `list[str] | None`. The benchmark monkey-patch returns
  `ExpansionResult` and accepts `**_kw`.
- `refine()` does NOT call `expand_doc_section_via_registry`.
- The doctor's stale mapping check (check 2) for graph sources
  needs the vectors DB connection (chunks table), not just the
  catalog DB.
- `semantic_context` is a JSON column on `Source`. Entity types are
  at `entities[].entity_type`, not `entities[].name`.
- `compute_authority_scores` is in
  `src/retrieval_hub/ontology/authority.py`.

## If blocked

- If the doctor implementation is larger than expected, ship the
  static checks (1, 3-5, 7-9) first and defer check 2 (stale,
  needs vectors DB) and check 6 (dead, needs embedding).
- #56 drift detection can be deferred — it's just a CronJob wrapper
  around the doctor once implemented.
- #58-60 (new source mappings) are independently workable without
  the doctor — just less systematic.
