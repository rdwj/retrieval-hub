# Agent Integration Guide

How to use RetrievalHub's MCP tools effectively in multi-source workflows.

## Tools overview

| Tool | Purpose |
|------|---------|
| `list_sources` | Browse available sources with slugs, families, and document counts |
| `describe_source` | Get full metadata, sample prompts, and health status for one source |
| `retrieve` | Semantic search with optional `doc_section` and `scope_entity_id` filters |
| `refine` | Expand context around a retrieved chunk (adjacent, section, graph traversal) |
| `request_access` | Check access requirements for restricted sources |

## Source families and when to use them

**Document / clinical_document** — narrative text chunked into passages. Use `retrieve` for semantic search, `refine` with `strategy=section` to read the full section around a hit.

**Graph** — entity-centric data (FHIR patients, SNOMED ontology, Hetionet knowledge graph). Each chunk represents one entity. Use `doc_section` to filter by entity type, `scope_entity_id` to restrict to a subgraph, and `refine` with `strategy=graph_traverse_from_seed` to explore relationships.

**Tabular** — structured records (clinical trials). Each chunk is one record. Best for filtering and counting.

## Filtering retrieve results

### doc_section — filter by type

Pass a list of section names to restrict results. What counts as a "section" depends on the source family:

- **Graph sources**: entity type (e.g., `["Patient", "Condition", "MedicationRequest"]`)
- **Document sources**: section header text (e.g., `["Discussion", "Methods"]`)

### scope_entity_id — scope to a subgraph

Graph sources only. Pass a seed entity's UUID (from a previous result's `doc_title`) to restrict retrieval to all entities connected to that seed within 2 hops. Primary use case: scope FHIR queries to one patient.

Both filters compose: `scope_entity_id` + `doc_section` returns only specific entity types within the scoped subgraph.

## Multi-source workflow: treatment plan

This pattern retrieves from 5+ sources to build a clinical treatment plan.

### Step 1: Identify the patient (FHIR)

```
retrieve(query="<patient name>", source="fhir-hypertension", doc_section=["Patient"])
```

Note the patient's `doc_title` (UUID) for scoping.

### Step 2: Gather clinical data (FHIR, scoped)

```
retrieve(query="conditions diagnoses", source="fhir-hypertension",
         scope_entity_id="<patient-uuid>", doc_section=["Condition"])

retrieve(query="medications", source="fhir-hypertension",
         scope_entity_id="<patient-uuid>", doc_section=["MedicationRequest"])

retrieve(query="blood pressure vitals", source="fhir-hypertension",
         scope_entity_id="<patient-uuid>", doc_section=["Observation"])
```

### Step 3: Get treatment guidelines (VA CPG)

```
retrieve(query="hypertension treatment first-line medication",
         source="va-cpg-clinical-guidelines")
```

Include recommendation strength ratings from the results.

### Step 4: Enrich with terminology (SNOMED-CT)

```
retrieve(query="essential hypertension classification",
         source="snomed-ct-hypertension")
```

Provides ontological context: parent concepts, finding sites, subtypes.

### Step 5: Check drug context (Hetionet)

```
retrieve(query="<drug name> targets interactions",
         source="hetionet-hypertension")
```

Returns drug-gene-disease relationships, similar compounds, pharmacologic class.

### Step 6: Find evidence (PubMed)

```
retrieve(query="<drug name> hypertension outcomes evidence",
         source="pubmed-hypertension")
```

Cite the PMC URL from `doc_url` and note study design.

## Tips

- Start with `list_sources` to see what's available. Source slugs and families tell you what kind of data to expect.
- Use `describe_source` to read `sample_prompts` before querying a source for the first time. These contain source-specific guidance.
- Check `usage_rules` in retrieve responses. Some sources require specific citation formats or scope disclaimers.
- For graph sources, `refine` with `strategy=graph_traverse_from_seed` and `edge_types` is more targeted than broad retrieve. Use retrieve for discovery, refine for exploration.
- Multi-source queries (`source="*"` or comma-separated slugs) use Reciprocal Rank Fusion. Useful for broad discovery but scores aren't comparable across sources.
