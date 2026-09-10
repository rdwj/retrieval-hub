# Next Session -- Ontology v2

## Epic: Ontology self-improvement and concept-first retrieval

Build on the ontology registry (shipped in the ontology v1 epic) with
eval-driven self-improvement, query success monitoring, concept-first
retrieval, an onboarding pipeline with HITL, and authority score
improvements.

Issues: #61 (closed), #62, #63, #64, #68 (closed)

## Next: Concept-first retrieval (#62)

Add `retrieve(concept="Condition")` — query by canonical concept instead of
naming a specific source. The system fans out to all sources mapped to that
concept, queries each, and merges results weighted by authority scores.

### Prerequisites (all met)

- Ontology registry with hierarchy: shipped
- Authority scoring with meaningful differentiation: shipped (#68), range 0.98
- `expand_doc_section_via_registry` walks the concept tree: shipped
- Benchmark harness exists: `scripts/eval_ontology_benchmark.py`

### Implementation steps

1. **Add `concept_query()` to `retrieval/api.py`**
   New function: `concept_query(concept: str, query_text: str, *, session,
   top_k=10, ...)`. Resolves the concept to mapped sources, fans out
   `query()` calls, merges and re-ranks results weighted by authority score.
   - Look up all `OntologyMapping` rows for the canonical concept (and
     children via `_expand_concepts_via_hierarchy`)
   - Group mappings by `source_slug`
   - Call `query()` per source with the mapping's `local_name` as
     `doc_section`
   - Weight each hit's score by its source's authority score
   - Merge, deduplicate by chunk_id, sort by weighted score, return top_k

2. **Wire into the MCP server**
   The MCP `retrieve` tool (`retrieval-hub-mcp/src/retrieval_hub_mcp/server.py`)
   currently requires `source`. Add an optional `concept` parameter. When
   `concept` is provided and `source` is not, call `concept_query()` instead
   of `query()`. Validate that exactly one of `source` or `concept` is
   provided.

3. **Handle authority-weighted scoring**
   Decide the merge formula: `final_score = hit.score * authority_score`
   (multiplicative) or `final_score = rrf_rank(hit) * authority_score`
   (rank-based). Since BM25 hybrid retrieval uses RRF, the scores are
   already rank-based (1/(rank+k)). Multiplicative weighting should work:
   higher-authority sources' hits float up in the merged list.

4. **Add benchmark dimension**
   Extend `eval_ontology_benchmark.py` with concept-first queries that
   compare single-source retrieval against concept-based fan-out. Measure:
   source coverage (how many sources contribute hits), recall improvement.

5. **Test with real queries**
   - `retrieve(concept="Condition")` should hit SNOMED, FHIR, Hetionet,
     ClinicalTrials, PubMed, VA-CPG
   - `retrieve(concept="Aircraft Component")` should hit aircraft-maintenance,
     aircraft-sb-test, aircraft-sb-process
   - Verify deduplication works when the same chunk is returned by ontology
     expansion and direct match

**Sequencing.** Step 1 is the core logic. Step 2 wires it into the MCP
server. Step 3 is a design decision to make during step 1. Steps 4-5
validate. All can run locally.

**Constraints for the session:**
- Keep `concept_query()` in `retrieval/api.py` alongside `query()`. Reuse
  the existing `query()` for per-source calls — don't duplicate retrieval
  logic.
- The MCP server change should be backward-compatible — existing callers
  that pass `source=` must work unchanged.
- Authority scores are already in the DB. Read them at query time from
  `OntologyMapping.authority_score`, don't recompute.
- The benchmark's authority_correlation metric is broken with RRF scores
  (see session 2 notes). Don't use it as a quality signal. Use hit count
  lift and source coverage instead.

**Session start protocol:**
- Premise checks (~5 min, report before acting):
  1. Confirm `query()` in `retrieval/api.py` still has the signature
     `query(source_slug, query_text, *, session, top_k, ...)`
  2. Confirm MCP `retrieve` tool in `server.py` requires `source` parameter
  3. Run a quick `retrieve(source="hetionet-hypertension", concept query)`
     to verify the local stack (DB + embedding service) works
- Rules with history:
  1. `flag_modified()` for `semantic_context` mutations (CLAUDE.md)
  2. `127.0.0.1` not `localhost` for DB connections (CLAUDE.md)
  3. Port-forward to embedding service may be stale — check before running
     queries
- Stop-and-ask before: modifying the MCP server's public tool signatures,
  deploying to cluster.
- Close ritual: session summary + `/plan-next-session ontology-v2` to queue
  Phase 3 (#63).

## Remaining epic phases

### Phase 1: Authority score improvements (#68) -- COMPLETE

Shipped 2026-09-10. Added formal terminology, entity coverage, and
data freshness signals. Score range widened from 0.632 to 0.980
(29 distinct scores). Doctor score clustering: 17 → 1. Benchmark
correlation metric invalidated by BM25 hybrid retrieval change (#65)
but retrieval quality metrics held or improved.

**Dependencies:** None.

### Phase 2: Concept-first retrieval (#62)

`retrieve(concept="Condition")` without naming a source. Fan-out to
all sources with that concept, merge results weighted by authority
scores.

**Definition of done:** API accepts `concept=` parameter. Fan-out
queries all mapped sources and merges results. Benchmark validates
cross-source recall.

**Dependencies:** Phase 1 (meaningful scores improve fan-out ranking).

### Phase 3: Eval-driven self-improvement (#63)

Build an eval pipeline measuring per-mapping retrieval effectiveness
with a feedback loop to adjust authority scores and flag dead/stale
mappings.

**Definition of done:** Eval run produces per-mapping quality scores.
Auto-adjustment of authority scores based on observed retrieval
performance. Doctor integration for flagged mappings.

**Dependencies:** Phase 2 (concept-first queries generate the per-mapping
signal data).

### Phase 4: Query success monitoring (#64)

Instrument the retrieval path to track per-mapping hit rates and
trigger self-improvement when thresholds are crossed.

**Definition of done:** Per-mapping metrics stored. Trigger conditions
fire the doctor or score adjustment when hit rates drop. Dashboard or
report for ops visibility.

**Dependencies:** Phase 3 (self-improvement pipeline must exist for
triggers to invoke).

### Phase 5: Onboarding pipeline with HITL (#61) -- COMPLETE

Shipped 2026-09-10. Entity discovery via LLM (discover_entities()),
CLI review wizard (review_ontology_proposal.py), pipeline integration
(Stage 8 of pipeline.ingest()), doctor validation after ontology
population. All 5 acceptance criteria met.

## What landed last session (2026-09-10, session 2)

Authority score range widened (Phase 1, #68). Added 3 new scoring signals
to the 6-factor formula: formal terminology (1.2x boost for SNOMED, FHIR,
Hetionet, ClinicalTrials), log2-scaled entity coverage, and data freshness
(no-op while `last_refresh_at` is null). Score range: 0.632 → 0.980,
distinct scores: 11 → 29, clustering findings: 17 → 1. Doctor WARN count
unchanged (29). Retrieval quality held (overall hit lift +7.75 → +8.5).

Benchmark authority_correlation dropped (r=0.358 → 0.096) but this is
caused by BM25 hybrid retrieval (#65) changing similarity scores to
RRF-based values (only 6 distinct scores across 57 hits). The metric is
structurally unable to discriminate with rank-based RRF scores.

## What landed (2026-09-10, session 1)

HITL onboarding pipeline shipped (Phase 5, #61). Entity discovery via LLM,
CLI review wizard, pipeline integration as Stage 8, doctor validation.
`flag_modified` fix for JSON column persistence. Retro ran covering
platform-quality + onboarding pipeline.

**Closed:** #61 — Onboarding pipeline with HITL — all 5 acceptance criteria met

## Watch out for

- The `semantic_context` JSON column needs `flag_modified()` after mutation
  (CLAUDE.md lesson).
- The benchmark's authority_correlation metric is structurally broken with
  RRF-based scores (only 6 distinct similarity values across 57 hits).
  Don't use it as a quality signal. Use hit count lift and source coverage.
- Fan-out query performance: calling `query()` per-source sequentially
  could be slow with many sources. Consider whether to parallelize or
  just document the expected latency.
- The MCP `retrieve` tool signature change must be backward-compatible.
  Existing callers pass `source=` and must continue to work.

## If blocked

- If the local catalog DB is missing ontology data, re-run
  `scripts/onboard_ontology_sources.py` to repopulate.
- If the embedding service is down, re-establish port-forward:
  `oc port-forward svc/retrieval-hub-embedding 8081:8080 --context=gpt-oss-120b -n retrieval-hub`
- If concept_query fan-out is too slow, start with serial calls and add a
  note about async fan-out as a follow-up. Correctness before performance.

## What this covers (and what it doesn't)

**In scope:**
- #61 Onboarding pipeline with HITL (closed)
- #62 Concept-first retrieval
- #63 Eval self-improvement loops
- #64 Query success monitoring
- #68 Authority score improvements (closed)

**Out of scope:**
- Platform ops (NEXT_SESSION-platform-ops.md): #27, #66, #67, #70
- Platform quality (NEXT_SESSION-platform-quality.md): #65
