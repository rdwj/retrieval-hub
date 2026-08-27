# Next Session -- Self-Serve Onboarding

## Epic: Auth, AutoRAG-style Onboarding, and New Data Families

Build the auth layer, a self-serve source onboarding pipeline, and onboard
new datasets that exercise the four unrepresented source families (tabular,
graph, process, external). The self-serve pipeline replaces the idea of
adopting an external AutoRAG framework by wrapping our own eval sweep
infrastructure into an onboarding workflow.

### Phase 1: Auth -- MCP server integration

Wire the existing `retrieval-hub-auth` service into the MCP server so
that every retrieve/refine/describe_source call requires a valid JWT and
enforces the `Source.access` policy.

**What exists:**
- `retrieval-hub-auth/` is a complete peer component with FastAPI, local
  IdP backend, key rotation, token issuer/validator, and 11 test files.
- `docs/auth.md` is a thorough design doc (OAuth 2.1, JWT shape, pluggable
  backends, source-level access control).
- `Source.access` JSON column exists in the data model.
- No auth middleware exists yet in the MCP server.

**Work:**
1. Add JWT validation middleware to the MCP server. FastMCP 4.0b1 is our
   current version; verify its auth middleware API or use a thin FastAPI
   dependency-injection layer. The MCP server validates JWTs locally via
   JWKS fetched from `retrieval-hub-auth`.
2. Enforce `Source.access` policy in the core retrieval path. When a
   source has `access.visibility = "restricted"`, check the caller's
   `rh_groups` claim against `access.allowed_groups`. Return a clear
   error (not empty results) when denied.
3. Implement the `request_access` MCP tool. Returns a structured response
   explaining how to request access (contact info, approval workflow).
4. Deploy `retrieval-hub-auth` to the cluster alongside the MCP server.
5. Update `retrieval-hub-mcp/openshift.yaml` with the JWKS endpoint
   config and auth env vars.
6. Add integration tests: authed retrieve succeeds, unauthed retrieve
   returns 401, restricted source returns 403 for wrong group, request_access
   returns the right guidance.

**Definition of done:** MCP server rejects unauthenticated calls. Sources
with `access.visibility = "restricted"` are enforced. `request_access` tool
works. Existing sources remain accessible to any authenticated caller
(default open policy). Auth service deployed on cluster.

**Dependencies:** None. This unblocks everything else.

**Issues:** #30 (MCP server auth), #24 (Keycloak example, stretch goal)

---

### Phase 2: Self-serve onboarding pipeline

Build a CLI command that takes raw data and a minimal config, runs a
parameter sweep, and produces a fully onboarded source with eval baseline.
This replaces the external AutoRAG idea by wrapping our existing tools.

**What exists:**
- `scripts/new_source.py` scaffolds ingestion scripts (643 lines, template-
  based, supports document/clinical_document/technical_document families).
- `scripts/generate_qa_pairs.py` generates QA pairs using gpt-oss-120b
  (currently hardcoded to VA CPG corpus).
- `scripts/eval_answer_quality.py` runs Ragas eval with checkpoint/resume
  (currently hardcoded to va-cpg source).
- `retrieval-hub-evalhub/` packages the eval pipeline as OpenShift Jobs
  with parameterized inputs.
- Six existing ingestion scripts follow a common pattern: normalize docs,
  chunk, create Source, build index, register recipe.

**Work:**
1. **Generalize generate_qa_pairs.py.** Make it source-agnostic: accept
   `--source-slug`, `--data-dir`, `--family` and derive the generation
   targets from the data files rather than a hardcoded list. Keep the
   gpt-oss-120b scoring LLM.
2. **Generalize eval_answer_quality.py.** Replace hardcoded source slug
   and keyword maps with CLI parameters. The eval register already
   supports arbitrary suite names.
3. **Build `scripts/onboard_source.py`.** Single entry point that chains:
   a. Validate inputs (data dir, slug, family, name, description).
   b. Scaffold the ingestion script via `new_source.py` (or use a
      generic ingestion path for standard families).
   c. Run ingestion with 2-3 candidate chunk configs (e.g., 256/0,
      512/0, 512/64 for document families).
   d. Generate QA pairs from the data (10-20 pairs for a quick sweep).
   e. Run eval on each candidate config.
   f. Select the Pareto-optimal config (best answer_relevancy with
      acceptable faithfulness).
   g. Drop non-winning indexes, promote the winning config.
   h. Register the source as CURATED with the winning recipe and
      eval baseline on the data card.
   Output: a summary of what was tried, what won, and why.
4. **EvalHub integration.** Package the sweep as an EvalHub task so data
   owners can run the sweep on the cluster rather than locally. This
   overlaps with eval-convergence Phase 2.
5. **Data card auto-population.** The onboarding pipeline writes initial
   `describe_source` metadata: document count, chunk count, embedding
   model, chunk config, eval baseline scores, data freshness date.

**Definition of done:** A data owner can run
`python scripts/onboard_source.py --slug my-source --data-dir ./my-data/ --family document`
and get a fully registered, eval-baselined source. Tested with at least one
new dataset from Phase 3.

**Dependencies:** Phase 1 (auth should be in place before onboarding
sources that may need access control). The pipeline itself doesn't require
auth, but the sequencing ensures new sources are protected from day one.

---

### Phase 3: New datasets for unrepresented families

Onboard new data sources that exercise the four families with no examples:
`tabular`, `graph`, `process`, `external`. Use the self-serve pipeline
from Phase 2 where possible; where a family needs a new adapter, build it.

Each dataset lives in `/Users/wjackson/Developer/retrieval-hub-data-sources/`.

#### 3a. Tabular -- ClinicalTrials.gov dataset

A CSV/structured dataset of clinical trial records. Tests columnar
retrieval where the "document" is a row with typed fields, not prose.

**Work:**
1. Download a public ClinicalTrials.gov extract (e.g., trials related
   to hypertension or PTSD to complement the VA CPG source).
2. Build a `TabularAdapter` in the retrieval path. Tabular retrieval
   likely needs field-aware chunking: each row becomes a chunk, with
   column names as metadata. Or: natural-language rendering of each
   row for embedding, with structured fields preserved as metadata
   for filtering.
3. Write `scripts/ingest_clinical_trials.py` (or generate via the
   onboarding pipeline).
4. Add to `new_source.py` template support for `--family tabular`.
5. Generate QA pairs and run eval.

**Adapter design questions (resolve before implementation):**
- Row-per-chunk vs. group-of-rows-per-chunk?
- Should the retrieve tool support structured filters (e.g.,
  `phase = "Phase 3"`) or is semantic search over rendered text enough?
- How does `refine` work on tabular data? Adjacent rows? Same-column
  drill-down?

#### 3b. Process -- Aircraft maintenance procedures

Re-model the existing Piper SB data as structured procedures (step
sequences) rather than flat documents. This tests procedure/workflow
retrieval where ordering and dependencies matter.

**Work:**
1. Parse existing aircraft maintenance SBs to extract procedure steps
   (many SBs have numbered step lists). Store as structured JSON with
   step ordering preserved.
2. Build a `ProcessAdapter`. Process retrieval should return the
   procedure context around a matching step, not just the matching
   chunk. The `refine` entity-arc strategy may work here, treating
   the procedure as the "entity."
3. Write `scripts/ingest_aircraft_procedures.py`.
4. Add to `new_source.py` template support for `--family process`.
5. Generate QA pairs focused on "how do I do X" procedural questions.

**Note:** The raw data already exists in `retrieval-hub-data-sources/
aircraft-maintenance/`. This is a re-modeling exercise, not a new data
acquisition.

#### 3c. Graph -- SNOMED-CT subset or codebase dependency graph

A knowledge graph where entities have typed relationships. Tests
retrieval over structured relationships rather than prose.

**Work:**
1. Pick a dataset. Options:
   - SNOMED-CT concept subset (clinical, complements VA CPGs)
   - A dependency graph extracted from a public codebase
   - DBpedia/Wikidata subset on a focused topic
2. Build a `GraphAdapter`. Graph retrieval likely combines text search
   (entity descriptions) with relationship traversal. The `refine`
   cross_reference strategy is close to what's needed here.
3. Design the chunk representation: each entity as a chunk with
   relationship metadata? Or each relationship as a chunk?
4. Write the ingestion script.
5. Generate QA pairs that require multi-hop reasoning.

**Design consideration:** This is the most architecturally novel family.
May warrant a spike/prototype before committing to a full implementation.

#### 3d. External -- Federation to a public API

A source that proxies retrieval to an external system rather than
hosting its own embeddings. Tests the federation pattern.

**Work:**
1. Pick a target. Options:
   - A second RetrievalHub instance (self-federation for testing)
   - PubMed API (real external clinical data source)
   - A public embedding search API
2. Build an `ExternalAdapter`. The adapter translates retrieve/refine
   calls into the target system's API. No local embeddings, no local
   chunks, just a proxy.
3. The source catalog entry stores connection config (endpoint, auth)
   instead of a recipe.
4. Score normalization: external scores are on a different scale.
   Define a normalization contract for federated sources.
5. Works with multi-source retrieve (#34) -- an external source
   participates in RRF alongside local sources.

**Design consideration:** This is more of an integration pattern than a
data type. Simplest version: a source whose adapter makes HTTP calls
instead of pgvector queries.

**Sequencing within Phase 3:**
- 3a (tabular) and 3b (process) first -- highest value, clearest path
- 3c (graph) next -- most architecturally novel, may need a spike
- 3d (external) last -- integration pattern, less about data shape

**Definition of done:** At least three of the four families have a live
source with eval baseline. Each new adapter is wired into the retrieval
factory. The onboarding pipeline successfully onboards at least one of
these sources end-to-end.

**Dependencies:** Phase 2 (onboarding pipeline for dog-fooding). Phase 1
(auth for any restricted sources, though these public datasets don't need
it).

---

## Cross-cutting concerns

- **Eval pipeline generalization** overlaps with eval-convergence Phase 2
  (EvalHub integration). Coordinate: the generalized eval scripts serve
  both the onboarding pipeline and the EvalHub sweeps.
- **Multi-source retrieve** (#34, shipped) makes the new sources
  immediately useful in cross-dataset queries once onboarded.
- **Elicitation** (#29) remains a future epic. The onboarding pipeline
  doesn't need it, but it would improve the agent experience for new
  sources with unfamiliar vocabularies.
- **Retrieval adapter factory** at `src/retrieval_hub/retrieval/api.py`
  currently maps most families to `DocumentAdapter`. New families need
  new adapters registered there.

## Issues this epic addresses

- #30 MCP server authentication and per-source authorization (Phase 1)
- #24 Keycloak realm and role allowlist example (Phase 1 stretch)
- #27 Production ingestion runners (Phase 2, via EvalHub packaging)
- #16 Wikipedia subset and public code repositories (partially, via
  Phase 3 datasets)

## Issues this epic does NOT address

- #31 MCP-level end-to-end eval (eval-convergence epic)
- #29 Elicitation for low-confidence results (future epic)
- #25 Operator with CRDs (future)
- #23 Grafana dashboard (future)
- #17 SDK / #18 CLI (future)

---

## What this covers (and what it doesn't)

**In scope:**
- Auth service deployment and MCP server integration
- Source-level access control enforcement
- Self-serve onboarding CLI pipeline
- QA generation and eval generalization (source-agnostic)
- New data sources for tabular, process, graph, external families
- New retrieval adapters for each family
- Data card auto-population from onboarding

**Out of scope (other epics own):**
- Eval-convergence remaining phases (EvalHub integration, leaderboards)
- Refine tool improvements
- Elicitation (#29)
- Operator/CRDs (#25)
- SDK/CLI (#17, #18)
- Fine-tuning / model training
