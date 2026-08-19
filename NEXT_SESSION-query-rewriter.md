# Next Session — query-rewriter

## Next: Ragas eval measuring rewrite lift on VA CPG

The "is the differentiator real?" gate. Run retrieval with and without query rewriting on the VA CPG source, score both with Ragas metrics, and record whether rewriting produces a measurable improvement. This is the final phase of the query-rewriter epic. If the delta is there, we have a validated differentiator; if not, we document why and what would need to change.

1. **Environment setup**
   Install Ragas (`pip install ragas`) and verify the VA CPG corpus is ingested into local pgvector. The corpus lives at `/Users/wjackson/Developer/retrieval-hub-data-sources/va-cpg/extracted/` (5 categories). If not ingested, run `python scripts/ingest_va_cpg.py` and then `python scripts/seed_va_cpg_rewriter_metadata.py` to populate the rewriter metadata.

2. **Build the eval query set from existing Q/A data**
   The project already has 50 Q/A pairs at `eval/autorag/qa_dataset_draft.json` with ground-truth answers, source document paths, and `language_register` labels (clinical vs. lay). Filter to the lay-register questions (the ones where vocabulary translation should produce the biggest lift) plus a sampling of clinical-register ones as controls. Target 25-30 queries.

3. **Write the eval script** (`scripts/eval_rewrite_lift.py`)
   For each query in the set:
   - Run `retrieval_hub.retrieval.api.query()` directly (raw query, no rewriting) and collect top-5 hits
   - Run `RewriterService.rewrite()` to get rewritten queries, then run `query()` for each rewrite, deduplicate, collect top-5 hits
   - Record both hit sets with their scores and source doc paths
   
   Then score with Ragas:
   - `context_precision` — do the retrieved chunks come from the correct source document? (ground truth available in the Q/A dataset's `source_doc` field)
   - `answer_relevancy` — are the retrieved chunks relevant to answering the question? (uses the ground-truth answer for comparison)
   
   Output: per-query CSV with raw vs. rewritten scores, aggregate summary, and delta stats.

4. **Run the eval and analyze results**
   Execute the script against the live gpt-oss-120b endpoint. Examine:
   - Overall delta on context_precision and answer_relevancy
   - Per-query breakdown: which queries improved, which didn't
   - Which vocabulary mappings fired (from the rewrite rationale field)
   - Lay vs. clinical register performance difference

5. **Record results**
   - Save raw results to `eval/rewrite_lift/` (CSV + summary)
   - Update the VA CPG source data card with eval methodology and findings
   - Write a session summary to `session-summaries/`

**Sequencing.** Items 1-2 are fast setup (~10 min). Item 3 is the main implementation work. Items 4-5 are execution and recording.

**Constraints for the session:**
- The existing `eval/autorag/eval_retrieval.py` uses PubMedBERT for embeddings and cosine search directly. The rewrite eval should use the actual retrieval pipeline (`retrieval_hub.retrieval.api.query()`) against pgvector, not a custom cosine-search implementation. This measures the real production path.
- Ragas context_precision and answer_relevancy require an LLM for scoring. Use gpt-oss-120b for both rewriting AND eval scoring (single LLM, simpler setup). If Ragas needs a different LLM interface, wrap with LangChain's ChatOpenAI pointing at gpt-oss-120b.
- The Q/A dataset has `source_doc` paths relative to the corpus root (e.g., `chronic-disease/hypertension/clinician-summary.md`). These can serve as ground-truth for context_precision: does the retrieved chunk come from the correct document?

**Session start protocol:**
- Premise checks (before item 1, ~5 min):
  - Verify local databases are up (`pg_isready -h localhost -p 5433` and `-p 5434`)
  - Verify gpt-oss-120b endpoint is reachable: `curl -s https://gpt-oss-120b-direct-gpt-oss-120b-model.apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1/models | head -5`
  - Check if VA CPG source exists AND is queryable (has an active physical index): `python -c "from retrieval_hub.retrieval.api import query; query('va-cpg-clinical-guidelines', 'test', session=..., top_k=1)"` -- if this fails, re-ingest
  - Verify the Q/A dataset loads: `python -c "import json; d=json.load(open('eval/autorag/qa_dataset_draft.json')); print(f'{len(d[\"questions\"])} questions, {sum(1 for q in d[\"questions\"] if q[\"language_register\"]==\"lay\")} lay-register')"`
  - Check Ragas version: `pip show ragas` -- install if missing
- Rules with history:
  - The MCP server uses FastMCP `Depends()` for session injection -- the B008 lint warnings are intentional
  - Embedding models are shared cluster resources -- don't change the jina-code-embeddings setup
  - The rewriter reads `content` from gpt-oss-120b responses, not `reasoning` (it's a reasoning model)
- Stop-and-ask before: modifying the deployed MCP server; any changes to the VA CPG pgvector table schema; dropping/recreating the physical index
- Close ritual: session summary to `session-summaries/`; update NEXT_SESSION-query-rewriter.md with what landed; if the delta is positive, close #15 epic as validated

**LLM endpoint details (verified 2026-08-18):**
- URL: `https://gpt-oss-120b-direct-gpt-oss-120b-model.apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1/chat/completions`
- Model name: `/mnt/models`
- Auth: none required
- Context window: 131,072 tokens
- Response shape: OpenAI-compatible, reasoning model (`content` has the answer, `reasoning` has chain-of-thought)

## Remaining epic phases

The query rewriter is the differentiating capability: source-owner-declared metadata (vocabulary mappings, domain notes, sample queries) injected into a shared prompt template, producing reformulated queries that outperform raw user queries on retrieval eval. The rewriter is transparent to agents -- folded into `retrieve` as an automatic step, with `no_rewrite` as an opt-out flag and `rewritten_queries` returned in the response for observability.

End-state: on the VA CPG source, queries with rewriting enabled measurably outperform queries without rewriting on a Ragas eval, using declarative metadata and gpt-oss-120b as the rewriting LLM. The rewriter is callable through the existing `retrieve` MCP tool.

### Phase 4: Eval -- rewrite lift measurement (THIS SESSION)

Run a Ragas eval comparing retrieval with and without rewriting on the VA CPG source. Measure context_precision and answer_relevancy delta. Record results on the source's data card. This is the "is the differentiator real?" gate.

**Definition of done:** A measurable, positive delta on context_precision or answer_relevancy between rewrite-enabled and raw queries on at least 60% of test queries. Results recorded on the data card with methodology notes (Ragas version, LLM used, date). If the delta isn't there, document why and what would need to change.

**Dependencies:** Phases 1-3 complete (rewriter service built, VA CPG metadata seeded, retrieve tool wired).

### Phases 1-3, 5: COMPLETE

- Phase 1 (core rewriter service): `625a750`
- Phase 2 (VA CPG metadata): `625a750`
- Phase 3 (wire into retrieve): `625a750`
- Phase 5 (README quick-start): `6ec9bfe`

## What landed last session (2026-08-18)

Phases 1, 2, 3, and 5 of the query-rewriter epic in a single session. The rewriter is built, tested, integrated, documented, and smoke-tested against the live LLM.

**Commits:** `625a750`, `6ec9bfe`

- Core rewriter module: `src/retrieval_hub/rewriter/` with async LLM client, YAML prompt template, structured output validation. 64 unit tests.
- VA CPG metadata seeded: 49 vocabulary mappings across 7 clinical domains, 8 sample query examples, domain notes.
- Retrieve tool integration: `no_rewrite` parameter, transparent rewriting with fallback, hit deduplication by text content, `rewritten_queries` in response. 5 new MCP server tests.
- README quick-start: full demo flow covering databases, migrations, ingestion, query demo, rewriter smoke test, MCP server.
- Live smoke test confirmed: "high blood sugar after a meal" rewrites to "postprandial hyperglycemia management guidelines" and 4 other clinical variants via gpt-oss-120b.

**Closed:** #15 (partial -- rewriter built and wired, eval pending), #9 (README quick-start)

## Watch out for

- gpt-oss-120b is on a sandbox cluster -- endpoint URL may change if the cluster is reprovisioned. If unreachable, the eval can't run. No good fallback for the eval (it needs a real LLM for both rewriting and Ragas scoring).
- The VA CPG source may not be ingested in local databases (podman volumes are ephemeral) -- re-ingest with `scripts/ingest_va_cpg.py` if the premise check fails.
- Ragas API has changed significantly across versions. Search PyPI for the latest version and check the current API before writing eval code -- don't rely on training-data knowledge of the Ragas interface.
- The existing `eval/autorag/` directory uses AutoRAG and PubMedBERT. The rewrite eval should be a separate directory (`eval/rewrite_lift/`) to avoid conflating the two eval approaches.

## If blocked

- If gpt-oss-120b is unreachable, the eval can't run (both rewriting and Ragas scoring need an LLM). Document the blocker and move on to non-LLM work: CLI peer component (#18), or improving the existing ingestion pipeline.
- If Ragas has breaking API changes, fall back to a simpler eval: hit_rate and MRR against the ground-truth source documents (similar to what `eval/autorag/eval_retrieval.py` already does). This doesn't measure answer_relevancy but still proves whether rewriting surfaces the right documents.
