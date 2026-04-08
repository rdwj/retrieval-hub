# Query Rewriter

The query rewriter is the part of retrieval-hub that's actually new. Everything else — a catalog of sources, an MCP surface, an admin UI, OAuth — exists somewhere already, and we are following well-trodden patterns. The query rewriter is the bet that says: **the knowledge of how to ask a particular knowledge set a good question should live next to the knowledge set, not inside every agent that tries to use it.**

This document describes that bet: the thesis, the architecture (one shared rewriter + per-source metadata, with optional overrides), the I/O contract, the lifecycle of rewriter metadata, the LLM resolution policy, the latency posture, and how the VA clinical practice guidelines source acts as the canonical proving ground.

It does not specify the MCP tool the rewriter is exposed through — that's a `plan-tools` question, see [`mcp-server.md`](mcp-server.md). This doc describes the *capability*; the tool surface that wraps it comes later.

## The thesis

Today's RAG pipelines almost always do query rewriting *inside the agent*: the agent is given some scaffolding ("rephrase the user's question to be a better search query") and produces a query it then sends to a retrieval call. This works, kind of. Three things go wrong:

1. **The agent doesn't know what the corpus looks like.** It's rewriting blind. It can produce reasonable English-language paraphrases but it can't reformulate "blood sugar after a meal" into "postprandial hyperglycemia management" without prior knowledge of the clinical-document vocabulary, and that knowledge is not in the agent's prompt.
2. **Every team rewrites query-rewriting.** It's a recurring chunk of agent prompt engineering that gets reinvented in every project, with no shared baseline.
3. **The signal that would improve the rewrite — "what answers actually came back well from this corpus historically" — lives next to the data, not next to the agent.** The agent has no way to use it.

retrieval-hub flips this: the **source owner** declares metadata describing what their corpus looks like — vocabulary mappings, sample queries, domain notes, schema hints — and a **shared core rewriter** uses that metadata to reformulate queries against the source. The source owner doesn't author a bespoke rewrite prompt from scratch; they declare facts about their corpus, and the shared rewriter does the prompt engineering.

This is the architecturally important part. An earlier draft of this doc had each source carrying its own hand-written rewrite prompt as a property. That bar is too high — most source owners would never invest in writing a prompt, and the differentiator would only show up on a handful of premium sources. The metadata-driven approach lowers the bar dramatically: declare your vocabulary, declare a few sample queries, and you have a working rewriter for your source. The override path still exists for the rare cases where the shared core isn't enough.

## How it's built: shared core + source metadata

There is **one** rewriter prompt template — the "shared core" — and it lives in the core library next to the rewriter service. It is a carefully-engineered prompt that takes a structured payload of source metadata and a raw user query, and produces N reformulated queries with intent annotations.

Each source contributes a **`rewriter_metadata`** record that gets injected into the shared template at call time. The metadata fields, defined in [`catalog.md`](catalog.md):

- **`vocabulary_mappings`** — pairs of `(lay_term, canonical_term)`. The shared rewriter uses these to translate user phrasing into corpus phrasing. For VA clinical guidelines this is heavy: lay-language → clinical-language, acronym expansion, common patient phrasings. For Red Hat docs it's lighter: a few product-name canonicalizations.
- **`domain_notes`** — a short markdown blob describing what kind of content the source holds and how queries against it should be phrased. Think "the README for a query author." This is what gives the shared rewriter situational awareness.
- **`sample_queries`** — a small set of `(raw_query, good_rewrites)` examples. The shared rewriter uses these as few-shot examples in the rendered template. This is the lowest-effort way for a source owner to *shape* the rewriter's behavior.
- **`schema_hints`** — for `tabular` family sources, a structured schema description.

At call time, the rewriter:

1. Loads the source and its `rewriter_metadata`.
2. Renders the shared template, injecting the vocabulary mappings as a structured table, the domain notes as a context block, and the sample queries as few-shot examples.
3. Calls the configured LLM with the rendered prompt and the user's raw query.
4. Validates the LLM response against the structured output schema.
5. Returns the rewrites with lineage fields.

The shared template is **versioned**. Where it lives depends on the cluster configuration:

- **When MLflow is present** (production default — see [`integrations/mlflow.md`](integrations/mlflow.md)), the shared template lives as an MLflow prompt registry entry under the name `rh.rewriter.shared-core`. Versioning, tagging, comparison, and rollback all flow through MLflow's prompt registry UI. retrieval-hub keeps the *active version pointer* in its own configuration so the hot-path rewriter does not call MLflow on every rewrite — it caches the active template at startup and refreshes periodically. When the active version is bumped in MLflow, the cache picks up the new version on its next refresh (or immediately on a configuration reload).
- **When MLflow is absent** (standalone fallback), the shared template ships as a versioned artifact in the core library — a Python file or YAML in `src/retrieval_hub/rewriter/templates/` with a version constant. Bumping the version is a code change reviewed in the normal way.

In either case, the rewrite result's lineage field carries the **active template version** (`shared_template_version: 7`). When MLflow is the source of truth, this is the MLflow prompt version id. When the core library is the source of truth, it's the source-controlled version constant. Either way, agents and audit can resolve "which template version produced this rewrite" unambiguously.

Sources can pin to a specific shared-template version if they need to (rarely needed in v1), but the default is "use the current active version."

A source's `rewriter_metadata` is **versioned independently** from the recipe. The owner can iterate on vocabulary mappings without bumping the recipe version, because changing the rewriter doesn't change how the data was indexed. The metadata itself stays in retrieval-hub Postgres regardless of MLflow availability — it's strongly typed (vocabulary mappings, sample queries, schema hints), has a typed editor in the admin UI, and is on the hot path. MLflow's prompt registry is for free-text prompts; rewriter metadata is structured.

## The optional override path

There are sources where the shared rewriter, even with carefully-tuned metadata, isn't enough. For those, a source can carry a **`prompt_override_id`** referencing a custom rewriter prompt object that *replaces* the shared template entirely for this source.

Override prompts are used as the **exception**, not the default. They exist for cases where the source's domain is so specialized that the shared template's framing is wrong (e.g. a code retrieval source where the rewriter needs to think in terms of symbol names and call graphs instead of natural language). They follow the same storage pattern as the shared template: when MLflow is present, they live as named entries in the MLflow prompt registry (with a `rh.rewriter.override.<slug>` naming convention) and the catalog's `prompt_override_id` references the MLflow prompt name. When MLflow is absent, they live as catalog objects in retrieval-hub Postgres with their own version history. They are versioned, named, owned, and auditable in either case.

The decision tree for a source owner who wants better rewriting on their source:

1. Add `vocabulary_mappings`. This handles 80% of the wins.
2. Add `sample_queries` for the most common question types. This handles another 15%.
3. Add `domain_notes` for situational guidance.
4. Iterate on (1)–(3) and run the test suite (see Author-test loop below).
5. **Only if the shared rewriter is genuinely producing wrong output**, write an override prompt. This is the escape hatch, not the happy path.

By construction, most sources should never reach step 5. If they do, it's a signal that either the shared template needs improvement (which benefits everyone) or this source is a true edge case.

## What it does, concretely

Given:
- A `source_id` (must be `Published` and have `rewriter_metadata.enabled = true`)
- A `raw_query` (the user's actual question, in their actual phrasing)
- Optional `context` (recent conversation turns, agent identity, tenant, etc.)
- Optional `caller_llm` (overrides the cluster default — see "LLM resolution" below)

Returns:
- A list of 1 to `rewriter_metadata.max_rewrites` `rewritten_queries`, each with:
  - The reformulated query text
  - A short `intent` annotation (what this particular rewrite is *trying* to retrieve — "definition," "guideline reference," "specific procedure," etc.)
  - A `rationale` (why the rewriter chose this reformulation, primarily for debuggability)
  - An optional `confidence` score
- The `shared_template_version` and `metadata_version` used to produce the rewrites (lineage)
- The `llm` actually used (lineage)
- A `request_id` for tracing

The agent is free to use one rewrite, all of them, or any subset. The point is *options*. A common pattern will be: union the retrieval hits across all rewrites, deduplicate, rerank — and that pattern works regardless of which agent runtime is doing the orchestration.

## The canonical example: VA clinical practice guidelines

A user types into a chat interface: *"what should I do for someone with high blood sugar after a meal?"*

A naive RAG pipeline embeds that string and searches. The corpus — VA clinical practice guidelines, written in clinical English — does not use the phrase "high blood sugar after a meal" anywhere. Recall is poor.

The VA source's owner has declared `rewriter_metadata` with heavy vocabulary mappings:

```yaml
rewriter_metadata:
  enabled: true
  vocabulary_mappings:
    - lay: "high blood sugar"
      canonical: "hyperglycemia"
      qualifiers: ["postprandial", "fasting", "random"]
    - lay: "blood sugar after a meal"
      canonical: "postprandial glucose"
    - lay: "blood pressure"
      canonical: "hypertension"
      qualifiers: ["essential", "secondary", "stage 1", "stage 2"]
    # ... ~50 more
  domain_notes: |
    VA/DoD clinical practice guidelines. Prefer the official guideline
    title prefix when reformulating for guideline-reference queries.
    Recognize patient-language descriptions of common chronic conditions.
  sample_queries:
    - raw: "what's the target blood pressure for someone with diabetes"
      good_rewrites:
        - "VA/DoD clinical practice guideline blood pressure target diabetes mellitus"
        - "hypertension management diabetes type 2 target systolic"
  prompt_override_id: null         # uses the shared core rewriter
  llm_resolution: default
  default_llm: granite-3.3-8b-instruct
  max_rewrites: 5
```

When the agent submits the raw question, the shared rewriter — fed this metadata — produces something like:

```yaml
rewritten_queries:
  - text: "VA/DoD clinical practice guideline postprandial hyperglycemia management"
    intent: "guideline_reference"
    rationale: "Lay phrase 'high blood sugar after a meal' maps to clinical term 'postprandial hyperglycemia.' Source's domain_notes prefer guideline-title prefixes for guideline-reference queries."
    confidence: 0.92
  - text: "type 2 diabetes mellitus postprandial glucose treatment recommendation"
    intent: "treatment_recommendation"
    rationale: "Most likely underlying condition; vocabulary mapping for 'high blood sugar' qualified to 'postprandial glucose' from sample_queries."
    confidence: 0.78
  - text: "insulin therapy postprandial glucose elevation"
    intent: "specific_intervention"
    rationale: "Common targeted intervention; allows retrieval of intervention-specific sections."
    confidence: 0.61
shared_template_version: 7
metadata_version: 4
llm: granite-3.3-8b-instruct
```

The agent unions retrieval against these three queries, gets three different (but overlapping) sets of clinical sections back, deduplicates, and answers the user with citations. The agent itself never had to know what "postprandial" means. The VA source's owner — who understands clinical vocabulary — encoded that knowledge once, as metadata declarations, and every agent that uses this source benefits forever.

This is not a hypothetical. It's the example we are building toward, and the v0 success criterion for the rewriter is: *on the VA source, queries with rewriting enabled outperform queries without rewriting on a measurable eval, and the gap is large enough that nobody who uses the source would turn it off.* If we can't show that, the differentiator isn't real.

## LLM resolution

The rewriter needs an LLM. There are three modes for which one to use, and the round-1 default is **both, with cluster-resident as the default**:

| Source `rewriter_metadata.llm_resolution` | Behavior |
|---|---|
| `default` | Use the source's `default_llm`, served by the cluster vLLM. Caller is not required to supply credentials. |
| `caller_optional` | Use the caller's LLM if they pass one; otherwise fall back to the source's `default_llm`. |
| `caller_required` | Use the caller's LLM. Fail with `caller_llm_required` if they didn't pass one. |

The rationale for `caller_required` exists for sources where the rewriter prompt is *deliberately* compute-heavy (long context, large model) and the source owner doesn't want retrieval-hub to absorb that cost — they want the calling agent's billing relationship to pay for it. We do not expect this to be common in v1.

The cluster default LLM is **`granite-3.3-8b-instruct`**, served by the cluster's vLLM. It is small on purpose: rewriting is a hot-path operation that needs to fit inside the agent's per-turn latency budget, and a 70B model breaks that budget. If a particular source's metadata renders into a prompt that's too rich for an 8B model to handle well, the right answer is to (a) trim the metadata, (b) split into multiple narrower sources, or (c) opt that source into a `caller_required` configuration with a larger model — not to bump the cluster default for everyone.

The caller-supplied path takes credentials in a structured way through the tool input — exact shape will be defined when `plan-tools` runs. The rewriter never logs caller credentials and never persists them.

## Latency posture

The rewriter is on the **hot path** of every agent turn that uses it, which means latency budget is real. Round 1 targets:

- p50 end-to-end (MCP entry → rewrites returned): **under 800 ms** with `granite-3.3-8b-instruct`
- p95 end-to-end: **under 2 s**
- The LLM call itself is the dominant cost; everything else (catalog lookup, metadata loading, template rendering, structured output validation) should sum to under 50 ms

These numbers are aspirational, not enforced — they're what we should hold the cluster default LLM choice to. If `granite-3.3-8b-instruct` can't hit p50 under 800 ms on the target cluster's vLLM serving, we either pick a smaller model or trim the shared template's overhead.

A future optimization is **cached rewrites**: if the same raw query has been rewritten against the same source recently, return the cached result. The cache would be keyed by `(source_id, shared_template_version, metadata_version, raw_query, context_hash)`. Round 2.

## How a source owner authors and tests rewriter metadata

The author-test loop has to be tight or nobody will invest in it. The flow we are designing for:

1. **Edit metadata.** Owner opens the source's rewriter metadata editor in the admin UI, adds vocabulary mappings, edits domain notes, adds sample queries. Saves as a new metadata version. The source can be in `Curated` state for this; metadata edits do not require the source to be `Published`.
2. **Test on the spot.** The editor has a "test" affordance where the owner can paste a raw query and see the structured rewrite output, the rendered prompt (so they can see exactly how their metadata is being injected), the LLM used, and the latency. This is one MCP call away — same code path that agents will use.
3. **Run the metadata test suite.** A source's `rewriter_metadata` carries a frozen set of `test_cases` — pairs of `(raw_query, expected_intents_or_coverage)`. The owner runs the suite from the UI or CLI; the rewriter is invoked for each case and the result is scored against the expected coverage. Lightweight harness, not a full eval framework.
4. **Compare against the previous metadata version.** The UI shows a diff: which test cases improved, which regressed, which are unchanged. This is the bar for accepting a new metadata version into production.
5. **Promote.** The owner promotes the new metadata version. The source's `rewriter_metadata.metadata_version` reference picks up the new version; agents calling the rewriter against this source automatically get the new behavior on their next call.
6. **Retrieval-level eval.** Separately, a full retrieval eval runs against the source with rewriting enabled vs. disabled. This is the *real* score that lands on the card. It runs less often (e.g. nightly) and uses the source's eval suite, not the metadata test suite.

Steps 1–4 are the metadata-author loop. Step 6 is the source-eval loop. Both feed into "is the differentiator real for this source." The override prompt path, when needed, has its own author loop modeled on this one but operating against the override prompt object instead of the metadata.

## Where it lives in the code

The rewriter is a service inside the **core library** (`src/retrieval_hub/rewriter/`). Not a separate peer component. Reasons:

- It needs synchronous access to the catalog (load source, load metadata, load eval criteria) and to the same access-control checks the rest of the catalog uses. A peer component would have to re-acquire all of that over the network.
- It is invoked from at least three places: the MCP server (agent path), the admin UI (test affordance), and the CLI (`retrieval-hub rewriter test ...`). All of those already import the core library, so having the rewriter as a core-lib module gives all three a single code path.
- The cost of the LLM call dominates anyway. Splitting it into its own deployable buys nothing.
- The shared template lives next to the rewriter code, so it ships and versions with the rest of the core library.

The rewriter takes an LLM client as a constructor argument (dependency injection), which is what makes the cluster-default vs. caller-supplied resolution possible: the MCP layer constructs the right LLM client based on the request and passes it in. The rewriter itself doesn't know about credentials.

## What's Decided

- **The rewriter is shared core + source metadata**, not bespoke per-source prompts. Each source contributes vocabulary mappings, domain notes, and sample queries; the shared template handles the prompt engineering.
- **The shared template is part of the core library**, versioned and reviewed like any other code.
- **`rewriter_metadata` is versioned independently from the recipe**, because changing the rewriter doesn't change how the data was indexed.
- **An override prompt path exists** as an escape hatch (`prompt_override_id`), but it's the exception, not the default.
- **LLM resolution is `default | caller_optional | caller_required`**, with `default` (cluster-resident) as the round-1 normal case.
- **The cluster default LLM is `granite-3.3-8b-instruct`**, served by the cluster's vLLM.
- **The output is structured**: list of `(text, intent, rationale, confidence)` plus lineage fields. No free-form text.
- **The rewriter lives in the core library**, not as a peer component.
- **Latency targets**: p50 under 800ms, p95 under 2s with the default LLM. They decide model size.
- **The VA clinical practice guidelines source is the proving ground.** If the rewriter doesn't measurably win there with declarative metadata, the differentiator isn't real and we have to rethink it.

## What's Open

- **How rich the shared template can be before it bloats.** The metadata for VA will be substantial; rendered into a prompt, it might push the context window of an 8B model harder than is comfortable. We need to measure on real metadata and on real corpora before locking the template's structure.
- **Whether the shared template is one template or one-per-family.** Round 1 leans toward one template that branches on `source.family` inside its rendering, but a small set of family-specific templates might end up cleaner. Test against `clinical_document` and `code` before committing.
- **Caching.** Round 2.
- **The exact `vocabulary_mappings` data structure.** Today it's `(lay, canonical, qualifiers)`. Real clinical vocabulary mapping is messier — synonyms, hierarchical relationships, ICD/SNOMED codes. The structure may need to grow, possibly with a separate per-source mapping object that the metadata references.
- **How rewrite results compose with cross-source search.** If an agent is querying three sources and only one has rewriting enabled, what's the right behavior? Probably "only that one gets rewritten and the others get the raw query," but it deserves a real answer once cross-source tools are designed.
- **Eval framework integration.** The retrieval-level eval (step 6 above) needs an eval framework. SDG Hub is the working assumption but not committed. See [`evaluation.md`](evaluation.md).
- **Output schema versioning.** `output_schema_id: rewrite_v1` implies there will be a `rewrite_v2`. We should commit to the v1 shape when `plan-tools` runs and treat schema bumps as a real lifecycle event.
