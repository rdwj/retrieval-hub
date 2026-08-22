# Next Session -- data-products

## Next: Dataset selection at scale (Phase 6)

Research question: at what catalog size does "list_sources + agent picks
the right one" break down? Phase 4 showed it works at 3 sources. Phase 6
tests at larger scales.

**Session start protocol:**
- Read Phase 4 lab notes for baseline metrics
- Consider synthetic source registrations (metadata-only, no real data)
  to test at 10/20/50 sources without ingesting real corpora
- `git status` — commit any uncommitted files first

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

### Phase 5: Data owner onboarding path + lab notes [DONE -- 2026-08-22]

Built `scripts/new_source.py` scaffolding tool that generates complete
ingestion scripts from a source slug. Generated scripts include the full
7-stage pipeline, Phase 4-informed description guidance, governance
templates, and CLI with all standard arguments. 43 unit tests. Makefile
`new-source` target. Updated `docs/guide-data-owner.md` with tool
reference.

**Dependencies:** Phases 2 + 3 (done)

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

**Phase 4**: Cross-dataset reasoning agent test. Scaffolded agent with
fips-agents 0.17.1 (Anthropic provider, Sonnet 5). 20-question eval
harness with automated source selection scoring. 2 prompt iterations.
Key finding: cross-domain selection works at 3-source scale (0.95
recall), within-domain discrimination unreliable. #34 deferred.
See `eval/cross_dataset_reasoning/LAB_NOTES.md`.

**Phase 5**: Source scaffolding tool (`scripts/new_source.py`). Generates
complete ingestion scripts from a slug. 43 unit tests. Makefile target.
Updated data owner guide with tool reference.

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
