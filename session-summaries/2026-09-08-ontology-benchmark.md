# Session Summary — 2026-09-08 · ontology · Benchmark ontology-assisted vs. raw retrieval

**Plan:** NEXT_SESSION-ontology.md / #57   **Commits:** b7d9c01, (this commit) (main)
**Deployed:** none (measurement session, no server changes)   **Model:** Opus 4.6

## Plan vs. actual

Planned: 10-15 paired queries, benchmark harness, recall@k and source coverage metrics, human-readable report.
Shipped: 12 paired queries across 3 dimensions, benchmark harness with direct DB access, full metrics including authority score correlation, findings doc with recommendations.
Scope: stayed in scope. Added a recommendation doc (`docs/ontology-benchmark-findings.md`) and an ontology-doctor skill proposal beyond the original plan.

## Shipped

- `b7d9c01` — Query set (12 queries), benchmark harness (`scripts/eval_ontology_benchmark.py`), first run results with report
- (this commit) — Findings document, session summary, NEXT_SESSION update

## Key findings

Cross-source concept resolution is the ontology's strongest value proposition: 80% win rate, +6.2 avg additional hits per query. Without the ontology, agents only retrieve from sources where the canonical name happens to match the local name.

Relationship discovery also shows clear value: 100% win rate, +7.0 avg additional hits.

Hierarchy expansion via doc_section filtering hurts retrieval for non-graph sources: 0% win rate, -4.5 avg hits. Child concept names don't map to doc_section values in clinical_document sources. The fix is family-aware expansion — inject child names into query text for document sources instead of using them as section filters.

Authority score correlation is not statistically significant (r=0.04, p=0.77). Scores are clustered too narrowly (1.04–1.248) to differentiate.

## Verification & confidence

- Benchmark ran against live cluster DB (port-forwarded catalog + vectors DBs + embedding service)
- Cross-source results manually verified: querying "Condition" on Hetionet (local name: Disease) returns zero hits without ontology, 5 hits with — confirmed correct
- Hierarchy negative results explained by source family mismatch, not a bug
- Confidence: high for cross-source and relationship dimensions, which represent the primary use case. Hierarchy findings are a genuine design gap, not a measurement error.

## Judgment calls & deviations

- **MCP → direct DB**: The plan called for connecting to the MCP server via streamable-http client. The deployed server now requires OAuth, which a benchmark script can't handle programmatically. Pivoted to direct DB access + retrieval API calls. The retrieval path is identical; only the transport differs.
- **Ontology expansion bypass**: Discovered that the retrieval API already has two layers of ontology expansion (registry-level + adapter-level per-source aliases). The "without ontology" path monkey-patches both to no-ops to simulate a retrieval stack with no ontology layer. This is documented in the findings doc.
- **Hierarchy query design**: The "without ontology" path for hierarchy queries uses no doc_section filter (full-text search), not doc_section=[canonical_name]. An agent without the ontology would search freely, not restrict to a section it doesn't know.

## Backlog delta

Issue #57 remains open — the benchmark is delivered but hierarchy expansion needs a fix before the ontology can be considered validated across all dimensions.

New work identified:
- Family-aware hierarchy expansion (fix the 0% hierarchy win rate)
- Ontology doctor skill (`/ontology-doctor`) — analyze deployment health, propose fixes
- Widen authority score range for meaningful differentiation

## Drift & forward-collisions

- The `expand_doc_section_via_registry` function now has a known gap for document-family sources. Any future work on ontology-based retrieval should account for this.
- The benchmark harness monkey-patches two internal functions (`_resolve_embedding_endpoint` and `expand_doc_section_via_registry`). If those function signatures change, the benchmark will break.
