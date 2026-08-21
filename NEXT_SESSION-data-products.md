# Next Session -- data-products

## Next: Cross-dataset reasoning agent test (Phase 4)

Build an agent using `fips-agents create agent` that connects to the
RetrievalHub MCP server and test whether it naturally discovers and
combines the right sources across 2 domains (clinical + aviation) without
being told which datasets to use. The agent uses the Anthropic API with
Sonnet. The deliverable is lab notes documenting what prompting patterns
work, what fails, and how the findings compare with the CDC project's
structured scope signals approach.

1. **Scaffold the agent with fips-agents**
   `fips-agents create agent` in a sibling directory (e.g.,
   `retrieval-hub-agent/`). Configure it to connect to the RetrievalHub
   MCP server as its tool source. Use the Anthropic API with Sonnet
   (`claude-sonnet-5` or latest Sonnet) as the LLM backend.

2. **Build a cross-dataset reasoning system prompt**
   Write a system prompt that encourages the agent to use `list_sources`
   to discover available data, then `retrieve` from the appropriate
   source(s). The prompt should NOT name specific datasets or solutions.
   The goal is to see if the agent can figure out the right sources from
   their descriptions alone. Store the prompt in YAML format under
   `prompts/` per project conventions.

3. **Run the 10 cross-dataset eval questions**
   Both QA datasets include cross-dataset questions: 5 from
   `eval/pubmed_hypertension/qa_dataset.json` and 5 from
   `eval/aircraft_maintenance/qa_dataset.json`. Run each through the
   agent and record: which sources it queried, whether it synthesized
   across them, and answer quality (manual scoring on a 1-5 scale).

4. **Ad-hoc probes for edge cases**
   Test queries that should NOT cross domains ("What is SB 1197E?" is
   aviation-only), queries that span both clinical sources (VA CPG +
   PubMed hypertension), and ambiguous queries where domain selection
   matters. Record the agent's source selection behavior.

5. **Iterate on the system prompt**
   Based on failures from steps 3-4, refine the prompt. Track each
   iteration: what changed, what improved, what regressed. The iteration
   log is part of the lab notes.

6. **Lab notes: cross-dataset reasoning patterns**
   Write `eval/cross_dataset_reasoning/LAB_NOTES.md` covering:
   - System prompt patterns that work vs fail
   - How the agent discovers complementary sources
   - Source selection accuracy (correct domain, correct source within domain)
   - Comparison with the CDC project's approach (structured scope signals
     in source descriptions vs system prompt engineering)
   - Whether #34 (multi-source search tool) is actually needed, or if
     agent discipline suffices at the 3-source scale

**Session start protocol:**
- Premise checks (~10 min):
  - Verify the MCP server is running and all 3 sources are visible:
    connect via `mcp-test-mcp` or `curl` and call `list_sources`.
    Expected: `va-cpg-clinical-guidelines`, `pubmed-hypertension`,
    `aircraft-maintenance`.
  - Verify Anthropic API key is set (`echo $ANTHROPIC_API_KEY | head -c 10`)
  - Verify `fips-agents` is installed and has the `agent` template
  - Read the CDC cross-dataset evaluation notes if available
    (`MCP/CDC/data-acceptance-testing`) for comparison context
  - `git status` — commit any uncommitted files first
- Rules with history:
  - The MCP server endpoint may differ between local dev and cluster.
    Check the route/port before configuring the agent.
  - Use `127.0.0.1` not `localhost` for any local Postgres connections
    (IPv4/IPv6 race condition — see CLAUDE.md).
  - Store prompts in YAML under `prompts/`, not hardcoded in Python.
- Stop-and-ask before: modifying the MCP server code or any production
  data source registrations. This session is testing agent behavior, not
  changing the platform.
- Close ritual: session summary, update this file, update eval register

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

### Phase 4: Cross-dataset reasoning agent test + lab notes [NEXT]

Test whether a well-prompted agent naturally discovers and combines VA CPG,
pubmed-hypertension, and aircraft-maintenance sources without being told
which datasets to use. Agent built with `fips-agents`, using Anthropic API
with Sonnet.

**Definition of done:** Agent successfully discovers relevant sources,
queries each independently, and synthesizes across results. Documented
system prompt patterns that work and patterns that fail.

**Dependencies:** Phase 3 (done)

### Phase 5: Data owner onboarding path + lab notes

Distill the onboarding process into something a domain expert (non-AI
engineer) could follow.

**Definition of done:** A domain expert could reasonably follow the
process from data to serving agents, documented with evidence of what
works and what gaps remain.

**Dependencies:** Phases 2 + 3 (done)

**Parallel-ok:** Yes, could run in parallel with Phase 4.

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

## What landed last session (2026-08-21)

See `session-summaries/2026-08-21-data-products-ragas-aircraft.md`.

Phase 3 completed: aircraft chunking sweep (TF-512-0 wins, 0.950 hit_rate,
0.749 MRR), Ragas answer-quality confirmed, production re-ingested on
cluster, cross-domain comparison lab notes written. Commits: 0495a7e..63e6985.

Parallel session completed sweep and production re-ingestion (d3d948a),
IPv4/IPv6 fix (8d9209f). Closed #36 (Ragas validation).

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
