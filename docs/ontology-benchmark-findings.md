# Ontology Benchmark Findings and Recommendations

## Benchmark summary

Ran 12 paired queries comparing retrieval with vs. without the ontology
registry, across three dimensions. Latest results (after the family-aware
hierarchy fix) in `eval/ontology_benchmark/runs/20260908-220904/`.

| Dimension | Queries | Win Rate | Avg Hit Lift | Avg Source Lift |
|-----------|---------|----------|-------------|----------------|
| Cross-source | 5 | 80% | +6.2 | +1.4 |
| Hierarchy | 4 | 100% | +10.2 | +0.0 |
| Relationship | 3 | 100% | +7.0 | +0.7 |
| **Overall** | **12** | **91.7%** | **+7.8** | **+0.8** |

### Before the family-aware fix (2026-09-08, first benchmark run)

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

## What was fixed

### Hierarchy expansion: family-aware routing

The initial benchmark (2026-09-08) showed 0% win rate for hierarchy
queries because child concept names were added as `doc_section` filters
for all sources, including document-family sources where doc_section
values are structural headings, not concept types.

The fix introduced `ExpansionResult`, a return type that separates
doc_section filter values from query expansion terms.
`expand_doc_section_via_registry` now accepts a `source_family`
parameter and routes hierarchy children by family:

- **Graph sources**: children go into the `doc_section` filter (entity
  types are doc_section values)
- **Document sources**: children go into `query_terms` (appended to
  the query text before embedding)

Flat/alias expansion (stage 1) is family-agnostic and always goes into
`doc_section` since those are real local names.

The benchmark's `run_hierarchy` function was also updated to be
family-aware: for document sources, child names are used as query text
enrichment instead of doc_section filters.

Result: hierarchy went from 0% win rate / -4.5 avg hit lift to 100%
win rate / +10.2 avg hit lift with no regression on other dimensions.

## Remaining gaps

### Authority score correlation

Authority scores now show a weak positive correlation with retrieval
quality (r=0.36, p=0.006), up from the initial non-significant result
(r=0.04, p=0.77). The improvement comes from the larger hit sample
size after the hierarchy fix. The scores are still clustered in a
narrow range (1.04-1.248), and all five multi-source concepts share
the same maximum score. Widening the range would require new scoring
signals (formal terminology flag, entity count coverage).

## Recommendations

### 1. Family-aware hierarchy expansion (DONE)

Shipped in the same session as the benchmark. See "What was fixed"
above. Hierarchy went from 0% to 100% win rate.

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
