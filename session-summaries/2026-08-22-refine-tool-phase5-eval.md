# Session: Refine-tool Phase 5 — A/B eval

**Date:** 2026-08-22
**Epic:** refine-tool
**Phase:** 5 (A/B eval — does refine improve answer quality?)

## Outcome

Phase 5 complete. **Adjacent refine degrades automated eval metrics.**
The refine tool remains valuable for human-in-the-loop exploration but
does not improve RAG answer quality in the automated pipeline.

## What landed

- `d6f068e` — eval pipeline extended with optional `--refine-strategy`
  and `--refine-window` flags. New `_stage_refine()` between retrieve
  and generate. Includes `chunk_index`/`chunk_id` in serialized hits,
  refine params in config fingerprint, refined.json caching.

- Adjacent refine eval completed (`eval/rewrite_lift/runs/refine-adjacent/`).
  Section eval skipped — adjacent already showed clear degradation,
  section returns even more dilutive context.

## Results: adjacent refine vs baseline (no refine)

| Metric             | Baseline | Adjacent refine | Delta    |
|--------------------|----------|-----------------|----------|
| context_precision  | 0.815    | 0.386           | **-0.429** |
| answer_relevancy   | 0.735    | 0.678           | -0.057   |
| faithfulness       | 0.854    | 0.837           | -0.017   |

## Analysis

Adjacent refine (window=2) expands each of the 5 top-k hits with 4
surrounding chunks, inflating the context from 5 focused chunks to ~25.
Most of the added chunks are positionally adjacent but not semantically
relevant to the question. Ragas context_precision penalizes irrelevant
context heavily, causing the metric to roughly halve.

Answer_relevancy and faithfulness showed smaller declines, suggesting
the LLM can still find relevant information in the expanded context
but the noise reduces overall quality.

Section refine would be worse: our smoke test showed 43 chunks per
hit for the section strategy vs 5 for adjacent.

## Implications

- The refine tool's value is in **exploration**, not automated RAG.
  When a human or agent reads a retrieve hit and wants to understand
  the surrounding context, refine provides that. But stuffing all the
  expanded context into a generation prompt degrades quality.
- A future improvement could be selective refine — only expand the
  top-1 hit, or use reranking after refine to prune back to top-k.
  But that's a different experiment.

## Epic status

Phase 5 closes the refine-tool epic's gate question. Remaining work
is #34 (multi-source retrieve), which is independent of refine quality.
