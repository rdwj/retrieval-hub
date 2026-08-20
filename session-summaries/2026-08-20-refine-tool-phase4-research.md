# Session Summary: refine-tool Phase 4 (entity-arc research)

**Date:** 2026-08-20
**Epic:** refine-tool
**Phase:** 4 — Entity-arc retrieval (research)
**Outcome:** Research complete. Entity-arc retrieval is feasible. Design documented.

## What happened

Investigated whether the current architecture supports entity-arc
retrieval — tracing an entity's mentions across a document in structural
order (GitHub #28).

### Key finding: wrong embedding model invalidated first experiment

The initial empirical run used `nomic-ai/nomic-embed-text-v1.5` with
`search_query:` prefix against VA CPG data that was indexed with
`NeuML/pubmedbert-base-embeddings` (no prefix). This produced near-zero
similarity scores (0.03-0.06) and zero overlap with keyword matches.
The fix: read the embedding model from the recipe version's
`embedding.model` field in the catalog DB, not hardcode it.

**Lesson learned:** Any code that embeds queries must read the model
config from the recipe version. The adapter already does this via
`_embedding_model_name()` and `_query_prefix()`. Research scripts must
do the same.

### Corrected results

With PubMedBERT (correct model), entity-scoped filtered ANN search
produces meaningful results:

- "SSRIs": scores 0.39-0.56, top hits in Recommendations and Discussion
- "sertraline": 0.41-0.51, concentrating in pharmacotherapy sections
- "prazosin": 0.25-0.52, with the top hit (0.52) directly discussing
  prazosin treatment evidence
- "Cognitive Processing Therapy": 0.39-0.50, correctly finding therapy
  sections

### doc_section ordering is unreliable

13 of 19 multi-chunk sections in the PTSD CPG are fragmented.
`chunk_index` is the only valid structural ordering signal. `doc_section`
is useful as a label but not for ordering.

### Hybrid approach needed

Vector search alone misses 7 of 15 literal SSRI mentions (47% recall
gap). A hybrid vector+keyword union recovers all mentions (27 total
chunks) at the cost of higher token counts.

### Token budget is the binding constraint

27 chunks at 512 tokens = 13,824 tokens. Score-weighted sampling
(select by score, present in chunk_index order) fits 7 chunks in a
4,000-token budget while preserving the most relevant arc segments.

## Design decisions

Full design in `docs/entity-arc-retrieval-research.md`. Summary:

1. New `_entity_arc_refine` adapter method: hybrid vector+keyword search
   within one document, ordered by chunk_index
2. New `_keyword_search` SQL helper with vector scores for ranking
3. `"entity_arc"` registered as a refine strategy
4. Score floor (0.30 default) filters noise from keyword-only matches
5. Existing `RefineResponse` envelope works — `origin_chunk_index`
   set to first arc chunk (or made optional later)
6. No DDL changes, no new tables, no ingestion pipeline changes

## Files created

- `docs/entity-arc-retrieval-research.md` — full research document
- `scripts/entity_arc_experiment.py` — one-off experiment script (gitignore)

## What's next

Implementation of entity-arc strategy (Phase 4 implementation session).
See design in `docs/entity-arc-retrieval-research.md`.

## Test baseline

212 core + 33 MCP tests passing. No regressions.
