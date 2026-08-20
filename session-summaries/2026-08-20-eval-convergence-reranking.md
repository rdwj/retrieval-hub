# Session Summary -- 2026-08-20 -- eval-convergence -- Answer-quality eval pipeline and reranking comparison

**Plan:** NEXT_SESSION-eval-convergence.md (Phase 1)   **Commits:** `0aea548`..`3bcecf8` (main)
**Deployed:** none   **Model:** Claude Opus 4.6 (1M context)

## Plan vs. actual

Planned: build end-to-end answer-quality eval pipeline with Ragas. Shipped:
the pipeline plus a five-strategy reranking comparison, yielding the
session's headline result (+12.1% context_precision from cross-encoder
reranking). Scope expanded from "build the pipeline" to "build and use it
to answer a retrieval architecture question." Also filed 4 new issues,
updated README positioning, and wrote the eval convergence plan with arXiv
outline.

## Shipped

- `0aea548` -- answer-quality eval pipeline (`scripts/eval_answer_quality.py`) with three-stage caching, Ragas context_precision + answer_relevancy, gpt-oss-120b judge with reasoning off
- `8eeeacd` (prior session, ran first full eval this session) -- first Ragas run: rewriting improves answer_relevancy +5.4% but drops context_precision -6.8%
- `0877b37` -- reranking strategy comparison (`scripts/eval_rerank_strategies.py`): five strategies (cosine_dedup, RRF, cross-encoder, cosine-on-original, LLM rerank), per-condition checkpointing, parallel workers, subset + full runs
- `23331e5` -- eval register updated with Runs 3-5
- `a0d3bc8` -- README positioning: one MCP server for all enterprise retrieval content
- `3bcecf8` -- revised eval plan with leaderboard analysis, arXiv outline, JMIR clinical benchmark reference

## Verification and confidence

- Five eval runs executed (1 answer-quality baseline, 1 five-strategy subset, 1 three-strategy full, 1 two-strategy full, multiple smoke tests). All Ragas metrics validated on gpt-oss-120b with reasoning off.
- Cross-encoder result (+12.1% context_precision) confirmed on both 10-query subset and full 30-query run. Consistent across registers.
- Confidence: **high** on the cross-encoder finding. **Medium** on the answer_relevancy trade-off (-7.9%) -- this may be addressable through register-aware rewriting or hybrid scoring (untested).

## Judgment calls and deviations

- Dropped faithfulness from early runs due to Ragas max_tokens=1024 default causing NaN. Fixed by bumping to 8192. Faithfulness works in later runs but has NaN on some lay-register queries.
- Used gpt-oss-120b for both rewriting (reasoning on) and scoring (reasoning off). Not ideal separation but not circular: answer generation is by gpt-oss:20b (different model).
- granite3.3:8b (local Ollama) was too slow for Ragas scoring (~23s/item). Switched to gpt-oss-120b cluster endpoint which is faster despite network round-trip.
- muse-glimmer:30b-mlx has a chat template issue that makes it incompatible with instructor/Ragas (outputs role tokens in content).

## Backlog delta

Filed: #28 (entity-arc retrieval), #29 (elicitation in retrieve/refine), #30 (MCP auth), #31 (MCP-level eval path).
Parallel session filed: #32-35 (retrieve tool improvements).

## Drift and forward-collisions

- Backward: #29 updated to reflect that elicitation is a feature of retrieve/refine, not a separate tool.
- Forward: the reranking comparison (cross-encoder finding) directly informs eval-convergence Phase 3 (retrieval config sweep). The cross-encoder should be the default reranking strategy going forward.

## For the reviewer

- Sanity-check: the answer_relevancy drop with cross-encoder (-7.9%). Is this a retrieval problem or an answer-model problem? The chunks are more precisely relevant (higher context_precision) but the 20b answer model produces slightly less relevant answers from them. Worth testing with a larger answer model.
- Thin verification: faithfulness NaN on lay-register queries in Run 5. Ragas may struggle with shorter answers. Not investigated.
- Wants guidance: none.

## Risks / watch-fors

- gpt-oss-120b sandbox cluster is the single point of failure for both rewriting and eval scoring. If reprovisioned, all eval scripts need URL updates.
- The 30-query eval set was authored alongside the vocabulary mappings. Cross-validation (E10 in eval plan) is needed before publishing to rule out data leakage.
