# Session Summary — 2026-08-20 · refine-tool · Entity-arc retrieval research

**Plan:** NEXT_SESSION-refine-tool.md / #28   **Commits:** 8c033bd (main)
**Deployed:** none   **Model:** Opus 4.6 (1M context)

## Plan vs. actual

Planned: Research whether entity-arc retrieval is feasible with the
current architecture. Shipped: Complete research with design document.
Slipped: none. Scope: stayed in scope — research phase only, no code
changes.

## Shipped

- `8c033bd` Research document (`docs/entity-arc-retrieval-research.md`)
  answering all four research questions from the plan, plus an
  implementation design for the next session.

## Verification & confidence

- Empirical queries run against the live cluster pgvector database with
  PubMedBERT embeddings (the correct model for VA CPG data).
- Tested four entity queries (SSRIs, sertraline, CPT, prazosin) and one
  contextual query across the PTSD CPG document.
- Verified doc_section fragmentation across 19 multi-chunk sections.
- Verified hybrid vector+keyword union recall and token budget math.
- Confidence: **high** — findings are empirical, reproducible against the
  cluster, and the design builds on proven infrastructure
  (`_filtered_similarity_search`, token budgeting, `RefineOutput`).

## Judgment calls & deviations

- First experiment used wrong embedding model (Nomic v1.5 instead of
  PubMedBERT). Caught by near-zero scores and zero keyword overlap.
  Corrected by reading the recipe version's `embedding.model` from the
  catalog DB. This is now documented as a "Watch out for" in
  NEXT_SESSION-refine-tool.md.
- Decided hybrid vector+keyword is necessary rather than vector-only.
  Vector alone misses 47% of keyword matches (7/15). This adds one SQL
  query per refine call but both hit the same pgvector index.

## Backlog delta

Filed: none. Closed: none. Deferred: none.
Memory: none new (existing project memories adequate).

## Drift & forward-collisions

- Backward — none. No open issues affected by research-only output.
- Forward — #28 entity-arc retrieval: research validates feasibility and
  produces implementation design. Implementation is the next session.

## For the reviewer

- Sanity-check: The hybrid approach adds a keyword search leg that
  returns chunks with low vector scores (0.15-0.27). The score floor
  (0.30) filters most noise, but the threshold is empirically chosen
  from one document. Worth validating across other CPGs.
- Thin verification: doc_section fragmentation was checked on only the
  PTSD CPG. Other CPGs may have different section structures. The
  finding (use chunk_index not doc_section for ordering) should hold
  regardless since chunk_index is always sequential.
- Wants guidance: none.

## Risks / watch-fors

- Embedding model mismatch is a recurring trap. Any new adapter method
  or research script that embeds queries must use `_embedding_model_name()`
  and `_query_prefix()` from the recipe version. Hardcoding model names
  produces silently wrong results (near-zero scores, not errors).
- Score floor of 0.30 was chosen from SSRI/PTSD data. May need
  per-source or per-model calibration. See #32 (score calibration issue).
