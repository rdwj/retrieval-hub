# Next Session — Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology. Builds on the
lightweight per-source alias resolution shipped in the graph-quality
epic.

Issues: #48 (umbrella), #56, #57

## Next: Benchmarking ontology-assisted vs. raw retrieval (#57)

The ontology registry is feature-complete through Phase 5a (44 concepts,
53 mappings with authority scores, 13 cross-concept relationships,
hierarchy expansion, describe_ontology with sorting). Before investing
in drift detection (#56) or concept-first retrieval (Phase 6), we need
quantitative evidence that the ontology layer improves agent retrieval.

1. **#57 — Benchmark ontology-assisted vs. raw retrieval**

   Design paired query sets that test the same clinical questions two
   ways: (a) agent uses `describe_ontology` to discover cross-source
   terminology, then queries with the right local names, and (b) agent
   queries with the canonical name only (no ontology tools). Compare
   recall@k and answer quality.

   Implementation steps:

   a. **Query set design.** Build 10-15 paired queries across three
      dimensions:
      - Cross-source concept resolution: "Find all Condition data"
        across FHIR (Condition), Hetionet (Disease), SNOMED (Disorder)
      - Hierarchy expansion: "Find Condition data" with hierarchy
        (should include Hypertension, PTSD, etc.) vs. literal only
      - Relationship-informed queries: "What compounds treat
        conditions?" using relationship discovery vs. blind search

      Five multi-source concepts are available for cross-source
      queries: Compound (3 sources), Condition (3), Finding (3),
      Anatomy (2), Procedure (2).

   b. **Benchmark harness.** Script that runs each query pair against
      the live MCP server (via port-forward or direct cluster URL)
      and collects results. Use the existing eval script patterns
      in `scripts/eval_*.py` as reference. The harness should:
      - Run the "with ontology" path: call `describe_ontology` first,
        extract local names, query each source with correct terms
      - Run the "without ontology" path: query with the canonical
        name only (what an agent would do without ontology tools)
      - Record hits, scores, and which chunks were returned

   c. **Metrics computation.** For each query pair, compute:
      - Recall@k: did the ontology path surface relevant chunks
        the raw path missed?
      - Unique-source coverage: how many distinct sources returned
        results with vs. without ontology?
      - Authority score correlation: do higher-authority-score
        mappings produce better retrieval results?

   d. **Report.** Summary output (JSON + human-readable) with
      per-dimension and aggregate metrics. Include the query sets
      and raw results for reproducibility.

   **Sequencing.** Query set design first (a), then harness (b) and
   metrics (c) together, report last (d).

**Constraints for the session:**
- The benchmark measures the *deployed* MCP server. Ensure port-forward
  to 5434 (Postgres) is running for ontology lookups, and the MCP server
  pod is healthy.
- Use `127.0.0.1` not `localhost` for local Postgres connections.
- The eval scripts in `scripts/eval_*.py` use psycopg and direct DB
  queries. The benchmark can use the same pattern, or call the MCP
  tools via the retrieval-hub Python client if available.
- Authority scores are advisory. The benchmark should measure whether
  they correlate with retrieval quality, not enforce them.
- Do not change the ontology registry or MCP server code. This is a
  measurement session, not a feature session.

**Session start protocol:**
- Premise checks: verify MCP server pod is running and healthy
  (`curl /health`). Verify port-forward to 5434 is active. Run
  `describe_ontology` (via port-forward or test script) to confirm
  authority scores are present. Check `git log --oneline -5` for
  unexpected commits.
- Rules with history: MCP server deploys to gpt-oss-120b cluster
  context (not mcp-rhoai). Use `127.0.0.1` not `localhost` for
  Postgres. Container deploys need explicit dep verification.
- Stop-and-ask before: any changes to the ontology registry schema
  or MCP server code (this is a measurement session).
- Close ritual: session summary + `/plan-next-session` per convention.

### Definition of done

- 10-15 paired query sets covering cross-source resolution, hierarchy
  expansion, and relationship discovery.
- Benchmark harness that runs both paths and records results.
- Recall@k and source coverage metrics reported with and without
  ontology.
- Human-readable report summarizing whether the ontology layer helps.

## Remaining epic phases

The arc goes from lightweight registry (Phase 1-2) through biomedical
hierarchy support (Phase 3-4) to production governance (Phase 5-6).
Phases 1-5a are done. Phases 5b and 6 are production hardening and
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

Phase 5a shipped: `authority_score` column on `ontology_mapping` with
scoring heuristics (source status, family weight, cross-source
agreement). `describe_ontology` returns mappings sorted by score
descending. Seed script applied to cluster DB (53 mappings, scores
0.720-1.248). MCP server redeployed.

See `session-summaries/2026-09-08-ontology-authority-scoring.md`.

**Closed:** #55 — disambiguation and authority ranking

**Commits:** 1518e7e, 5616241, 9f9e8a1, 5d3877f

**Prior sessions (same day):** Phases 1-4 also shipped. Closed
#49, #50, #51, #52, #53, #54.

## Watch out for

- Alembic migration chain — current head is `c3d4e5f6a7b8`.
- The MCP server uses alias imports to avoid Pydantic/ORM name
  collisions: `OntologyConceptModel`, `OntologyRelationshipModel`.
- Authority scores are advisory — don't gate retrieval on them.
  The benchmark should measure whether they correlate with quality.
- Per-source alias fallback must remain functional for sources not
  yet in the registry.
- The `semantic_context.authority_weight` override is undocumented
  for data owners — document it if benchmarking validates the scores.
- All sources are currently `curated` status, so status weight alone
  provides no differentiation. Family weight is the primary signal.

## If blocked

- If the benchmark design turns out to be larger than expected,
  start with a minimal version: 5 paired queries for cross-source
  concept resolution only (the strongest signal), skip hierarchy and
  relationship dimensions initially.
- #56 (drift detection) is independently workable and doesn't depend
  on benchmark results.
