# Next Session — query-rewriter

## Next: Build the rewriter service and seed VA CPG metadata

Phases 1 and 2 of the epic are parallel-ok and together form the foundation: the rewriter service (code + prompt template + LLM client) and the VA CPG metadata (vocabulary mappings + sample queries) that makes it effective. Both must land before Phase 3 can wire them into `retrieve`. README quick-start (#9) folds in at the end if there's time.

1. **Core rewriter service + shared template**
   Create `src/retrieval_hub/rewriter/` with the service class, YAML prompt template, and LLM client. The LLM client targets gpt-oss-120b via httpx (OpenAI-compatible chat completions). The rewrite output schema (`RewrittenQuery` with text, intent, rationale, confidence) and lineage fields are defined as Pydantic models. Validate with a standalone test script against the live LLM.

   Key files to create:
   - `src/retrieval_hub/rewriter/__init__.py`
   - `src/retrieval_hub/rewriter/service.py` -- `RewriterService` class
   - `src/retrieval_hub/rewriter/llm.py` -- async LLM client
   - `src/retrieval_hub/rewriter/schemas.py` -- rewrite output models (or extend `src/retrieval_hub/schemas/rewriter.py` which already has `RewriterMetadata`)
   - `prompts/rewriter-shared-core.yaml` -- the shared template
   - `scripts/test_rewriter.py` -- standalone smoke test
   - Unit tests in `tests/test_rewriter/`

2. **VA CPG rewriter metadata**
   Populate `rewriter_metadata` on the VA CPG source with 30-50 clinical vocabulary mappings, domain notes, and 5-10 sample queries. The `RewriterMetadata` Pydantic schema already exists at `src/retrieval_hub/schemas/rewriter.py` with all the right fields. Write a script to update the source record in the catalog DB.

3. **README quick-start (#9)** (if time permits)
   Add a "Quick start (full demo)" section to the root README. Cover podman containers, migrations, ingestion, query demo, MCP server.

**Sequencing.** Items 1 and 2 are independent -- start with item 1 (the service is the harder piece), then item 2 (metadata is data entry once the schema is validated). Item 3 is standalone filler.

**Constraints for the session:**
- The existing `RewriterMetadata` schema and `Source.rewriter_metadata` column are already in place -- don't recreate them
- The rewrite output schema (what the LLM returns) is separate from the metadata schema (what the source owner declares) -- keep them distinct
- gpt-oss-120b is a reasoning model; the LLM client should read from `content` (the answer) not `reasoning` (the chain-of-thought)
- The VA CPG source may or may not be ingested in the local DB (databases are ephemeral podman volumes) -- re-ingest if needed, or just UPDATE the metadata on the existing source record

**Session start protocol:**
- Premise checks (before item 1, ~5 min):
  - Verify local databases are up (`pg_isready -h localhost -p 5433` and `-p 5434`)
  - Verify gpt-oss-120b endpoint is reachable: `curl -s https://gpt-oss-120b-direct-gpt-oss-120b-model.apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1/models | head -5`
  - Check if `va-cpg-clinical-guidelines` source exists in the catalog (needed for item 2)
  - Verify the existing `RewriterMetadata` schema imports cleanly: `from retrieval_hub.schemas.rewriter import RewriterMetadata`
- Rules with history:
  - The MCP server uses FastMCP `Depends()` for session injection -- the B008 lint warnings are intentional
  - Embedding models are shared cluster resources -- don't change the jina-code-embeddings setup
- Stop-and-ask before: modifying the deployed MCP server on gpt-oss-120b; any changes to the VA CPG pgvector table
- Close ritual: session summary to `session-summaries/`; update NEXT_SESSION-query-rewriter.md with what landed

**LLM endpoint details (verified 2026-08-18):**
- URL: `https://gpt-oss-120b-direct-gpt-oss-120b-model.apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1/chat/completions`
- Model name: `/mnt/models`
- Auth: none required
- Context window: 131,072 tokens
- Response shape: OpenAI-compatible, reasoning model (`content` has the answer, `reasoning` has chain-of-thought)
- Smoke-tested: "high blood sugar after a meal" -> "Postprandial hyperglycemia."

## Remaining epic phases

The query rewriter is the differentiating capability: source-owner-declared metadata (vocabulary mappings, domain notes, sample queries) injected into a shared prompt template, producing reformulated queries that outperform raw user queries on retrieval eval. The rewriter is transparent to agents -- folded into `retrieve` as an automatic step, with `no_rewrite` as an opt-out flag and `rewritten_queries` returned in the response for observability.

End-state: on the VA CPG source, queries with rewriting enabled measurably outperform queries without rewriting on a Ragas eval, using declarative metadata and gpt-oss-120b as the rewriting LLM. The rewriter is callable through the existing `retrieve` MCP tool.

### Phase 1: Core rewriter service + shared template

Build the rewriter as a core library service at `src/retrieval_hub/rewriter/`. The shared prompt template lives in `prompts/rewriter-shared-core.yaml`. LLM calls go to gpt-oss-120b on the cluster via httpx (OpenAI-compatible API). Structured output validation on the response.

**Work:**
1. Create `src/retrieval_hub/rewriter/service.py` with `RewriterService` class -- takes an LLM client, loads source metadata, renders the shared template, calls the LLM, validates structured output
2. Create the shared prompt template in `prompts/rewriter-shared-core.yaml` -- slots for vocabulary_mappings, domain_notes, sample_queries, raw_query
3. Create `src/retrieval_hub/rewriter/llm.py` with an async LLM client targeting the gpt-oss-120b endpoint (OpenAI-compatible chat completions API via httpx)
4. Define the rewrite output schema: list of `(text, intent, rationale, confidence)` plus lineage fields (template_version, metadata_version, llm, request_id)
5. Write unit tests with mocked LLM responses
6. Create a standalone test script (`scripts/test_rewriter.py`) that calls the service directly against the live LLM with a hardcoded VA CPG-style metadata payload

**Definition of done:** `test_rewriter.py` produces structured rewrites from a raw query like "high blood sugar after a meal" using gpt-oss-120b, with vocabulary-mapped terms appearing in the output. Unit tests pass.

**Dependencies:** None. Needs network access to gpt-oss-120b cluster endpoint.

**Parallel-ok:** Yes -- independent of Phase 2.

### Phase 2: VA CPG rewriter metadata

Populate `rewriter_metadata` on the VA CPG source with clinical vocabulary mappings, domain notes, and sample queries. This is the proving-ground data that makes the shared template effective. Re-ingest or update the source record to carry the metadata.

**Work:**
1. Build a vocabulary mapping set for the VA CPG corpus: 30-50 lay-term-to-clinical-term pairs (e.g., "high blood sugar" -> "hyperglycemia", "blood pressure medicine" -> "antihypertensive therapy")
2. Write domain_notes for the VA CPG source describing content type, preferred query phrasing, guideline title conventions
3. Create 5-10 sample_queries with good_rewrites as few-shot examples
4. Write a script or extend `ingest_va_cpg.py` to update the source's `rewriter_metadata` column
5. Verify the metadata loads correctly through the catalog API

**Definition of done:** `SELECT rewriter_metadata FROM source WHERE slug='va-cpg-clinical-guidelines'` returns a populated JSON with vocabulary_mappings (30+ entries), domain_notes, and sample_queries (5+ entries). The metadata renders cleanly into the shared template from Phase 1.

**Dependencies:** None. Can run in parallel with Phase 1 (metadata authoring doesn't need the rewriter code).

**Parallel-ok:** Yes -- independent of Phase 1.

### Phase 3: Wire rewriter into retrieve MCP tool

Fold the rewriter into the `retrieve` tool as a transparent step. When a source has `rewriter_metadata` with `enabled: true`, the tool rewrites the query before vector search and returns the rewritten queries in the response. Add `no_rewrite: bool = False` parameter. Add `rewritten_queries` to `RetrievalResponse`.

**Work:**
1. Add `no_rewrite: bool = False` parameter to the `retrieve` tool
2. Add `rewritten_queries` field to `RetrievalResponse` schema (list of rewrite objects, or None when rewriting was skipped)
3. In the retrieve flow: check source metadata, call RewriterService if enabled and not no_rewrite, union retrieval hits across rewrites, deduplicate
4. Handle the fallback: if the LLM call fails or times out, fall back to the raw query (rewriting failure should not block retrieval)
5. Update MCP server tests for both paths (rewrite-enabled, no_rewrite, source without metadata)
6. Test end-to-end against VA CPG source with live LLM

**Definition of done:** `retrieve(query="high blood sugar after a meal", source="va-cpg-clinical-guidelines")` returns hits with `rewritten_queries` populated, and the hits are different (better) than `retrieve(..., no_rewrite=True)`. Fallback works when LLM is unreachable.

**Dependencies:** Gated on Phase 1 (rewriter service) and Phase 2 (VA CPG metadata).

**Parallel-ok:** No.

### Phase 4: Eval -- rewrite lift measurement

Run a Ragas eval comparing retrieval with and without rewriting on the VA CPG source. Measure context_precision and answer_relevancy delta. Record results on the source's data card. This is the "is the differentiator real?" gate.

**Work:**
1. Build a test query set: 20-30 queries spanning lay-language clinical questions, guideline-reference queries, and treatment-recommendation queries
2. Run retrieval with `no_rewrite=True` and collect hits for each query
3. Run retrieval with rewriting enabled and collect hits for each query
4. Score both sets with Ragas (context_precision, answer_relevancy, or similar metrics)
5. Record the eval results: per-query scores, aggregate delta, which vocabulary mappings fired
6. Update the VA CPG source's data card with eval results and the tools/methodology used
7. Write a brief eval summary to `session-summaries/`

**Definition of done:** A measurable, positive delta on context_precision or answer_relevancy between rewrite-enabled and raw queries on at least 60% of test queries. Results recorded on the data card with methodology notes (Ragas version, LLM used, date). If the delta isn't there, document why and what would need to change.

**Dependencies:** Gated on Phase 3 (rewriter wired into retrieve).

**Parallel-ok:** No.

### Phase 5: README quick-start (#9)

Update the root README with a local demo flow: start databases, run migrations, ingest a source, query it. Close #9.

**Work:**
1. Add a "Quick start (full demo)" section to README.md with step-by-step commands
2. Cover: podman containers, migrations, VA CPG or code source ingestion, query demo script, MCP server startup
3. Verify the flow works from a clean checkout

**Definition of done:** A developer can clone the repo, follow the README, and have a working retrieval demo within 10 minutes (excluding model download time). #9 closed.

**Dependencies:** None. Can be done in any session that has spare capacity.

**Parallel-ok:** Yes -- independent of all other phases.

## What landed last session (2026-08-18)

Code source epic completed and archived. Live GitHub file fetch on `retrieve`, min_tokens chunker denoising, github_repo auto-detection in recipes, code query demo script. 5 stale issues closed (#8, #11, #12, #13, #14). Retro written to `retrospectives/2026-08-18_code-source-epic/`.

**Commits:** `9b548c6`..`bfd17a1` (code source epic, 2 sessions)

## Watch out for

- gpt-oss-120b is on a sandbox cluster -- endpoint URL may change if the cluster is reprovisioned
- The VA CPG source may not be ingested in local databases (podman volumes are ephemeral) -- check during premise checks
- The `RewriterMetadata` Pydantic schema already exists with `extra="forbid"` -- any new fields need to be added there, not worked around

## If blocked

- If gpt-oss-120b is unreachable, implement the rewriter service with a mock LLM client that returns canned responses. The service architecture doesn't change; only the client is swapped. Wire the real endpoint when it's back.
- If the VA CPG source is not available locally, the rewriter service can still be built and tested with hardcoded metadata payloads (item 1 doesn't depend on item 2)

---

## What this covers (and what it doesn't)

**In scope:**
- #15 -- query rewriter end-to-end with real eval delta on VA source
- #9 -- root README quick-start for local demo flow
- Core rewriter service with shared template and per-source metadata
- LLM integration with gpt-oss-120b (OpenAI-compatible API)
- Transparent rewriting inside the retrieve tool (no separate rewrite tool)
- Ragas eval measuring rewrite lift
- Data card updates with eval methodology

**Out of scope (other epics own):**
- Override prompt path (`prompt_override_id`) -- design doc covers it, but not needed for MVP
- Cached rewrites -- Round 2 per design doc
- MLflow prompt registry integration -- deferred until MLflow is wired (#21)
- Admin UI rewriter metadata editor -- deferred until UI SPA (#19)
- Cross-source rewriting behavior -- deferred until cross-source search is designed
- CLI rewriter test command -- deferred until CLI peer component (#18)
