# Entity-Arc Retrieval: Research Findings

Research phase for GitHub issue #28. Investigates whether the current
architecture can support tracing an entity's mentions across a document
in structural order.

## Research questions and answers

### 1. Does entity-scoped filtered search produce a usable arc?

**Yes, with qualifications.** Embedding the entity name and filtering to
one document with `WHERE doc_title = %s` produces semantically relevant
results when using the correct embedding model (PubMedBERT for VA CPG
data). Scores range from 0.39-0.56 for entity names like "SSRIs" and
0.52 for specific drugs like "prazosin."

The critical prerequisite is using the same embedding model that produced
the stored vectors. The recipe version's `embedding.model` field
(retrieved from the catalog DB) must be used — not hardcoded. The VA CPG
data uses `NeuML/pubmedbert-base-embeddings` with no query/document
prefix, not the Nomic v1.5 model used by the code source.

When ordered by `chunk_index`, the top-20 vector results for "SSRIs"
trace a recognizable pathway through the PTSD CPG: treatment selection
sidebars (chunks 17-19) -> recommendations (chunks 33-37) -> evidence
discussion (chunks 46-74) -> appendix material (chunks 96-156).

**Qualification:** Vector search alone misses 7 of 15 chunks containing
the literal string "SSRI." Keyword matches at chunks 17, 75, 92, 95,
109, 158, and 190 fall outside the vector top-20. A hybrid approach
(vector union keyword) recovers all mentions at the cost of more total
chunks (27 vs 20).

### 2. Is doc_section ordering sufficient for structural position?

**No.** 13 of 19 multi-chunk sections in the PTSD CPG are fragmented —
their chunks do not form contiguous index ranges. Extreme examples:

- "References" spans chunk indices 22-209 (188 index range, 52 chunks)
- "Table of Contents" spans 1-157 (10 chunks scattered across 157 indices)
- "IX. Recommendations" spans 35-113 (13 chunks across 79 indices)

`chunk_index` ordering is the only reliable structural signal. Chunks are
numbered sequentially through the document, so sorting by `chunk_index`
produces document-order regardless of section fragmentation.

`doc_section` remains useful as a label (telling the agent "this chunk is
from the Discussion section") but not as an ordering key.

### 3. How should the response shape differ from cross_reference?

Entity-arc differs from cross_reference in three structural ways:

| Property | cross_reference | entity_arc |
|---|---|---|
| Scope | Cross-document (related CPGs) | Single document |
| Ordering | By relevance score | By chunk_index (structural position) |
| Origin | One specific chunk | No single origin — the arc IS the result |

The current `RefineResponse` envelope works for entity-arc with minor
reinterpretation:

- `origin_chunk_index` is meaningless for entity-arc (there's no single
  origin chunk). Could be set to -1 or the first arc chunk's index.
  Better: make it optional on the schema.
- `is_origin` on `RefineHit` is meaningless. All hits are arc members.
- `doc_title`/`doc_url` per-hit are null (single-document strategy, like
  section/adjacent).
- A new field `total_arc_mentions` (total entity mentions found before
  token truncation) would help agents understand coverage.

**Recommendation:** The existing `RefineResponse` envelope can serve
entity-arc without adding new models. The `strategy` field already
distinguishes behavior. Two envelope-level changes are worth considering:

1. Make `origin_chunk_index` optional (or accept -1 for arc strategies)
2. Add `total_arc_mentions: int | None` for arc strategies

These are additive, backward-compatible changes.

### 4. What's the token budget story?

The SSRI arc across the PTSD CPG produces 27 chunks (hybrid) at 512
tokens each = 13,824 tokens. At a 4,000-token budget, only 7 chunks fit.

**Recommended strategy: score-weighted sampling in chunk_index order.**

1. Collect all candidates (vector top-K union keyword matches)
2. Apply a minimum score threshold (0.30) to remove noise — this drops
   Table of Contents, Abbreviations, and very weak keyword hits
3. If total tokens exceed budget, select chunks by descending score until
   budget is filled, then re-sort selected chunks by chunk_index for
   presentation
4. Report `truncated=true` and `total_arc_mentions=N` so the agent knows
   the arc was sampled

This mirrors the cross_reference token strategy but re-sorts by position
instead of keeping score order.

## Implementation design

### New adapter method: `_entity_arc_refine`

```
def _entity_arc_refine(
    self,
    *,
    doc_title: str,
    chunk_index: int,        # ignored; kept for interface compat
    query: str,              # entity name or description
    window: int,             # max vector results (top_k)
    request_id: str,
    max_context_tokens: int | None = None,
) -> RefineOutput:
```

Steps:
1. Embed `query` using the source's configured embedding model
2. Filtered ANN search: `WHERE doc_title = %s ORDER BY embedding <=> vec LIMIT window`
3. Keyword search: `WHERE doc_title = %s AND chunk_text ILIKE '%query%'`
4. Union by chunk_index, keeping the higher score for duplicates
5. Apply score floor (0.30) to keyword-only matches with low vector relevance
6. Sort by chunk_index
7. Token budgeting: if over budget, select top-scoring chunks and re-sort by position
8. Return `RefineOutput` with ordered results

### Entity alias handling

The `EntityDefinition.aliases` field provides alternate names (e.g.,
"SSRIs" has alias "selective serotonin reuptake inhibitors"). The keyword
search leg should search for the entity name AND all aliases. Vector
search handles this implicitly through semantic similarity.

For the first implementation, the `query` parameter carries the entity
name. Aliases can be resolved from `SemanticContext.entities` if the
query matches an entity name.

### New SQL method needed

```python
def _keyword_search(
    self,
    pattern: str,
    doc_title: str,
    query_vec: list[float],
) -> list[dict]:
    """Keyword search within a document, with vector scores for ranking."""
```

This runs `WHERE doc_title = %s AND chunk_text ILIKE %s` but also
computes the cosine similarity score so keyword-only results can be
ranked alongside vector results.

### MCP tool changes

The `refine` tool's `strategy` parameter accepts `"entity_arc"` as a new
value. No new parameters needed — `query` carries the entity name,
`window` controls vector top-k, `max_context_tokens` controls budget.

`doc_title` and `chunk_index` are required by the current interface but
`chunk_index` is meaningless for entity-arc. Options:
- Accept any chunk_index (ignore it internally)
- Make chunk_index optional on the MCP tool (breaking change)
- Accept chunk_index=0 as a convention for "no specific origin"

**Recommendation:** Accept any chunk_index, ignore it internally for
entity_arc strategy. Document this in the tool docstring.

### Configuration

Add to `RefinementStrategy` configs:
```yaml
- kind: entity_arc
  window: 20          # vector top-k
  enabled: true
  max_context_tokens: 4000
  min_score: 0.30     # score floor for noise filtering
```

`min_score` is a new field on `RefinementStrategy`. Default: null (no
floor). Only meaningful for entity_arc.

## What this research does NOT cover

- **Cross-document entity arcs** (e.g., tracing SSRIs across PTSD + SUD
  + MDD CPGs). The cross_reference strategy already provides cross-document
  retrieval; entity-arc focuses on within-document narrative structure.
- **Co-reference resolution** (recognizing that "the medication" in one
  chunk refers to "sertraline" in a previous chunk). PubMedBERT's semantic
  similarity handles some of this implicitly but not reliably.
- **Section-type filtering** (excluding appendix/references sections from
  arcs). This would require section-type metadata that doesn't exist in
  the current schema. Score thresholds provide a rough approximation.

## Risk assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Short entity names embed poorly | Low (PubMedBERT handles "SSRIs" at 0.56) | Fall back to keyword-only if vector scores are all below threshold |
| Token budget too small for useful arc | Medium | Default to 4,000 tokens; agent can request more |
| Keyword search too broad (common terms) | Medium | Score floor filters low-relevance keyword hits |
| Performance (two queries per refine call) | Low | Both queries hit the same pgvector index; keyword search is fast |

## Verdict

Entity-arc retrieval is feasible with the current architecture. The
approach — hybrid vector+keyword search within a document, ordered by
chunk_index, with score-based token truncation — builds on existing
infrastructure (`_filtered_similarity_search`, token budgeting,
`RefineOutput`). Implementation requires one new adapter method, one new
SQL helper, and registration of `"entity_arc"` as a strategy.

Estimated implementation: one session. No DDL changes, no new tables, no
changes to the ingestion pipeline.
