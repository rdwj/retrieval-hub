# Next Session -- data-products

## Next: Data owner onboarding path (Phase 5)

Distill the data-to-serving pipeline into a process a domain expert
(non-AI engineer) could follow. Document what works, what requires
engineering help, and what gaps remain. Phase 4 findings inform what
metadata descriptions need to contain for effective agent-driven
source selection.

1. **Audit the current onboarding steps**
   Walk through what it takes to go from raw data to a serving source:
   data preparation, ingestion script, chunking sweep, Ragas validation,
   source registration, cluster deployment. Identify which steps require
   engineering skills vs domain expertise.

2. **Draft onboarding documentation**
   Write a guide that a domain expert could follow, noting where they
   need engineering help. Use the three existing sources (VA CPG, PubMed
   hypertension, aircraft maintenance) as worked examples.

3. **Identify gaps in the pipeline**
   What tooling is missing? Does the data owner need CLI tools, a web UI,
   templates? What metadata do they need to write (descriptions, usage
   rules) and what guidance do they need for effective agent-driven
   source selection (from Phase 4 findings)?

4. **Lab notes: onboarding path assessment**
   Document what works, what requires engineering intervention, and
   recommendations for making onboarding self-service.

**Session start protocol:**
- Premise checks (~5 min):
  - `git status` — commit any uncommitted files first
  - Review Phase 4 lab notes for source description findings
  - Review the three ingestion scripts to catalog the steps
- Rules with history:
  - Use `127.0.0.1` not `localhost` for any local Postgres connections
    (IPv4/IPv6 race condition — see CLAUDE.md).
- Stop-and-ask before: modifying the MCP server code or any production
  data source registrations.
- Close ritual: session summary, update this file

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
(381 chunks after chunking sweep, PubMedBERT 768-dim, pgvector table
`idx_pubmed_hypertension_v1`). Built a BioC section-aware chunker.
SA-256-0 won the chunking sweep at 0.950 hit_rate@5.

### Phase 2: Aircraft maintenance baseline ingestion [DONE -- 2026-08-21]

Deployed snowflake-arctic-embed-m-v1.5 on vLLM. Ingested 269 Piper Aircraft
service bulletins. TF-512-0 won the chunking sweep at 0.950 hit_rate@5,
0.749 MRR@5. Ragas confirmed (+4.3pp context_precision, +5.6pp
answer_relevancy over production baseline).

### Phase 3: Chunking refinement sweeps + lab notes [DONE -- 2026-08-21]

Both sweeps complete with Ragas confirmation. Cross-domain comparison
written. Key finding: optimal chunk size does NOT transfer across domains
(PubMed: 256 tokens, aircraft: 512 tokens). Overlap consistently hurts
MRR. Full results in `eval/pubmed_hypertension/CHUNKING_SWEEP.md` and
`eval/aircraft_maintenance/CHUNKING_SWEEP.md`.

### Phase 4: Cross-dataset reasoning agent test + lab notes [DONE -- 2026-08-22]

Scaffolded agent with `fips-agents create agent --provider anthropic`.
Built 20-question eval harness (10 cross-dataset, 5 single-source
controls, 5 ad-hoc probes) with automated source selection scoring.
Ran 2 prompt iterations (v0 baseline, v1 disambiguation).

Key findings: cross-domain source selection works well at 3-source scale
(0.95 recall). Within-domain discrimination (two clinical sources) is
unreliable from descriptions alone. Making the prompt more selective
(v1) hurt recall without improving exact match. The "over-query" behavior
(query both clinical sources) is the safer default.

Assessed #34 (multi-source search): not needed at current scale. Defer
until catalog grows beyond 5-10 sources with domain overlap.

Full results in `eval/cross_dataset_reasoning/LAB_NOTES.md`.

**Dependencies:** Phase 3 (done)

### Phase 5: Data owner onboarding path + lab notes

Distill the onboarding process into something a domain expert (non-AI
engineer) could follow.

**Definition of done:** A domain expert could reasonably follow the
process from data to serving agents, documented with evidence of what
works and what gaps remain.

**Dependencies:** Phases 2 + 3 (done)

**Parallel-ok:** Yes, dependencies met. Can start immediately.

### Phase 6: Dataset selection at scale + lab notes

Research question: at what catalog size does "list_sources + agent picks
the right one" break down?

**Dependencies:** Phase 4

### Phase 7: Lab notes consolidation + paper outline

Pull findings from all phases into structured lab notes and paper outline.

**Dependencies:** Phases 2-6

---

## What this covers (and what it doesn't)

**In scope:**
- Cross-dataset reasoning via agent behavior (not multi-source tool)
- Agent scaffolding with fips-agents + Anthropic API + Sonnet
- System prompt engineering for source discovery
- Lab notes and paper material
- Comparison with CDC project's structured scope signals approach

**Out of scope (other epics own):**
- Retrieval quality optimization -- `NEXT_SESSION-eval-convergence.md`
- Refine tool entity-arc retrieval -- `NEXT_SESSION-refine-tool.md`
- Issue #34 (multi-source search API) -- testing whether agent discipline
  suffices before building tool-level multi-source
- Issue #30 (MCP server authentication) -- separate infrastructure concern

## What landed last session (2026-08-22)

Phase 4 completed: cross-dataset reasoning agent test. Scaffolded agent
with fips-agents 0.17.1 (Anthropic provider, Sonnet 5). Built 20-question
eval harness with automated source selection scoring. Ran 2 prompt
iterations. Key finding: cross-domain source selection works at 3-source
scale (0.95 recall), within-domain discrimination unreliable.
Assessed #34: defer until catalog grows. Full results in
`eval/cross_dataset_reasoning/LAB_NOTES.md`.

## Watch out for

- The MCP server must be running with all 3 sources registered. Check
  `list_sources` at session start. If a source is missing, the catalog
  DB or pgvector table may need attention.
- The vLLM pod on agent-security-dev-3 may be scaled down between sessions.
  The embedding endpoint is needed for the MCP server to serve retrieval
  queries. Check the pod at session start.
- The IPv4/IPv6 dual-listener on port 5433 (Podman + oc port-forward)
  affects any script using `localhost`. Always use `127.0.0.1` for local
  Postgres. See CLAUDE.md lesson learned.
- The Anthropic API key needs to be available. Check env vars at session
  start.

## If blocked

- **MCP server down:** Focus on writing the system prompt and eval
  harness. Test with a mock or local MCP server.
- **Anthropic API unavailable:** Use a local model via Ollama as a
  fallback. The prompt engineering findings should transfer, though
  source selection behavior may differ with a weaker model.
- **Source data missing:** Re-run the relevant ingestion script. All
  three ingest scripts are in `scripts/`.
