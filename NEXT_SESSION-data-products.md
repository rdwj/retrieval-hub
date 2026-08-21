# Next Session -- data-products

## Next: Aircraft chunking sweep + cross-domain comparison

Run the chunking refinement methodology (`docs/chunking-refinement-methodology.md`)
against the aircraft-maintenance corpus. The PubMed sweep already landed
(SA-256-0 won at 0.950 hit_rate, Ragas confirmed — see
`eval/pubmed_hypertension/CHUNKING_SWEEP.md`). This session completes
Phase 3 by running the aircraft sweep and writing the cross-domain
comparison lab notes.

The aircraft sweep is token-fixed only (no BioC structure — source is
Docling-extracted markdown). The comparison with the PubMed results is
a paper contribution: do chunking defaults transfer across domains, or
does technical maintenance content need different parameters?

1. **Write sweep script**
   Adapt `scripts/sweep_pubmed_chunking.py` for the aircraft corpus.
   Key differences: remote embedding via vLLM endpoint (not local
   PubMedBERT), token-fixed chunker only, different eval dataset
   (`eval/aircraft_maintenance/qa_dataset.json`). The baseline is
   512/64 (current ingestion config).

2. **Define sweep grid and hypothesis**
   Grid (token-fixed only, ~6 configs):
   - Token sizes: 256 / 384 / 512
   - Overlap: 0 / 64
   - Hypothesis: aircraft service bulletins are shorter and more
     structured than clinical literature — smaller chunks (256) may
     win because each bulletin covers a single topic. But overlap
     should help since procedural steps span chunk boundaries.
   - Record hypothesis before running.

3. **Sweep: re-ingest + eval per config**
   Re-ingest all 263 docs per config via the remote vLLM endpoint,
   run retrieval eval against the 25-question QA dataset using
   hit_rate@5 and MRR@5.
   - Important: the BERT tokenizer mismatch means `truncate_prompt_tokens`
     is already set in the embed module. Larger chunk sizes (512) will
     have some tokens truncated on outlier chunks — this is expected
     and documented.

4. **Ragas answer-quality on winner vs runner-up**

5. **Lab notes: cross-domain comparison**
   Write the full decision chain for both sweeps side by side:
   hypothesis, results tables, why each winner won, whether the
   methodology doc was followable for a second domain, and what
   surprised us. These notes feed the arXiv paper.

**Session start protocol:**
- Premise checks (~5 min):
  - Verify local Postgres (ports 5434/5433) is running
  - Verify `idx_aircraft_maintenance_v1` table exists with 2330 rows
  - Verify vLLM endpoint is reachable:
    `curl -s https://vllm-snowflake-embedding-retrieval-hub.apps.cluster-khsm8.khsm8.sandbox780.opentlc.com/v1/embeddings -X POST -H 'Content-Type: application/json' -d '{"model":"Snowflake/snowflake-arctic-embed-m-v1.5","input":["test"]}'`
    If 503/timeout: check the pod on agent-security-dev-3 (`oc get pods --context=agent-security-dev-3 -n retrieval-hub`). The GPU
    machineset may have been scaled down between sessions.
  - Read `docs/chunking-refinement-methodology.md` and the PubMed sweep
    results (`eval/pubmed_hypertension/CHUNKING_SWEEP.md`) for context
  - Read `scripts/sweep_pubmed_chunking.py` to understand the sweep
    harness before adapting it
  - `git status` — commit any uncommitted files first
- Rules with history:
  - Record sweep results as structured data (JSON/CSV), not prose.
  - `truncate_prompt_tokens: 512` is set in `_remote_embed()` — don't
    reduce chunk size to work around BERT tokenizer expansion. The
    truncation is intentional and documented in CLAUDE.md.
- Stop-and-ask before: dropping and recreating `idx_aircraft_maintenance_v1`
  (the `write_chunks(replace=True)` default deletes all rows first)
- Close ritual: session summary, update eval register, update this file

**Loop design:**
- **Exit predicate:** All 6 configs have been ingested, evaluated, and
  recorded. Results table complete with no blank cells.
- **Max iterations:** 6 configs.
- **Per-item verifier:** Each config produces a row in the results table
  with hit_rate@5 and MRR@5 values. Ingestion log confirms chunk count
  is in expected range for the config.
- **Premise to re-validate each pass:** The pgvector table exists, the
  previous config's data was successfully replaced, and the vLLM endpoint
  is still responding (check between configs if ingestion was slow).
- **Maker != checker:** Ingestion script produces chunks via remote
  embedding; eval script independently scores retrieval quality against
  the QA dataset. Different code paths.
- **If stuck:** If a config fails embedding (vLLM timeout, pod crash),
  record the failure and move on. If the vLLM endpoint goes down
  mid-sweep, check the pod and restart if needed before continuing.

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

### Phase 3: Chunking refinement sweeps + lab notes [IN PROGRESS]

PubMed sweep DONE (parallel session 2026-08-21): SA-256-0 won at 0.950
hit_rate@5, Ragas confirmed. Results in `eval/pubmed_hypertension/`.
Pubmed ingestion updated to winner config.

Remaining: aircraft sweep + cross-domain comparison lab notes.

**Definition of done:** Sweep results tables in both `eval/` dirs,
winners re-ingested as production configs, cross-domain comparison
lab notes document whether chunking defaults transfer.

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

See `session-summaries/2026-08-21-data-products-aircraft-ingestion.md`.

Phase 2 completed: aircraft maintenance baseline ingestion with remote
embedding. 263 docs, 2330 chunks, snowflake-arctic-embed-m-v1.5 via vLLM.
Commits: `182e2e3`..`b7b7a65`.

Parallel session also completed PubMed chunking sweep (Phase 3 first half):
SA-256-0 won at 0.950 hit_rate@5. Commits: `5355ef4`..`f0edac2`.

## Watch out for

- The vLLM pod on agent-security-dev-3 and the L40S GPU node may be
  scaled down between sessions. Check both at session start. The GPU
  machineset is `gpu-cluster-khsm8-7cbl6-worker-us-east-2c` (currently
  3 replicas; was 2 before this session).
- Each sweep config re-embeds all 263 docs via the remote endpoint. At
  ~2 min per config (132s baseline), the full 6-config sweep should take
  ~12-15 min of embedding time. Budget accordingly.
- The `truncate_prompt_tokens: 512` in `_remote_embed()` means some
  chunks lose their tail tokens when BERT tokenization exceeds 512.
  This is expected for 512/64 configs but should not happen for 256/0.
  If it does, that's a data point worth noting in the lab notes.

## If blocked

- **vLLM endpoint down:** Check the pod on agent-security-dev-3. If the
  GPU node was scaled down, bump the machineset back to 3:
  `oc scale machineset gpu-cluster-khsm8-7cbl6-worker-us-east-2c --replicas=3 --context=agent-security-dev-3 -n openshift-machine-api`
  Then wait ~10 min for GPU driver installation.
- **Sweep script broken:** Fall back to manual re-ingestion per config
  by modifying constants in `ingest_aircraft_maintenance.py` and running
  the eval script by hand.
- **Cross-dataset reasoning fails (Phase 4):** Iterate on the system
  prompt. If the pattern fundamentally doesn't work with current MCP tool
  design, document why.
