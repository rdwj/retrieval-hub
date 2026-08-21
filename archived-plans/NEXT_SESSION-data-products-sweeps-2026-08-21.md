# Next Session -- data-products-sweeps

## Next: Aircraft maintenance chunking sweep

Run the chunking refinement methodology (`docs/chunking-refinement-methodology.md`)
against the aircraft-maintenance corpus. Same process as the PubMed sweep,
different domain: 269 Piper service bulletins (token-fixed chunker only, no
BioC structure). The cross-domain comparison with PubMed results is the paper
contribution: do optimal chunking parameters transfer across document types?

1. **Adapt the sweep script for aircraft-maintenance**
   Fork `scripts/sweep_pubmed_chunking.py` into
   `scripts/sweep_aircraft_chunking.py`. Key differences:
   - Token-fixed chunker only (no BioC section-aware -- source is Docling
     markdown, not structured JSON)
   - Embedding model: Snowflake Arctic Embed M v1.5 (384-dim) via remote
     vLLM endpoint, not local PubMedBERT
   - QA dataset schema differs: `expected_doc_title` (not `source_doc`),
     matching on exact `doc_title` equality
   - Production table: `idx_aircraft_maintenance_v1`
   - Sweep table: `idx_aircraft_maintenance_sweep`
   - Current baseline: TF-512-64 (512 tokens, 64 overlap)
   - 269 documents / 307 markdown files -- re-ingestion per config is
     slower (~10 min each vs ~30s for PubMed's 10 articles)

2. **Define sweep grid and hypothesis**
   Follow Steps 1-2 of the methodology doc. Grid (token-fixed only):
   - TF-512-64 (current baseline)
   - TF-512-0 (remove overlap -- PubMed sweep found overlap harmful)
   - TF-256-0 (PubMed winner was 256 tokens)
   - TF-256-64 (small with overlap)
   - TF-1024-0 (large chunks)
   - TF-1024-128 (large with overlap, tests if larger context benefits
     from overlap more than small/medium chunks)
   Record hypothesis before running. The PubMed findings set strong
   priors: 256 tokens likely wins, overlap likely hurts. The question is
   whether these transfer to a non-clinical domain with shorter, more
   structured documents (service bulletins are 1-3 pages vs 10-20 page
   review articles).

3. **Run the sweep (~6 configs)**
   Re-ingest per config, eval against the aircraft QA dataset. The
   remote embedding endpoint means re-ingestion is network-bound, not
   CPU-bound -- wall time depends on vLLM throughput.

4. **Ragas answer-quality on winner vs baseline**
   Adapt `scripts/eval_chunking_answer_quality.py` for aircraft.

5. **Cross-domain comparison lab notes**
   The paper-quality deliverable. Compare PubMed and aircraft sweep
   results side by side:
   - Do optimal chunk sizes differ across domains?
   - Does the "overlap is harmful" finding generalize?
   - Does the VA CPG prior (512 tokens) transfer better to service
     bulletins (shorter, structured) than to review articles (longer,
     narrative)?
   - What does this tell us about domain-specific vs universal chunking
     defaults?

**Sequencing.** Adapt script first (item 1), then hypothesis (item 2),
then sweep (item 3). Ragas (item 4) only if the sweep completes with
time remaining. Cross-domain comparison (item 5) is the session's main
written deliverable.

**Constraints for the session:**
- The vLLM embedding endpoint on agent-security-dev-3 must be running.
  Check before starting -- if the GPU node was scaled down or the pod
  evicted, re-ingestion won't work. See
  `deploy/openshift/retrieval-hub/embedding/vllm-snowflake.yaml`.
- Remote embedding adds network latency. 269 documents x re-ingestion
  per config = significant wall time. Budget ~60 min for the sweep
  (6 configs x ~10 min each).
- Use the same eval harness structure as the PubMed sweep so metrics
  are directly comparable across domains.
- The aircraft QA dataset uses `expected_doc_title` (not `source_doc`)
  and has no `pmc_id` field. The sweep script needs to match on
  `doc_title` directly.

**Session start protocol:**
- Premise checks (before item 1, ~10 min):
  - Verify local Postgres (ports 5434/5433) is running
  - Verify `idx_aircraft_maintenance_v1` table exists with expected rows
  - Verify vLLM embedding endpoint is reachable:
    `curl -s https://vllm-snowflake-embedding-retrieval-hub.apps.agent-security-dev-3.rh-aiservices-bu.com/v1/models`
    (or whatever the route is -- check the OpenShift route)
  - `git status` -- commit any uncommitted files first
  - Read `docs/chunking-refinement-methodology.md` Steps 1-4
  - Read the PubMed sweep lab notes (`eval/pubmed_hypertension/CHUNKING_SWEEP.md`)
    for the priors that inform the hypothesis
- Rules with history:
  - The cl100k_base tokenizer differs from Snowflake's WordPiece
    tokenizer (1.3-1.5x ratio). The remote endpoint uses
    `truncate_prompt_tokens: 512` to handle this. Don't reduce
    cl100k_base chunk size to compensate -- the truncation loss is
    minimal (see CLAUDE.md lesson learned).
  - Record sweep results as structured data (JSON), not just prose.
- Stop-and-ask before: dropping and recreating pgvector tables
  (`write_chunks(replace=True)` on the sweep table is expected; confirm
  the table name is the sweep table, not production)
- Close ritual: session summary, update this file with what landed,
  commit sweep results and lab notes

**Loop design:**
- **Exit predicate:** All configs in the sweep grid have been ingested,
  evaluated, and recorded. Results table complete with no blank cells.
- **Max iterations:** ~6 configs.
- **Per-item verifier:** Each config produces a row in the results table
  with hit_rate@5 and MRR@5 values. Ingestion log confirms chunk count.
- **Premise to re-validate each pass:** The pgvector sweep table exists,
  the previous config's data was successfully replaced, and the vLLM
  endpoint is still responding.
- **Maker != checker:** Ingestion script produces chunks; eval script
  independently scores retrieval quality. Different code paths.
- **If stuck:** If the vLLM endpoint goes down mid-sweep, pause and
  check cluster state. If a config fails ingestion, record the failure
  and move on. Don't block the sweep on one broken config.

## What landed last session (2026-08-21)

PubMed chunking sweep completed (data-products Phase 3, first half).

- a619ff3 -- TECHNICAL_DOCUMENT enum fix (was never committed, not a linter issue)
- 4787aaa -- BioC section-aware chunker + 23 tests (Phase 1 deliverable, committed)
- cb097d9 -- PubMed ingestion script, QA dataset, chunking methodology doc
- 5355ef4 -- Sweep script: 9 configs, direct pgvector eval, JSON checkpoints
- aa9530a -- Sweep results + paper-quality lab notes
- 5e4089d -- Production re-ingestion with SA-256-0, Ragas comparison script
- 1cf935c -- Ragas results confirming SA-256-0

**Key findings (carry forward as priors for aircraft sweep):**
- SA-256-0 won at 0.950 hit_rate@5, +10pp over all others
- Token-fixed tied section-aware at 512 tokens (model quality dominates)
- Overlap was actively harmful (-10pp across the board)
- Ragas confirmed: context_precision +4.1pp, answer_relevancy +7.8pp

**Parallel session also moved on:** eval-convergence landed embedding
model comparison (Nomic v1.5 for VA CPG) and aircraft-maintenance
baseline ingestion (data-products Phase 2).

## Watch out for

- The vLLM embedding endpoint is on a GPU node that could be scaled down
  or reallocated. Check before starting the sweep. If unavailable, the
  fallback is local CPU embedding with sentence-transformers (much slower
  but functional for 269 documents).
- The aircraft QA dataset has 25 questions but 9 of them have `category=None`
  (the cross-aircraft and cross-dataset questions). Inspect these before
  the sweep to decide whether to include or exclude them from eval.
- Re-ingestion wall time is ~10 min per config (269 docs, remote embedding).
  A 6-config sweep takes ~60 min. Plan the session around this.

## If blocked

- If the vLLM endpoint is down and can't be recovered: do the sweep
  with local sentence-transformers and the same Snowflake model. Slower
  but produces identical embeddings. The sweep script needs a
  `--local-embedding` flag for this fallback.
- If cluster access is fully blocked: write the cross-domain comparison
  lab notes using only the PubMed sweep results and the aircraft baseline
  (no sweep), noting the gap. The comparison is less complete but still
  contributes to the paper.
