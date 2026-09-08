# Ontology Benchmark Findings and Recommendations

## Benchmark summary

Ran 12 paired queries comparing retrieval with vs. without the ontology
registry, across three dimensions. Full results in
`eval/ontology_benchmark/runs/20260908-213957/`.

| Dimension | Queries | Win Rate | Avg Hit Lift | Avg Source Lift |
|-----------|---------|----------|-------------|----------------|
| Cross-source | 5 | 80% | +6.2 | +1.4 |
| Hierarchy | 4 | 0% | -4.5 | -0.5 |
| Relationship | 3 | 100% | +7.0 | +0.7 |
| **Overall** | **12** | **58%** | **+2.8** | **+0.6** |

## What works

### Cross-source concept resolution

When a concept has different local names across sources (Condition maps
to Disease in Hetionet, Disorder in SNOMED, Condition in FHIR), an
agent using `describe_ontology` retrieves from all sources. Without it,
the agent only hits the source where the canonical name happens to match
the local name — one source out of three.

The one non-win (xsrc-05, Procedure) is a control case: both FHIR and
SNOMED use "Procedure" as the local name, so no translation is needed.

### Relationship discovery

Discovering that Patient connects to Condition via `diagnosed_with`, or
that Compound connects to Gene via `binds/upregulates/downregulates`,
lets an agent query entity types it wouldn't otherwise know to search.
The strongest signal was rel-02 (Patient → Condition): +15 hits because
the relationship pointed the agent at Condition data across 3 sources.

## What doesn't work

### Hierarchy expansion via doc_section filtering

All 4 hierarchy queries returned fewer hits with the ontology than
without. The cause: the benchmark uses child concept names as
`doc_section` filters, but doc_section values only match entity type
names in graph-family sources. For clinical_document sources (VA CPG),
doc_section values are document structural headings ("Management of
Hypertension", "Pharmacotherapy"), not concept types ("Metformin",
"PHQ-9").

When the hierarchy expansion produces `doc_section=["Metformin"]` on
VA CPG, the filter matches nothing. The "without ontology" path, which
uses no doc_section filter at all, gets 5 hits from the full-text search.

### Authority score correlation

Authority scores show no statistically significant correlation with
retrieval quality (r=0.04, p=0.77). The scores are clustered in too
narrow a range (1.04–1.248) to differentiate. All five multi-source
concepts share the same maximum score (1.248). To produce a meaningful
signal, we would need either more variation in the scoring formula or
more sources with genuinely different authority levels.

## Recommendations

### 1. Family-aware hierarchy expansion

The hierarchy expansion logic should be aware of the target source's
family. For graph-family sources, child concept names work as
doc_section filters because entity types ARE doc_sections. For
document-family sources, child concept names should be injected into
the query text rather than the doc_section filter.

Concrete proposal: when `expand_doc_section_via_registry` detects that
the source is a clinical_document or technical_document family, it
should skip hierarchy expansion on doc_section and instead return the
child names as supplementary query terms. The retrieval API could
accept an optional `expanded_terms` parameter that gets appended to
the query text before embedding.

This would make the hierarchy expansion work across both source
families, turning the 0% win rate into a positive signal.

### 2. Widen authority score range

The current scoring formula produces a narrow range because all sources
share the same `curated` status and the family weight differences are
small. Two approaches to improve differentiation:

- **Per-source confidence signals.** Sources backed by a formal
  terminology standard (SNOMED) should score higher than sources using
  informal labels (tale-of-two-cities). The `semantic_context` already
  contains entity metadata; a boolean `formal_terminology` flag would
  feed directly into the authority formula.

- **Coverage-based scoring.** A mapping where the source has 500
  entities of that type should score higher than a mapping where the
  source has 3. The entity count is available at ingestion time and
  could feed into the authority formula as a coverage weight.

### 3. Ontology doctor skill

A Claude Code skill (`/ontology-doctor`) that runs the benchmark
harness, analyzes the results, and proposes fixes. The skill would:

- Run `eval_ontology_benchmark.py` against the current deployment
- Identify mappings that produce zero retrieval hits (dead mappings)
- Detect hierarchy expansions that harm retrieval (family mismatch)
- Flag concepts with suspiciously similar authority scores
- Propose specific fixes: new mappings, score adjustments, family-aware
  expansion rules

This is a separate session's worth of work. The skill needs design
decisions around: how much it should auto-fix vs. propose, whether it
runs against the deployed server or a local dev instance, and how it
handles the OAuth-protected MCP endpoint.

### 4. Expand benchmark coverage

The current benchmark covers 5 of 11 sources (the three graph sources
plus VA CPG and SNOMED). Adding queries that target clinical_document
sources (pubmed-hypertension), technical_document sources
(aircraft-maintenance), and tabular sources (clinicaltrials) would
test ontology value across the full source family spectrum.

## Appendix: benchmark methodology

The benchmark uses direct DB access for ontology queries and the
`retrieval_hub.retrieval.api.query` function for vector search. The
"without ontology" path disables both the registry-level expansion
(`expand_doc_section_via_registry`) and the adapter-level alias
expansion (`SourceAdapter._expand_doc_section`) via monkey-patching,
so the doc_section filter is applied literally.

This simulates what an agent would experience if the ontology layer
didn't exist: the agent queries with the concept name it knows, and the
retrieval stack applies that name literally without any cross-source
translation.

The "with ontology" path leaves both expansion layers enabled, plus
uses `describe_ontology_db` to discover per-source local names, exactly
as an agent would use the `describe_ontology` MCP tool.
