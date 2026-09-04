# Enterprise Ontology Platforms: Landscape Research

**Date:** 2026-09-04
**Context:** Informing the design of RetrievalHub's ontology registry (#48).
RetrievalHub already ships a lightweight per-source alias resolution via
`SemanticContext.entities[].aliases`. This research surveys how major
platforms handle ontology, concept mapping, and the relationship between
ontology and retrieval — to identify gaps and inform the full feature arc.

## Platforms surveyed

### Palantir Ontology (Foundry)

Palantir treats ontology as the central organizing layer for all data
interaction. Object types are backed by datasets; each type has
properties, links to other types, and actions (write-back operations).

**Key feature: Interfaces.** Palantir uses "interfaces" for polymorphism.
An abstract type like "Facility" can be implemented by concrete object
types from different backing datasets (e.g., "Hospital" from FHIR,
"Clinic" from an EHR export). Queries against the interface return
results from all implementing types. This is the closest analog to our
canonical concept → per-source local name pattern, but with one level
of abstraction rather than deep hierarchies.

**Ontology-as-API.** Palantir recently shipped an MCP server that
exposes the ontology as tool calls. Agents discover object types, query
objects, and traverse links without knowing the backing data format.
The ontology is the API surface; the data sources are implementation
details.

**Relevance to RetrievalHub:** The interface pattern validates our
canonical concept approach. The MCP server precedent confirms that
ontology discovery should be a first-class agent-facing tool.

### Databricks Unity Catalog + Genie Ontology

Unity Catalog is Databricks' governance layer. Genie Ontology (preview,
June 2026) auto-infers a knowledge graph from tables, query logs, and
dashboards.

**Key feature: OntoRank.** When multiple sources define the same term
differently, Genie Ontology uses a PageRank-like scoring algorithm
("OntoRank") to rank definitions by provenance, freshness, usage
frequency, and certification status. The highest-ranked definition
becomes the canonical one. This addresses the disambiguation problem
that flat mappings ignore.

**Auto-inference.** Rather than requiring manual ontology curation,
Genie infers entity types and relationships from usage patterns. A
column that's frequently joined on becomes a foreign key relationship
in the ontology; a metric that's queried often gets promoted.

**Relevance to RetrievalHub:** OntoRank is relevant if our source count
grows and concept conflicts arise. Auto-inference is less applicable
since our sources are curated, but the idea of deriving ontology from
usage (query logs, refine patterns) is interesting for future
prioritization of concept mappings.

### Google Knowledge Catalog (Dataplex v2)

Google's approach centers on a business glossary with structured term
management.

**Key feature: Synonym and related-term relationships.** Each glossary
entry can declare synonyms (equivalent terms) and related terms (weaker
association). This is richer than our flat alias list — it distinguishes
between "these are the same concept" and "these are related but
different."

**Gemini-powered drift detection.** Google uses Gemini to flag when
glossary definitions diverge from actual column statistics and query
patterns. If the glossary says "blood_pressure is systolic" but the
column contains diastolic values, it raises an alert.

**Hierarchical categories.** Terms are organized into a category tree,
enabling broad queries ("show me all cardiovascular terms") that
resolve to specific entries.

**Relevance to RetrievalHub:** The synonym vs. related-term distinction
is worth adopting. Drift detection is valuable as a quality signal but
lower priority than core mapping features.

### AWS Glue Data Catalog

AWS Glue focuses on schema management and classification.

**Key feature: Skill assets (June 2026 preview).** Skill assets bundle
query patterns, usage rules, and data definitions into a single
artifact that agents consume. This is directly analogous to our
`usage_rules` and `sample_prompts` pattern — AWS arrived at the same
design independently.

**Classifiers.** Glue can auto-classify columns by content (PII, date,
identifier) using built-in and custom classifiers. This is orthogonal
to concept mapping but useful for governance.

**Weakness:** No cross-source concept alignment. Each catalog entry is
independent; there's no "these two tables describe the same entity"
mechanism.

**Relevance to RetrievalHub:** Validates our usage_rules design. The
classification pattern could inform future data governance features
but isn't directly relevant to ontology.

### dbt Semantic Layer

dbt's semantic layer defines metrics, entities, and dimensions as code.

**Key feature: Ontology as correctness guarantee.** If the agent picks
the right metric and dimensions from the semantic layer, the generated
SQL is deterministically correct. The ontology eliminates an entire
class of errors (wrong joins, wrong aggregations) by construction.

**Limitation:** Single-warehouse focus. dbt doesn't handle cross-source
concept alignment — all data lives in one warehouse.

**Relevance to RetrievalHub:** The "correctness by construction" idea
is powerful. If our ontology registry knows that "Condition" in FHIR
and "Disorder" in SNOMED refer to the same concept, an agent using
`doc_section=["Condition"]` gets correct results across sources by
construction. This is the core value proposition of the registry.

### Apache Atlas

Atlas is the most mature open-source metadata and governance platform,
originally from the Hadoop ecosystem.

**Key feature: Type inheritance.** Atlas supports full type hierarchies
with supertypes and subtypes. A "ClinicalEntity" supertype can have
"Condition", "Procedure", and "Observation" subtypes. Queries against
the supertype match all subtypes. This is the feature most directly
applicable to our SNOMED-CT use case, where the concept hierarchy is
19 levels deep.

**Classification propagation.** When a classification (tag) is applied
to a type, it automatically propagates through lineage to all
downstream entities. Tag a source table as "PHI" and every derived
dataset inherits the classification.

**Business glossary.** Atlas maintains a glossary of business terms with
categories, related terms, and assigned entities. Terms can be linked
to technical metadata (tables, columns, types).

**Relevance to RetrievalHub:** Type inheritance is the single most
important feature for our biomedical domain. Classification propagation
could inform future governance features (e.g., propagating
usage_rules through ontology relationships).

### Stardog

Stardog is an enterprise knowledge graph platform built on RDF/OWL
standards.

**Key feature: OWL reasoning.** Stardog uses formal ontology reasoning
to infer relationships. `owl:sameAs` declares equivalence between
entities across sources; `rdfs:subClassOf` defines hierarchies. The
reasoner automatically expands queries to include inferred matches.

**Virtual graphs.** Stardog can query heterogeneous sources (SQL
databases, REST APIs, CSV files) through virtual graphs — unified
query interface without copying data. The ontology layer maps between
the virtual schema and physical sources at query time.

**SHACL validation.** Stardog validates data against ontology
constraints expressed in SHACL (Shapes Constraint Language). This
catches drift: if a source stops conforming to the expected schema,
validation fails explicitly.

**Relevance to RetrievalHub:** Stardog represents the full-featured
end of the spectrum. OWL reasoning and virtual graphs are powerful but
heavy. The key takeaway is that formal reasoning over hierarchies
(even simplified) unlocks query expansion that flat mappings cannot
match. SHACL-style validation is the gold standard for drift detection.

## Gap analysis

Five capabilities that our flat canonical_name → (source, local_name)
mapping does not provide, ordered by estimated value for RetrievalHub:

### 1. Hierarchical concepts (is-a relationships)

**What it enables:** An agent searching for "Cardiovascular Disease"
automatically finds "Hypertension", "Heart Failure", and all subtypes
without enumerating them. SNOMED-CT, which we already serve, is a
19-level hierarchy. Without is-a support, agents must know the exact
leaf-level concept name to query effectively.

**Who does it:** Atlas (type inheritance), Stardog (rdfs:subClassOf),
Google (category trees), Palantir (interfaces, one level only).

**Complexity:** Medium. We already have SNOMED hierarchy data in
Memgraph. The registry needs parent/child edges between canonical
concepts and a query-time expansion that walks up/down the tree.

### 2. Ontology-as-discovery-API

**What it enables:** Agents ask "what concepts exist?" and "how are
Compound and Disease related?" at runtime. This eliminates hardcoded
domain knowledge in agent prompts and enables generic agents to work
with any RetrievalHub deployment.

**Who does it:** Palantir (Ontology MCP server), dbt (metric/entity
listing), Atlas (REST API over types and glossary).

**Complexity:** Low-medium. Primarily a new MCP tool that queries the
registry. The registry data already exists (or will, after Phase 1).

### 3. Cross-concept relationship types

**What it enables:** Beyond "these names are equivalent," the registry
captures that "Compound treats Disease" and "Gene associates Disease."
An agent can discover traversal paths programmatically rather than
relying on hardcoded refine strategies.

**Who does it:** Stardog (OWL object properties), Palantir (link types),
Atlas (relationship definitions).

**Complexity:** Medium. We already have `RelationshipHint` in
`SemanticContext` and edge types in Memgraph. The registry would
aggregate these cross-source into canonical relationship types.

### 4. Disambiguation and authority ranking

**What it enables:** When "Condition" means different things across
sources (a FHIR resource type vs. a SNOMED semantic tag vs. a clinical
note section header), the registry ranks which interpretation is
canonical based on provenance, usage, and curation status.

**Who does it:** Databricks (OntoRank), Google (Gemini-powered
resolution).

**Complexity:** Medium-high. Requires usage telemetry (which queries
hit which mappings) and a ranking model. Low priority while our
sources are all curated by the platform team.

### 5. Drift detection and validation

**What it enables:** The registry detects when source schemas evolve
in ways that break ontology mappings. A source that renames "Condition"
to "ClinicalCondition" triggers an alert rather than silently returning
no results.

**Who does it:** Google (Gemini drift detection), Stardog (SHACL
validation), Atlas (classification propagation detects lineage breaks).

**Complexity:** Medium. Could be implemented as a periodic validation
job that checks whether mapped local_names still exist in the source's
doc_section values.

## The coupling question: RAG and Ontology

The platforms above fall into two camps on whether retrieval (RAG) and
ontology should be tightly coupled:

**Tightly coupled (Palantir, Stardog):** The ontology IS the query
interface. You don't write queries; you navigate the ontology. Retrieval
is an implementation detail. This produces the best agent experience —
agents never see source-specific details — but requires the ontology to
be comprehensive and correct. Gaps in the ontology mean gaps in access.

**Loosely coupled (dbt, AWS Glue, Atlas):** The ontology is metadata
ABOUT the data, not the access path. You can still query directly; the
ontology helps you find the right query. More forgiving of incomplete
ontology — direct access is always available as a fallback.

**RetrievalHub's position today:** Loosely coupled. Agents call
`retrieve(source="fhir-hypertension", doc_section=["Condition"])` —
they name the source and the entity type directly. The ontology (alias
resolution) is a convenience layer that expands the filter, but the
agent still drives.

**The case for tighter coupling:** As source count grows, requiring
agents to know source slugs becomes a bottleneck. An ontology-first
interface — `retrieve(concept="Condition")` that automatically fans out
to all sources with that concept — would be more ergonomic. The
multi-source retrieve (`source="*"`) already moves in this direction.

**The case for staying loose:** Tight coupling requires the ontology to
be complete and correct. A missing mapping means invisible data. For a
platform with curated sources and expert users, the loose approach
(agents know source names, ontology is opt-in convenience) is safer and
more transparent. The agent can always bypass the ontology.

**Recommendation:** Move incrementally toward tighter coupling. The
registry starts as metadata (Phases 1-2), becomes a discovery API
(Phase 3), and eventually supports concept-first retrieval (Phase 4+).
At each stage, direct source-level access remains available. The agent
chooses how much to rely on the ontology based on its confidence in the
mappings.
