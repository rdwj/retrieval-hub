# Session Summary: Self-Serve Onboarding Pipeline Proving Run

**Date:** 2026-08-27 (evening session)
**Epic:** Self-Serve Onboarding

## Goal

Run the self-serve onboarding pipeline (`onboard_source.py`) end-to-end
against the aircraft maintenance dataset to prove it works. Fix whatever
breaks.

## What landed

### Bug fixes (committed)

Five bugs found and fixed across 4 files:

1. **BioC JSON misdetection** (`pipeline.py`): `_load_bioc_documents()`
   picked up any `.json` file (like `manifest.json`) and routed all
   documents through the BioC chunker, skipping regular markdown loading.
   Added `_is_bioc_format()` validation.

2. **Bare module imports** (`onboard_source.py`): Sibling script imports
   (`generate_qa_pairs`, `eval_answer_quality`) failed with
   `ModuleNotFoundError`. Added `sys.path.insert` for the scripts
   directory.

3. **DB URL format** (`onboard_source.py`): Default URLs used
   `postgresql://` instead of `postgresql+psycopg://`, causing SQLAlchemy
   to use the wrong adapter.

4. **Missing adapter** (`api.py`): `technical_document` family was not in
   the retrieval adapter factory, causing eval to raise
   `UnsupportedFamilyError`.

5. **Unhealthy model fallback** (`api.py`): When the model health probe
   marked an embedding model unhealthy, retrieval raised
   `ModelUnavailableError` instead of using the registered endpoint. Now
   falls back to the endpoint URL with a warning.

6. **LLM None content** (`llm.py`): vLLM can return `{"content": null}`
   in chat completions. `LlmClient.chat` crashed with `TypeError` on
   `len(None)`.

### Pipeline stages proven

- **Ingestion**: All 3 chunk configs (256/0, 512/0, 512/64) processed
  173 markdown files from `piper-cherokee/extracted/`, producing 3137,
  1612, and 1798 chunks respectively. Used local `sentence-transformers`
  for embedding (the remote nomic TEI pod OOMed under batch load).
  Tables written to cluster pgvector: `idx_aircraft_sb_test_256_0`,
  `idx_aircraft_sb_test_512_0`, `idx_aircraft_sb_test_512_64`.

- **QA generation**: 156 questions generated and validated from 173
  source documents (17 skipped validation). Cached at
  `eval/aircraft-sb-test/qa_generated.json`.

- **Retrieval**: Verified working both directly (`retrieval_hub.retrieval.api.query()`)
  and through the eval pipeline's stage 1 (156/156 queries completed).

- **Eval answer generation**: Reached 30/156 before being paused due to
  LLM contention with another eval run. `retrieval.json` is cached, so
  the eval can be resumed cleanly.

## What didn't land

- **Full eval completion**: Paused at answer generation (30/156) due to
  LLM endpoint contention. Resume when the other eval finishes.

- **Winner selection and promotion**: Depends on eval completion. The
  code path is simple (sort by relevancy, drop losers) but hasn't been
  exercised yet.

- **MCP server verification**: The deployed MCP server doesn't have the
  `technical_document` adapter fix or the unhealthy-model fallback. Needs
  redeployment.

## Observations for next session

1. **QA generation overshoots**: `--num-qa-pairs 20` generated 156
   questions (1 per document) instead of 20. The
   `_build_generation_targets()` function distributes pairs across
   documents but generates at least 1 per document. Not a blocker but
   should be investigated.

2. **Nomic TEI pod OOM**: The `retrieval-hub-embedding-nomic` pod (8Gi
   memory limit) OOMed under batch embedding load (batch_size=32).
   Consider increasing the memory limit or reducing batch size for
   ingestion.

3. **Model health probe**: The CronJob health probe runs every 5 minutes
   and overwrites manual status fixes. The unhealthy-model fallback in
   `api.py` is the right long-term fix, but needs to be deployed to the
   MCP server.

4. **Port-forward reliability**: The DB port-forward dropped during a
   large vector write (3137 rows with 768-dim vectors). The pipeline
   should add retry logic for DB writes, or ingestion caching so
   re-runs skip completed configs.

## Commits

- `4fd6a43` fix: Resolve four bugs blocking onboarding pipeline end-to-end run
- `f734199` fix: Handle None content in LLM chat responses
