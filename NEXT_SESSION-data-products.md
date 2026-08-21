# Next Session -- data-products

## Next: Chunking refinement sweeps (PubMed + aircraft)

Run the chunking refinement methodology (`docs/chunking-refinement-methodology.md`)
against both the pubmed-hypertension and aircraft-maintenance corpora. Two
sweeps, same methodology, different domains -- the comparison is a paper
contribution showing whether chunking defaults transfer across domains.

Paper-quality lab notes are a first-class deliverable, not an afterthought.
Run one sweep per session so each gets the full attention and documentation
it deserves.

### PubMed sweep (first session)

The BioC section-aware chunker adds a dimension the VA CPG sweep didn't
have: `respect_section_boundaries` (True/False).

1. **Define sweep grid and hypothesis**
   Follow Steps 1-2 of the methodology doc. Grid:
   - Chunker: section-aware (BioC) vs token-fixed
   - Token sizes: 256 / 512 / 1024
   - Overlap: 0 / 64
   - Section boundaries: respected vs ignored (section-aware only)
   - Record hypothesis before running

2. **Sweep: re-ingest + eval per config (~8-10 configs)**
   Re-ingest the 10 PMC articles per config into
   `idx_pubmed_hypertension_v1`, run retrieval eval against the
   25-question QA dataset using hit_rate@5 and MRR@5.

3. **Ragas answer-quality on winner vs runner-up**

4. **Lab notes (paper-quality)**

### Aircraft sweep (second session)

Same methodology applied to a technical maintenance domain with
token-fixed chunker only (no BioC structure available). This tests
whether the methodology doc is domain-portable.

**Session start protocol (PubMed sweep):**
- Premise checks (~5 min):
  - Verify local Postgres (ports 5434/5433) is running
  - Verify `idx_pubmed_hypertension_v1` table exists with 233 rows
  - Verify PubMedBERT model is cached in `.model_cache/`
  - Commit any uncommitted files first
  - Read `docs/chunking-refinement-methodology.md` and follow its steps
- Rules with history:
  - TECHNICAL_DOCUMENT enum: resolved (a619ff3).
  - Record sweep results as structured data (JSON/CSV), not just prose.
- Stop-and-ask before: dropping and recreating pgvector tables
- Close ritual: session summary, update eval register, update this file

**Loop design (per sweep):**
- **Exit predicate:** All configs in the sweep grid have been ingested,
  evaluated, and recorded. Results table complete with no blank cells.
- **Max iterations:** ~8-10 configs per sweep.
- **Per-item verifier:** Each config produces a row in the results table
  with hit_rate@5 and MRR@5 values.
- **Premise to re-validate each pass:** The pgvector table exists and
  the previous config's data was successfully replaced.
- **Maker != checker:** Ingestion script produces chunks; eval script
  independently scores retrieval quality.
- **If stuck:** Record the failure and move to the next config.

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

### Phase 2: Aircraft maintenance baseline ingestion [DONE -- 2026-08-21]

Deployed snowflake-arctic-embed-m-v1.5 on vLLM (agent-security-dev-3,
L40S GPU). Added remote embedding support to ChunkEmbedder/QueryEmbedder
(OpenAI-compatible `/v1/embeddings` endpoint). Ingested 269 Piper Aircraft
service bulletins (Cherokee PA-28 + Saratoga PA-32) using token-fixed
chunking (512/64) and remote embedding.

Key deliverables:
- `src/retrieval_hub/ingestion/embed.py` -- remote embedding backend
- `deploy/openshift/retrieval-hub/embedding/vllm-snowflake.yaml` -- vLLM manifest
- `scripts/ingest_aircraft_maintenance.py` -- 7-stage ingestion script
- `eval/aircraft_maintenance/qa_dataset.json` -- eval QA dataset
- Source registered as `aircraft-maintenance` (TECHNICAL_DOCUMENT)

Key finding (paper-worthy): remote embedding via vLLM's OpenAI-compatible
API integrates cleanly with the existing embedder interface. The same
`ChunkEmbedder`/`QueryEmbedder` classes work with both local
sentence-transformers and remote endpoints via a single `endpoint`
parameter.

### Phase 3: Chunking refinement sweeps + lab notes

Run the 8-step methodology from `docs/chunking-refinement-methodology.md`
against both the pubmed-hypertension and aircraft-maintenance corpora.
Two sweeps across different domains -- a paper contribution showing
whether chunking defaults transfer.

**Work:**
1. PubMed sweep: section-aware vs token-fixed, 256/512/1024 tokens,
   0/64 overlap, section boundaries respected vs ignored (~8-10 configs)
2. Aircraft sweep: token-fixed only, same size/overlap grid (~6 configs)
3. Ragas answer-quality on winners vs runners-up
4. Lab notes: domain comparison, methodology portability, what surprised us

**Definition of done:** Sweep results tables in `eval/pubmed_hypertension/`
and `eval/aircraft_maintenance/`, winners re-ingested as production
configs, lab notes document the full decision chain.

**Dependencies:** Phases 1 + 2 (both baselines done)

**Parallel-ok:** Yes, independent of other epics.

### Phase 4: Cross-dataset reasoning agent test + lab notes

Test whether a well-prompted agent naturally discovers and combines VA CPG,
pubmed-hypertension, and aircraft-maintenance sources without being told
which datasets to use. Now with 3 sources across 2 domains (clinical +
aviation), the agent must also distinguish domains, not just combine
similar datasets.

The CDC project (`MCP/CDC/data-acceptance-testing`) tested cross-dataset
reasoning as one of five question types. Their cross-dataset scores
improved from weakest category to 4.14/5.0 through structured scope
signals. Our approach differs: rather than a multi-source retrieve tool,
we test agent behavior patterns and prompting strategies.

**Work:**
1. Build a system prompt that encourages cross-dataset reasoning without
   spelling out specific datasets or solutions
2. Run cross-dataset questions from both eval QA datasets through
   the agent with the MCP server
3. Test additional ad-hoc queries to probe agent behavior
4. Iterate on the system prompt based on what fails
5. Write lab notes: what prompting patterns encourage cross-dataset
   reasoning, what fails, how the agent discovers complementary sources,
   comparison with the CDC project's approach

**Definition of done:** Agent successfully discovers relevant sources,
queries each independently, and synthesizes across results. Documented
system prompt patterns that work and patterns that fail.

**Dependencies:** Phase 3 (need optimized chunking, not baseline)

**Parallel-ok:** No, sequential after Phase 3

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

**Dependencies:** Phases 2 + 3 (need two completed onboardings across
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

**Dependencies:** Phase 4 (need 3 real sources with optimized chunking)

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

## What landed last session (2026-08-21)

Phase 2 completed: aircraft maintenance baseline ingestion with remote
embedding.

**New files:**
- `deploy/openshift/retrieval-hub/embedding/vllm-snowflake.yaml` -- vLLM
  Deployment + Service + Route for Snowflake Arctic Embed M v1.5 (GPU,
  OpenAI-compatible `/v1/embeddings` API)
- `scripts/ingest_aircraft_maintenance.py` -- 7-stage ingestion script
  for 269 Piper Aircraft service bulletins (Cherokee + Saratoga families)
- `eval/aircraft_maintenance/qa_dataset.json` -- 25 Q/A pairs (20
  single-source + 5 cross-dataset spanning aircraft + clinical domains)

**Modifications:**
- `src/retrieval_hub/ingestion/embed.py` -- added remote embedding
  backend: `ChunkEmbedder` and `QueryEmbedder` now accept an `endpoint`
  parameter to call an OpenAI-compatible `/v1/embeddings` API. Includes
  batching, exponential backoff retry, and dimension discovery. 15 new
  tests. Local backend unchanged when endpoint is None.
- `src/retrieval_hub/adapters/document.py` -- added `_embedding_endpoint()`
  to read endpoint from recipe, updated all 3 `QueryEmbedder` call sites
  (retrieve, cross_reference, entity_arc)

**Infrastructure:**
- Scaled GPU machineset on agent-security-dev-3 from 2 to 3 replicas
  (new L40S node). gpt-oss-120b was fully allocated (4/4 GPUs in use).
- Created `retrieval-hub` namespace on agent-security-dev-3.
- Deployed vLLM with `--task embed` flag for embedding model serving.

**Key finding:** Remote embedding via vLLM's OpenAI-compatible API
integrates cleanly with the existing embedder interface. No changes
needed to calling code -- the `endpoint` parameter routes to HTTP
automatically. The recipe stores the endpoint URL so the MCP server's
QueryEmbedder picks it up at retrieval time.

## What landed session before (2026-08-20)

Phase 1 completed: pubmed-hypertension baseline ingestion.

**New files:**
- `src/retrieval_hub/ingestion/chunking/bioc_section.py` -- BioC
  section-aware chunker
- `scripts/ingest_pubmed_hypertension.py` -- 7-stage ingestion script
- `eval/pubmed_hypertension/qa_dataset.json` -- 25 Q/A pairs
- `docs/chunking-refinement-methodology.md` -- 8-step repeatable
  methodology

**Ingestion results:** 10 articles, 233 chunks, PubMedBERT 768-dim.

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
