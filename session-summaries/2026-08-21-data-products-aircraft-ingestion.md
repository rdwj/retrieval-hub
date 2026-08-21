# Session Summary — 2026-08-21 · data-products · Aircraft maintenance ingestion with remote embedding

**Plan:** NEXT_SESSION-data-products.md (Phase 2, reordered)   **Commits:** none yet (prepare-and-ask)
**Deployed:** vLLM snowflake-arctic-embed on agent-security-dev-3   **Model:** Claude Opus 4.6

## Plan vs. actual

Planned: ingest aircraft maintenance dataset as Phase 2 (reordered from Phase 4).
Shipped: deployed snowflake-arctic-embed-m-v1.5 on vLLM, added remote embedding backend,
ingested 263 docs / 2,330 chunks, built 25-question eval dataset, updated epic plan.
Slipped: none. Scope stayed tight.

## Shipped

- `embed.py` — remote embedding backend (`endpoint` param) for both `ChunkEmbedder`
  and `QueryEmbedder`, with batching, retry, `truncate_prompt_tokens` for BERT
  tokenizer mismatch. 15 new tests, 260 total pass.
- `document.py` — `_embedding_endpoint()` method + updated all 3 `QueryEmbedder`
  call sites to pass endpoint from recipe.
- `vllm-snowflake.yaml` — vLLM v0.8.5 Deployment + Service + Route serving
  snowflake-arctic-embed-m-v1.5 on GPU. Iterated through 5 deployment fixes:
  `--task embed` flag, `vllm serve` subcommand, GPU toleration, non-root cache
  path, `enableServiceLinks: false` for env var collision.
- `ingest_aircraft_maintenance.py` — 7-stage ingestion script. 263 docs (170
  Cherokee, 93 Saratoga), 2,330 chunks, 1.14M tokens, 132.6s wall time.
  Source registered as `aircraft-maintenance` (TECHNICAL_DOCUMENT).
- `eval/aircraft_maintenance/qa_dataset.json` — 25 questions across 6 types
  including 5 cross-dataset (aircraft + clinical).
- `CLAUDE.md` — 2 new lessons learned (tokenizer mismatch, vLLM deployment).
- `NEXT_SESSION-data-products.md` — reordered phases, recorded what landed.

## Verification & confidence

- Remote embedding: 260 unit tests pass (mock-based), plus live verification
  against deployed vLLM endpoint (768-dim vectors returned).
- Ingestion: full pipeline ran end-to-end, 263 docs ingested, pgvector table
  populated with 2,330 rows.
- Retrieval: tested via DocumentAdapter — "carburetor heat cable replacement"
  returns SB_0312 (Cherokee) as top hit at 0.564 similarity. Cross-reference
  chain confirmed (SB_0298 as second hit).
- Confidence: **high** — tested live data, real GPU deployment, real retrieval.

## Judgment calls & deviations

- Reordered epic phases: aircraft ingestion moved from Phase 4 to Phase 2.
  Rationale: user wanted to work on aircraft data next; cross-dataset reasoning
  benefits from having 3 sources instead of 2.
- Used vLLM v0.8.5 instead of latest (v0.27.1 doesn't support `--task embed`
  for BERT models).
- Added `truncate_prompt_tokens: 512` to all remote embedding requests rather
  than reducing chunk size. cl100k_base 512 tokens can become 650+ BERT tokens;
  truncation loses a small tail on the longest chunks but preserves standard
  chunk sizing for all others.
- GPU on agent-security-dev-3 (scaled machineset 2→3) because gpt-oss-120b
  was fully allocated (4/4 GPUs).

## Backlog delta

Filed: none. Closed: none. Memory: `design_per_source_model_selection` added
by system. Deferred: GPU machineset scale-down after aircraft work concludes
(the L40S node will continue running).

## Drift & forward-collisions

- Backward — none. No open issues touched by this session's changes.
- Forward — Phase 3 (chunking sweeps) now has two corpora to sweep against
  instead of one. Phase 4 (cross-dataset reasoning) gains a third source and
  a cross-domain dimension (clinical + aviation).

## For the reviewer

- Sanity-check: the `truncate_prompt_tokens` approach — is token-tail truncation
  acceptable for retrieval quality, or should we pre-truncate client-side with
  the BERT tokenizer? The loss is small (only affects chunks where BERT produces
  >512 tokens from 512 cl100k_base tokens), but it's lossy.
- Thin verification: eval QA dataset questions were written by an agent reading
  the documents, not by a domain expert. Cross-dataset questions are plausible
  but synthetic.
- Wants guidance: none.

## Risks / watch-fors

- The L40S GPU node on agent-security-dev-3 is still running (cost). Scale the
  machineset back to 2 when the aircraft embedding endpoint is no longer needed.
- The vLLM endpoint URL is baked into the recipe — if the cluster or route
  changes, the MCP server won't be able to embed queries for this source until
  the recipe is updated.
