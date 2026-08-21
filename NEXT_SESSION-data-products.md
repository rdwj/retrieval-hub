# Next Session -- data-products

## Next: PubMed-hypertension chunking parameter sweep

Run the chunking refinement methodology (`docs/chunking-refinement-methodology.md`)
against the pubmed-hypertension corpus. First real test of the methodology
document. The BioC section-aware chunker adds a dimension the VA CPG sweep
didn't have: `respect_section_boundaries` (True/False). This is also the
first sweep using section-tagged chunks from structured source JSON.

Paper-quality lab notes are a first-class deliverable, not an afterthought.
The VA CPG E3 sweep runs in a separate session so each sweep gets the full
attention and documentation it deserves.

1. **Define sweep grid and hypothesis**
   Follow Steps 1-2 of the methodology doc. The grid adds a section-aware
   dimension that the VA CPG sweep doesn't have:
   - Chunker: section-aware (BioC) vs token-fixed
   - Token sizes: 256 / 512 / 1024
   - Overlap: 0 / 64
   - Section boundaries: respected vs ignored (section-aware only)
   - Record the hypothesis before running: which config do we expect to
     win, and why?

2. **Sweep: re-ingest + eval per config (~8-10 configs)**
   Re-ingest the 10 PMC articles per config into
   `idx_pubmed_hypertension_v1`, run retrieval eval against the
   25-question QA dataset (`eval/pubmed_hypertension/qa_dataset.json`)
   using hit_rate@5 and MRR@5.
   - Each config: ingest, verify chunk count, run eval, record row
   - If a config fails ingestion, record the failure and move on

3. **Ragas answer-quality on winner vs runner-up**
   Run answer-quality metrics (faithfulness, answer relevancy) on the
   top two configs to confirm the retrieval metrics tell the full story.

4. **Lab notes (paper-quality)**
   Write the full decision chain: hypothesis, results table, analysis,
   why the winner won, what surprised us, how to replicate. These notes
   feed the arXiv paper. Format: structured enough to cite, informal
   enough to show the thinking process.

**Constraints for the session:**
- Record all results in structured format under `eval/pubmed_hypertension/`
  (one results file per config, plus summary table)
- The pubmed sweep needs re-ingestion per config (~10 articles, fast)
- Commit the Phase 1 deliverables from the prior session before starting
  (uncommitted files from the pubmed-hypertension baseline work)
- The eval register format from `eval/rewrite_lift/EVAL_REGISTER.md`
  is the model for structured results

**Session start protocol:**
- Premise checks (before item 1, ~5 min):
  - Verify local Postgres (ports 5434/5433) is running
  - Verify `idx_pubmed_hypertension_v1` table exists with 233 rows
  - Verify PubMedBERT model is cached in `.model_cache/`
  - `git status` -- commit the uncommitted Phase 1 files first
  - Read `docs/chunking-refinement-methodology.md` and follow its steps
    rather than improvising
- Rules with history:
  - TECHNICAL_DOCUMENT enum: resolved (a619ff3). Was never a linter
    issue -- the value was added but never committed during Phase 1.
    Now committed and passing all checks.
  - Record sweep results as structured data (JSON/CSV), not just prose.
- Stop-and-ask before: dropping and recreating pgvector tables (the
  `write_chunks(replace=True)` default deletes all rows first -- this is
  expected for sweep re-ingestion but confirm the table name is correct)
- Close ritual: session summary, update eval register with sweep results,
  update `NEXT_SESSION-data-products.md` with what landed

**Loop design:**
- **Exit predicate:** All configs in the sweep grid have been ingested,
  evaluated, and recorded. Results table is complete with no blank cells.
- **Max iterations:** ~8-10 configs (PubMed only).
- **Per-item verifier:** Each config produces a row in the results table
  with hit_rate@5 and MRR@5 values. Ingestion log confirms chunk count
  matches expected range for the config.
- **Premise to re-validate each pass:** The pgvector table exists and
  the previous config's data was successfully replaced.
- **Maker != checker:** Ingestion script produces chunks; eval script
  independently scores retrieval quality. Different code paths.
- **If stuck:** If a config fails ingestion (e.g., OOM on large chunks),
  record the failure in the results table and move to the next config.
  Don't block the sweep on one broken config.

## Remaining epic phases

RetrievalHub serves multiple data products across domains. This epic takes
it from one dataset (VA CPG) to three or more, with documented chunking
refinement for each, proven cross-dataset reasoning, a data-owner-accessible
onboarding process, and evidence for whether agent-driven dataset selection
scales. Every phase produces lab notes showing the thinking and process, not
just the results. These notes feed the arXiv paper alongside the CDC
contextual fidelity work.

### Phase 1: PubMed-hypertension baseline [DONE -- 2026-08-20]

Ingested 10 PMC review articles as source slug `pubmed-hypertension`
(233 chunks, PubMedBERT 768-dim, pgvector table `idx_pubmed_hypertension_v1`).
Built a BioC section-aware chunker that reads structured JSON directly,
preserving section_type labels, passage boundaries, and citation metadata.
Created 25-question eval QA dataset (including 5 cross-dataset questions).
Documented the chunking refinement methodology in
`docs/chunking-refinement-methodology.md`. Added TECHNICAL_DOCUMENT to
SourceFamily enum.

Key finding (paper-worthy): source format selection affects retrieval
quality before chunking parameters enter the picture. BioC JSON preserves
section types, references, and passage boundaries that markdown extraction
loses.

### Phase 2: Chunking refinement sweep + lab notes

Run the 8-step methodology from `docs/chunking-refinement-methodology.md`
against the pubmed-hypertension corpus. This is the first test of whether
the methodology document is actually followable, and produces the
quantitative evidence for the paper.

**Work:**
1. Define the sweep grid (section-aware vs token-fixed, 256/512/1024
   tokens, 0/64 overlap, section boundaries respected vs ignored)
2. Re-ingest per config, run retrieval eval against the 25-question QA
   dataset (hit_rate@5, MRR@5)
3. Run Ragas answer-quality metrics on the winner vs runner-up
4. Write lab notes: hypothesis, results table, analysis, why the winner
   won, what surprised us, how to replicate
5. Optionally run the VA CPG E3 sweep (eval-convergence epic overlap) in
   the same session to compare domain effects on chunking

**Definition of done:** Sweep results table recorded in
`eval/pubmed_hypertension/`, winner re-ingested as the production config,
eval baseline established, lab notes document the full decision chain from
hypothesis to outcome.

**Dependencies:** None (Phase 1 is done)

**Parallel-ok:** Yes, independent of other epics. The VA CPG E3 sweep
from eval-convergence can run alongside.

### Phase 3: Cross-dataset reasoning agent test + lab notes

Test whether a well-prompted agent naturally discovers and combines VA CPG
and pubmed-hypertension sources without being told which datasets to use
or how to combine them. The agent's discipline should be source
discovery/retrieve/refine loops: "What does VA CPG say about treating this
patient?" followed by "I have a dataset of scientific articles on
hypertension -- maybe there is something in there that adds value."

The CDC project (`MCP/CDC/data-acceptance-testing`) tested cross-dataset
reasoning as one of five question types. Their cross-dataset scores
improved from weakest category to 4.14/5.0 through structured scope
signals. Our approach differs: rather than a multi-source retrieve tool,
we test agent behavior patterns and prompting strategies.

**Work:**
1. Build a system prompt that encourages cross-dataset reasoning without
   spelling out specific datasets or solutions
2. Run the 5 cross-dataset questions from the eval QA dataset through
   the agent with the MCP server
3. Test additional ad-hoc queries to probe agent behavior
4. Iterate on the system prompt based on what fails
5. Write lab notes: what prompting patterns encourage cross-dataset
   reasoning, what fails, how the agent discovers complementary sources,
   comparison with the CDC project's approach

**Definition of done:** Agent successfully discovers both sources, queries
each independently, and synthesizes across results for at least 3 of 5
cross-dataset eval questions. Documented system prompt patterns that work
and patterns that fail.

**Dependencies:** Phase 2 (need optimized chunking, not baseline)

**Parallel-ok:** No, sequential after Phase 2

### Phase 4: Aircraft-maintenance ingestion + stress test + lab notes

269 Piper Aircraft service bulletins (Cherokee PA-28 + Saratoga PA-32),
a different domain from clinical text. Tests three things: pipeline
throughput at 10-40x the pubmed volume, whether the chunking refinement
methodology transfers to a non-clinical domain, and embedding model
deployment (snowflake-arctic-embed-m-v1.5 on vLLM).

**Work:**
1. Deploy snowflake-arctic-embed-m-v1.5 on the cluster via vLLM
2. Write `scripts/ingest_aircraft_maintenance.py` following the ingestion
   pattern (Docling-extracted markdown, token-fixed chunker)
3. Run ingestion, document pipeline throughput (chunks/sec, total time,
   memory usage, where bottlenecks appear)
4. Build eval QA dataset for aircraft maintenance (20-30 questions
   covering service bulletins, inspection procedures, parts, ADs)
5. Run chunking refinement sweep using the methodology doc
6. Write lab notes: pipeline performance at scale, where it breaks (if
   anywhere), embedding model deployment process, does the chunking
   methodology transfer to technical maintenance documents or does the
   domain require different defaults?

**Definition of done:** Aircraft source registered as TECHNICAL_DOCUMENT,
chunking sweep completed, pipeline performance documented with throughput
numbers, lab notes cover domain transfer of the methodology.

**Dependencies:** Phase 2 (validated methodology to apply to new domain)

**Parallel-ok:** Yes, independent of Phase 3 -- can run concurrently

### Phase 5: Data owner onboarding path + lab notes

Distill the onboarding process into something a domain expert (non-AI
engineer) could follow. The target persona: a technical person who knows
their data domain well but has no experience with OpenShift, embeddings,
agents, or vector databases. For the DoD, this needs to be a credible
path from "I have a dataset" to "agents can answer questions about it
through RetrievalHub."

**Work:**
1. Review the onboarding journey doc (`docs/onboarding-journey-va-cpg.md`)
   and chunking methodology through the eyes of a domain expert -- where
   do they get stuck? What assumptions are baked in?
2. Identify the minimum viable tooling: guided CLI, templates, or clearer
   docs that remove AI/ML jargon
3. Prototype the simplest improvement (likely a template + guided doc
   rather than a CLI tool for now)
4. Test by simulating a domain expert walkthrough
5. Write lab notes: where domain experts get stuck, what assumptions need
   to be removed, what the gap is between "platform team does it" and
   "domain expert does it"

**Definition of done:** A domain expert could reasonably follow the
process from data to serving agents, documented with evidence of what
works and what gaps remain. Lab notes cover the accessibility analysis.

**Dependencies:** Phases 2 + 4 (need two completed onboardings across
different domains to generalize the process)

**Parallel-ok:** No, needs both prior onboardings as input

### Phase 6: Dataset selection at scale + lab notes

Research question: at what catalog size does "list_sources + agent picks
the right one" break down? With 3 sources the agent can read all
descriptions. At 300 or 3000, it cannot. Do we need an AI-based dataset
routing tool (agent-as-tool that takes the user's question and selects a
subset of sources), or do other patterns (source categories, domain
tags, hierarchical discovery) work well enough?

**Work:**
1. Test agent behavior with the real 3-source catalog (VA CPG, pubmed,
   aircraft) -- does it pick the right source for domain-specific queries?
2. Create synthetic catalog entries (50-100 fake sources with realistic
   descriptions) and test again
3. Scale to 300+ synthetic entries, measure where accuracy drops
4. If routing is needed: prototype an agent-as-tool that takes a query
   and returns top-N relevant sources
5. Write lab notes: agent behavior at each scale, what patterns help,
   cost/benefit analysis of routing layers

**Definition of done:** Evidence-based recommendation on agent vs
routing-tool approach, with experimental data at multiple catalog sizes.
Documented in lab notes with enough detail for the paper.

**Dependencies:** Phase 4 (need 3+ real sources to start testing)

**Parallel-ok:** No, sequential after Phase 4

### Phase 7: Lab notes consolidation + paper outline

Pull findings from all phases into structured lab notes. Update the arXiv
paper outline with RetrievalHub material alongside the CDC contextual
fidelity work. The paper angle: a reproducible process for making domain
data serve AI agents well, with lab notes showing the thinking at every
step. Readers should learn how to improve their own systems, not read a
product announcement.

**Work:**
1. Review lab notes from Phases 2-6 for completeness and cross-references
2. Structure the RetrievalHub paper contribution: source format selection,
   chunking refinement methodology, cross-dataset reasoning patterns,
   data-owner accessibility, dataset selection at scale
3. Update the arXiv paper outline (currently in
   `eval/rewrite_lift/EVAL_PLAN.md`) with new sections
4. Identify which lab notes need quantitative evidence vs which are
   already supported
5. Write any missing lab notes or fill gaps in existing ones

**Definition of done:** Paper outline has enough material for a draft
across all RetrievalHub contributions. All lab notes cross-referenced and
findable. A reader could follow the lab notes and replicate our findings.

**Dependencies:** Phases 2-6

**Parallel-ok:** No, synthesizes everything

---

## What this covers (and what it doesn't)

**In scope:**
- Ingesting pubmed-hypertension and aircraft-maintenance data products
- Chunking refinement methodology (documented, tested, reproducible)
- Cross-dataset reasoning via agent behavior (not multi-source tool)
- Pipeline stress testing at scale
- Data owner accessibility for non-AI-engineers
- Dataset selection at scale research
- Lab notes and paper material for every phase
- Embedding model deployment (snowflake-arctic-embed-m-v1.5)

**Out of scope (other epics own):**
- Retrieval quality optimization (rewriting, reranking, hybrid scoring) --
  `NEXT_SESSION-eval-convergence.md`
- Refine tool entity-arc retrieval -- `NEXT_SESSION-refine-tool.md`
- Issue #34 (multi-source search API) -- not needed; agent discipline
  replaces tool-level multi-source
- Issue #30 (MCP server authentication) -- separate infrastructure concern
- Issue #27 (production ingestion runners / Tekton) -- may be informed by
  Phase 4 stress test findings but is separate infrastructure work

## What landed last session (2026-08-20)

Phase 1 completed: pubmed-hypertension baseline ingestion.

**New files:**
- `src/retrieval_hub/ingestion/chunking/bioc_section.py` -- BioC
  section-aware chunker (23 unit tests in
  `tests/test_ingestion/test_bioc_chunker.py`)
- `scripts/ingest_pubmed_hypertension.py` -- 7-stage ingestion script
- `eval/pubmed_hypertension/qa_dataset.json` -- 25 Q/A pairs (20
  single-source + 5 cross-dataset)
- `docs/chunking-refinement-methodology.md` -- 8-step repeatable
  methodology with BioC-vs-markdown appendix

**Modifications:**
- `src/retrieval_hub/models/enums.py` -- added TECHNICAL_DOCUMENT to
  SourceFamily and EvalSuiteFamily
- `src/retrieval_hub/ingestion/chunking/__init__.py` -- exports for new
  chunker

**Ingestion results:** 10 articles, 233 chunks, 78K tokens, 23.9s wall
time. Source registered as `pubmed-hypertension` (CLINICAL_DOCUMENT,
curated). Section distribution: CONCL 42, METHODS 35, TABLE 33, INTRO
31, RESULTS 31, DISCUSS 27, FIG 17, ABSTRACT 10.

**Key finding:** Chunking from structured BioC JSON preserves section_type
labels, passage boundaries, and citation metadata that markdown extraction
loses. Paper-worthy -- documented in the methodology appendix.

**Parallel session:** refine-tool epic landed entity-arc refinement
(Phase 4) in a separate session. Eval-convergence deferred to let this
epic's sweep run next.

## Watch out for

- The eval-convergence epic's E3 (chunk sweep) overlaps with Phase 2.
  Decision: one sweep per session so each gets paper-quality lab notes.
  PubMed sweep runs first (this session); VA CPG E3 sweep runs in a
  follow-up session with the same eval harness for comparability.
- Embedding model deployment (Phase 4) depends on cluster access and GPU
  availability. Check cluster state before starting.

## If blocked

- **Cluster unavailable for Phase 4:** Do the aircraft ingestion locally
  with CPU-based embedding (slower but functional). Deploy the model when
  the cluster is back.
- **Cross-dataset reasoning fails (Phase 3):** Iterate on the system
  prompt. If the pattern fundamentally doesn't work with current MCP tool
  design, document why and consider whether a lightweight source-discovery
  tool (not multi-source retrieve) would help.
- **Chunking sweep infrastructure broken:** Fall back to manual
  re-ingestion per config rather than automated sweep.
