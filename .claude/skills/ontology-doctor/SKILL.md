---
name: ontology-doctor
description: >
  Audit ontology health and propose fixes. Checks for dead mappings,
  family mismatches, score clustering, missing mappings, stale mappings,
  and coverage gaps. Report-first with optional --apply for safe fixes.
  Use after adding sources, changing ontology mappings, or periodically
  to catch drift.
---

# Ontology Doctor

Audit the ontology registry for health issues and propose fixes.

## When to use

- After adding a new source or ingesting new data
- After modifying ontology mappings or the concept hierarchy
- Periodically (monthly or pre-release) to catch drift
- When retrieval results seem worse than expected for ontology-assisted queries
- When the benchmark shows regressions

Triggers: "ontology doctor", "audit ontology", "check ontology health",
"ontology drift", "dead mappings", "stale mappings"

## Prerequisites

This skill requires direct database access, not the deployed MCP
server (which is OAuth-protected and doesn't expose ontology tables
directly). Before running:

1. Port-forward the catalog DB:
   `oc port-forward svc/retrieval-hub-db 5434:5432 --context=gpt-oss-120b -n retrieval-hub`

2. For retrieval-based checks (dead mappings), also port-forward the
   embedding service:
   `oc port-forward svc/retrieval-hub-embedding 8081:8080 --context=gpt-oss-120b -n retrieval-hub`

Connection strings use `127.0.0.1` (not `localhost`) per project convention.

## Arguments

- No arguments: full audit across all sources and concepts
- `source=<slug>`: audit a single source
- `concept=<name>`: audit a single concept
- `--apply`: apply safe fixes (add missing mappings, re-run authority
  score computation after adding)
- `--skip-retrieval`: skip checks that require the embedding service
  (dead mapping detection). Useful when only the DB port-forward is up.
- `--json`: write machine-readable report to a file instead of
  human-readable console output
- `--include-retired`: include RETIRED sources in the audit (excluded
  by default since stale mappings on retired sources are not actionable)

## Check catalog

### 1. Missing mappings (static, always runs)

Compare each source's `semantic_context.entities[].entity_type`
values against `ontology_mapping.local_name` rows for that source.
Entity types present in the source but not in the ontology registry
are "unmapped." These represent concepts the ontology layer cannot
resolve for this source.

The comparison field is `entity_type` (not `name`), because
`entity_type` is what populates the `doc_section` column during
graph chunking, and `ontology_mapping.local_name` corresponds to
`doc_section` values.

Only CURATED and PUBLISHED sources are checked by default.

**Severity**: INFO for sources that are not yet onboarded to the
ontology. WARN for sources that have some mappings but are missing
others.

**Auto-fix (--apply)**: When an unmapped entity type name exactly
matches an existing `canonical_name` in the registry, add a mapping.
After all additions, re-run `compute_authority_scores` to set proper
scores (do not leave mappings at the default 1.0 while siblings
have computed scores). Use INSERT ON CONFLICT DO NOTHING to make
`--apply` idempotent. When no canonical name matches, report as
"needs manual mapping" with suggested canonical names (fuzzy match
against existing canonicals).

### 2. Stale mappings (static, always runs)

Check each `ontology_mapping.local_name` against the source's actual
data. For graph-family sources, check if the local_name exists as a
`doc_section` value in the chunks table (requires the vectors DB
connection, not just the catalog DB). For document-family sources,
check if the local_name exists in `semantic_context.entities`.

A mapping is stale when the local_name no longer exists in the source
data, meaning the ontology references an entity type that was removed
or renamed.

**Severity**: WARN. Stale mappings cause the ontology to advertise
capabilities the source cannot fulfill.

**Auto-fix (--apply)**: Flag stale mappings in the report. Do NOT
auto-remove -- stale mappings could indicate a re-ingestion issue
rather than a genuine removal.

### 3. Family mismatches (static, always runs)

Detect hierarchy relationships where a parent concept has mappings
in both graph and document-family sources. When hierarchy expansion
is used, the child concepts would be routed differently depending on
family. This is expected behavior (not a bug), but worth flagging
when a concept's children are mapped only to document sources and
would never appear as doc_section filters.

**Severity**: INFO. For awareness, not action.

### 4. Score clustering (static, always runs)

Analyze the distribution of authority scores across all mappings.
Flag when:
- All scores fall within a range narrower than 0.3 (insufficient
  differentiation)
- Multiple concepts share identical maximum scores
- The score formula produces the same result for all mappings of a
  given concept (no within-concept differentiation)

**Severity**: WARN when the range is too narrow for the score to
provide a useful ranking signal.

**Auto-fix**: None. Score formula changes are design decisions.

### 5. Coverage gaps (static, always runs)

For each canonical concept mapped to 2+ sources, check if any source
that *could* have this concept (based on family and domain) is
missing a mapping. Uses heuristics:
- Graph sources in the same domain (e.g., all clinical graph sources)
  should share the same concept set
- Clinical document sources that mention a condition name in their
  content but lack a mapping for it

**Severity**: INFO. Suggestions, not requirements.

### 6. Dead mappings (requires embedding service)

For each mapping, run a retrieval query using the `local_name` as
both doc_section filter and query text, against the mapped source.
A mapping is "dead" when it produces zero retrieval hits -- the
ontology claims the source has this concept, but no chunks match.

**Severity**: WARN. Dead mappings waste agent effort and return
empty results.

**Auto-fix**: None. Dead mappings could indicate an ingestion issue,
a stale index, or genuinely sparse data. Report for human review.

**Skip**: This check is skipped when `--skip-retrieval` is passed.

### 7. Duplicate mappings (static, always runs)

Detect when a source has multiple mappings for the same canonical
name with different local names. This is valid when the source
genuinely uses multiple terms for the same concept (e.g., SNOMED
might use both "Disorder" and "Clinical Finding"), but can also
indicate a data entry error.

**Severity**: INFO.

### 8. Orphan concepts (static, always runs)

Find `ontology_concept` rows whose `name` does not appear as a
`canonical_name` in any `ontology_mapping` row. These are concepts
defined in the hierarchy that no source has mapped. Could be
placeholder parents (expected) or concepts that lost their mappings.

**Severity**: INFO.

### 9. Dangling relationship references (static, always runs)

Find `ontology_relationship` rows where `source_concept` or
`target_concept` does not exist in `ontology_concept.name`. Unlike
the concept hierarchy (which has an FK constraint), relationships
have no FK to `ontology_concept`, so dangling references can
accumulate when concepts are renamed or removed.

**Severity**: WARN. Dangling references cause `describe_ontology`
to return relationships pointing to concepts that don't exist.

## Output format

### Console output (default)

Human-readable report printed to stdout, grouped by check type:

```
Ontology Health Report
======================
Checked: 11 sources, 44 concepts, 53 mappings

Missing Mappings (6 sources with gaps)
--------------------------------------
  aircraft-maintenance: 0 of 4 entity types mapped [INFO]
    Unmapped: Task, SubTask, Zone, Figure
  pubmed-hypertension: 0 of 3 entity types mapped [INFO]
    Unmapped: Article, Author, MeSH Term

Stale Mappings (0 found)
------------------------
  (none)

Score Clustering
----------------
  Range: 1.040 - 1.248 (spread: 0.208) [WARN: < 0.3]
  5 concepts share max score 1.248

Dead Mappings (2 found, embedding service checked)
---------------------------------------------------
  tale-of-two-cities / "Jerry Cruncher": 0 hits [WARN]
  tale-of-two-cities / "Miss Pross": 0 hits [WARN]

Summary: 2 WARN, 8 INFO
```

### JSON output (--json)

Machine-readable report written to a file. Structure:

```json
{
  "timestamp": "2026-09-08T22:00:00Z",
  "checks": {
    "missing_mappings": [...],
    "stale_mappings": [...],
    "family_mismatches": [...],
    "score_clustering": {...},
    "coverage_gaps": [...],
    "dead_mappings": [...],
    "duplicate_mappings": [...]
  },
  "summary": {
    "sources_checked": 11,
    "concepts_checked": 44,
    "mappings_checked": 53,
    "warn_count": 2,
    "info_count": 8
  }
}
```

## Implementation notes

### Database access pattern

Use the same direct DB access pattern as the benchmark script
(`scripts/eval_ontology_benchmark.py`):

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(db_url)
SessionLocal = sessionmaker(bind=engine)
with SessionLocal() as session:
    # run checks
```

Connection string defaults:
- Catalog: `postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub`
- Vectors: `postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub_vectors`

### Which checks need which connections

| Check | Catalog DB | Vectors DB | Embedding svc |
|-------|:---:|:---:|:---:|
| 1. Missing mappings | Y | | |
| 2. Stale mappings | Y | Y (graph sources) | |
| 3. Family mismatches | Y | | |
| 4. Score clustering | Y | | |
| 5. Coverage gaps | Y | | |
| 6. Dead mappings | Y | Y | Y |
| 7. Duplicate mappings | Y | | |
| 8. Orphan concepts | Y | | |
| 9. Dangling relationships | Y | | |

The catalog DB is always required. The vectors DB is needed for
checks that inspect actual chunk data. The embedding service is
only needed for dead mapping detection (live retrieval queries).

### Retrieval for dead mapping checks

Use `retrieval_hub.retrieval.api.query()` with monkey-patched
embedding endpoint (same approach as the benchmark). This avoids
needing the MCP client or OAuth.

### Script location

`scripts/ontology_doctor.py` -- standalone script that the skill
invokes. Not inside the skill directory, because it needs access to
`retrieval_hub` imports and should be runnable independently.

### GitHub issue creation

Not in v1. The report is sufficient for human review. If patterns
emerge (repeated stale mappings from the same source, consistent
dead mappings), a future version could auto-create tracking issues.

## Design decisions log

- **Direct DB over MCP**: The deployed MCP server is OAuth-protected
  and would require token management. Direct DB via port-forward is
  simpler and matches the benchmark pattern. The doctor is a
  developer tool, not an agent-facing API.

- **Report-first over auto-fix**: Ontology mappings affect retrieval
  for all agents. Auto-removing a "stale" mapping that turns out to
  be a transient ingestion issue would degrade retrieval. Safe
  additions (exact canonical name matches) are the only auto-fix.

- **Embedding service optional**: Some checks (dead mappings) need
  the embedding service for retrieval queries. Making it optional
  lets the doctor run with just the DB port-forward for quick static
  audits.

- **No concept-first retrieval dependency**: The doctor audits the
  registry as-is. It does not depend on Phase 6 (concept-first
  retrieval) and should work with the current source-level API.
