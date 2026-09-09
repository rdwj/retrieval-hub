# Next Session -- Platform Quality

## Epic: Hybrid retrieval and cross-cutting quality improvements

Add BM25 lexical search alongside vector ANN for all families that use
pgvector. The single biggest retrieval quality improvement identified
across the project's eval work.

Issues: #65

## Next: to be planned via /plan-next-session

(No next-session focus selected yet. Run `/plan-next-session platform-quality`
to pick the first slice from the phases below.)

## Remaining epic phases

### Phase 1: BM25 indexing and hybrid search (#65)

Add tsvector columns to pgvector index tables, build GIN indexes, and
implement hybrid scoring (vector + BM25 with configurable alpha).

**Work:**
1. Add tsvector column and GIN index to the pgvector schema
2. Populate tsvector during ingestion (or backfill existing tables)
3. Implement hybrid scoring in the retrieval path (RRF or weighted sum)
4. Benchmark on VA CPG and aircraft sources: measure lift on
   navigation queries ("where is X defined?", exact term lookup)

**Definition of done:** `retrieve` returns hybrid-scored results.
Benchmark shows improvement on exact-match and navigation queries
without regression on semantic queries.

**Dependencies:** None. Independent of other epics.

**Parallel-ok:** Yes — no overlap with platform-ops or ontology-v2.

## What this covers (and what it doesn't)

**In scope:**
- #65 Hybrid retrieval (BM25 + vector)

**Out of scope:**
- Platform ops (NEXT_SESSION-platform-ops.md): #27, #66, #67, #70
- Ontology v2 (NEXT_SESSION-ontology-v2.md): #61-64, #68
- Reranking (already evaluated and declined for current config)
- Query rewriting (#15, closed — already shipped)
