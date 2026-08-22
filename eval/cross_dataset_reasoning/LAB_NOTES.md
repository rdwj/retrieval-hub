# Cross-Dataset Reasoning: Lab Notes

Phase 4 of the data-products epic. Tests whether a well-prompted agent
discovers and combines the right data sources from catalog descriptions
alone, without domain-specific instructions.

## Setup

- **Agent**: Anthropic API with Claude Sonnet 5, no temperature control
  (Sonnet 5 does not support the parameter)
- **System prompt**: Domain-agnostic, instructs the agent to call
  `list_sources`, read descriptions, select sources, retrieve, synthesize
- **MCP server**: RetrievalHub local instance at `127.0.0.1:8000/mcp`
- **Sources (3)**:
  - `va-cpg-clinical-guidelines` — 52 VA/DoD clinical practice guidelines
  - `pubmed-hypertension` — 10 PubMed Central review articles on
    hypertension management
  - `aircraft-maintenance` — 269 Piper Aircraft service bulletins
- **Eval harness**: `scripts/eval_cross_dataset_agent.py` — calls
  Anthropic Messages API with tool definitions, proxies tool calls to
  MCP server, records every tool invocation and computes source
  selection metrics
- **Question set**: 20 questions in three categories:
  - 10 cross-dataset (require 2+ sources)
  - 5 single-source controls (should use exactly 1 source)
  - 5 ad-hoc probes (edge cases: ambiguous, out-of-scope, misleading
    terminology)

## Scoring

Source selection is scored automatically on three metrics:
- **Precision**: fraction of queried sources that were expected
- **Recall**: fraction of expected sources that were queried
- **Exact match**: queried source set == expected source set

## Iteration 0: Baseline (v0)

**Run**: `v0-baseline` | **Prompt**: `prompts/v0.yaml`

**Hypothesis**: A minimal domain-agnostic prompt with instructions to
discover sources via `list_sources` and select based on descriptions
will achieve reasonable source selection.

### Results

| Category | n | Precision | Recall | Exact Match |
|---|---|---|---|---|
| cross-dataset | 10 | 0.900 | 0.900 | 0.500 |
| single-source-control | 5 | 0.700 | 1.000 | 0.400 |
| ad-hoc-probe | 5 | 0.933 | 1.000 | 0.800 |
| **Overall** | **20** | **0.858** | **0.950** | **0.550** |

Tokens: 722K input / 41K output. Avg 4.05 iterations per question.
Wall time: 687s (~11.5 min).

### Observations

**Recall is excellent.** The agent almost always queries sources that
are genuinely relevant (0.95 overall). It correctly identifies which
domain a question belongs to.

**Precision suffers from clinical source conflation.** The dominant
failure pattern: the agent queries BOTH `va-cpg-clinical-guidelines`
and `pubmed-hypertension` for every clinical question, even when only
one is relevant. This caused failures on all three clinical
single-source controls and inflated the source set on three
aviation+clinical cross-dataset questions (am-021, am-023, am-024).

This behavior is understandable given the source descriptions: both
explicitly mention hypertension management. The short descriptions
differentiate them as "clinical practice guidelines" vs "review articles
from PubMed Central", but the agent doesn't leverage this distinction
to make targeted selections.

**Missed cross-domain bridges (minor).** Two aviation-framed questions
(am-022 about occupational health precautions for mechanics using
solvents, am-025 about fatigue and adherence to inspection schedules)
were routed only to aircraft-maintenance, missing the clinical
relevance of "occupational health" and "adherence."

**Perfect behaviors:**
- All 5 purely clinical cross-dataset questions: exact match (5/5)
- Both aviation single-source controls: exact match (2/2)
- Out-of-scope question (ad-hoc-004): correctly queried nothing
- Clinical-sounding aviation question (ad-hoc-001): correctly routed
  to aircraft-maintenance only
- Aviation-terminology health question (ad-hoc-005): correctly routed
  to both clinical sources

### Per-question breakdown

| ID | Expected | Queried | Match |
|---|---|---|---|
| xds001-005 | va-cpg + pubmed | va-cpg + pubmed | 5/5 |
| am-021 | aircraft + va-cpg | aircraft + pubmed + va-cpg | N (extra) |
| am-022 | aircraft + pubmed | aircraft | N (missed) |
| am-023 | aircraft + pubmed | aircraft + pubmed + va-cpg | N (extra) |
| am-024 | aircraft + pubmed | aircraft + pubmed + va-cpg | N (extra) |
| am-025 | aircraft + pubmed | aircraft | N (missed) |
| ctrl-001,002 | aircraft | aircraft | 2/2 |
| ctrl-003 | pubmed | pubmed + va-cpg | N (extra) |
| ctrl-004 | pubmed | pubmed + va-cpg | N (extra) |
| ctrl-005 | va-cpg | pubmed + va-cpg | N (extra) |
| ad-hoc-001 | aircraft | aircraft | Y |
| ad-hoc-002 | va-cpg + pubmed | va-cpg + pubmed | Y |
| ad-hoc-003 | aircraft + pubmed | aircraft + pubmed + va-cpg | N (extra) |
| ad-hoc-004 | (none) | (none) | Y |
| ad-hoc-005 | va-cpg + pubmed | va-cpg + pubmed | Y |

## Iteration 1: Source disambiguation (v1)

**Run**: `v1-disambiguate` | **Prompt**: `prompts/v1.yaml`

**Hypothesis**: Clinical conflation is caused by description overlap.
Adding guidance to use `describe_source` for disambiguation and to
consider whether multi-source querying is truly warranted will improve
precision without hurting recall.

**Changes from v0:**
1. Made `describe_source` prescriptive when sources overlap ("When two
   or more sources cover similar domains, call `describe_source` on
   each before selecting")
2. Added single-vs-multi-source guidance ("Not every question touching
   a domain needs every source in that domain")
3. Added secondary domain signal detection ("Scan for terms that map
   to a second domain")

### Results

| Category | n | Precision | Recall | Exact Match |
|---|---|---|---|---|
| cross-dataset | 10 | 0.917 | 0.850 | 0.600 |
| single-source-control | 5 | 0.600 | 0.800 | 0.400 |
| ad-hoc-probe | 5 | 0.933 | 0.800 | 0.600 |
| **Overall** | **20** | **0.842** | **0.825** | **0.550** |

Tokens: 779K input / 43K output. Avg 4.55 iterations per question.
Wall time: 703s (~11.7 min).

### Comparison with v0

| Metric | v0 | v1 | Delta |
|---|---|---|---|
| Precision | 0.858 | 0.842 | -0.016 |
| Recall | 0.950 | 0.825 | **-0.125** |
| Exact Match | 0.550 | 0.550 | 0.000 |
| Avg Iterations | 4.05 | 4.55 | +0.50 |
| Input Tokens | 722K | 779K | +57K |

**Hypothesis rejected.** The disambiguation guidance did not improve
exact match (still 0.55) and significantly hurt recall (-12.5 points).
The agent became more cautious but not more accurate.

### What changed per-question

| ID | v0 | v1 | Assessment |
|---|---|---|---|
| am-021 | N (extra: all 3) | **Y** (aircraft + va-cpg) | Improved: stopped over-querying |
| am-023 | N (extra: all 3) | N (wrong: va-cpg not pubmed) | Changed: swapped clinical source |
| ctrl-005 | N (extra: both clinical) | N (pubmed only, should be va-cpg) | **Regressed**: picked wrong source |
| ad-hoc-005 | Y (both clinical) | **N** (queried nothing) | **Regressed**: declined to query |

All other questions unchanged from v0.

### Analysis

The disambiguation guidance created a precision/recall tradeoff that
netted to zero. The agent now sometimes correctly narrows to fewer
sources (am-021 improved) but also sometimes overshoots the narrowing
(ad-hoc-005 queried nothing, ctrl-005 picked the wrong single source).

The clinical conflation on ctrl-003 and ctrl-004 persisted — even
with explicit guidance to consider whether multi-source querying is
warranted, the agent still queries both clinical sources for
hypertension questions. This confirms that the overlap in source
descriptions is the root cause, not the prompt's selectivity guidance.

The `describe_source` calls increased token usage (+57K) and iteration
count (+0.45) without improving accuracy. This suggests that
within-domain disambiguation via `describe_source` is not an effective
strategy at the description level — the full descriptions still
overlap significantly on hypertension.

## Key findings

### 1. Cross-domain selection works well at 3-source scale

The agent correctly distinguishes aviation from clinical domains on
every question that has a clear primary domain. All 5 pure clinical
cross-dataset questions achieved exact match in both iterations. Both
aviation single-source controls were perfect in both iterations. The
out-of-scope and misleading-terminology probes were handled correctly.

At 3 sources with distinct domains, `list_sources` descriptions are
sufficient for domain-level routing.

### 2. Within-domain discrimination is unreliable

When two sources cover overlapping content (both clinical sources
cover hypertension), the agent cannot reliably choose between them
from descriptions alone. The v0 behavior — query both — is rational
given the description overlap. The v1 attempt to make the agent more
selective hurt recall without improving exact match.

This is a structural limitation: source descriptions optimized for
human cataloging may not provide the granularity needed for automated
source selection within a domain.

### 3. The "over-query" behavior is the safer default

v0's recall of 0.95 vs v1's 0.83 shows that querying both clinical
sources when any clinical question arises is a better strategy than
trying to pick one. The cost of an extra retrieve call (~500ms +
embedding compute) is trivial compared to the cost of missing relevant
information.

This suggests the platform should optimize for cheap retrieval rather
than precise source selection — at small catalog scale, the right
strategy is "query everything plausibly relevant."

### 4. Aviation cross-dataset questions are genuinely hard

The aviation+clinical cross-dataset questions (am-022 about
occupational health, am-025 about fatigue management) require the
agent to recognize that terms like "occupational health" and "fatigue
adherence" bridge to clinical content. Neither prompt iteration
reliably caught these signals. This is a hard NLU problem: the
clinical relevance is implicit, not stated in the question's surface
terms.

## Comparison with CDC structured scope signals

The CDC project embeds structured scope signals in source descriptions
that explicitly declare what topics each source covers and what
questions it can answer. RetrievalHub uses unstructured
`description_short` text instead.

The v0/v1 results suggest that unstructured descriptions work well for
cross-domain routing (clinical vs aviation) but poorly for
within-domain discrimination. The CDC approach would help here:
structured scope signals could explicitly declare that one source
covers "prescriptive guidelines" while another covers "primary
research evidence," making the distinction machine-readable rather
than relying on the agent to infer it from prose.

However, structured scope signals add curation overhead. At 3-source
scale, the added precision may not justify the cost. At larger catalog
sizes (10-50+ sources with overlapping domains), structured signals
would become more valuable as the combinatorial space of source
selection grows.

**Recommendation**: For the current catalog size, unstructured
descriptions suffice. If RetrievalHub grows beyond ~10 sources with
domain overlap, consider adding structured scope metadata (topic
coverage, content type, intended use case) alongside descriptions.

## Implications for issue #34 (multi-source search)

Issue #34 proposes a `multi_source_retrieve` tool that searches across
sources in a single call. These results suggest:

**Not needed at 3-source scale.** Agent discipline handles source
selection well enough. The agent correctly identifies relevant domains
and makes separate retrieve calls. The per-source retrieve pattern
gives the agent control over query tailoring (different query text for
different domains).

**Would help with the clinical conflation pattern.** If the agent
can't distinguish between two clinical sources, a multi-source tool
that searches both in one call would be more efficient than two
separate retrieve calls. But this is an efficiency optimization, not a
correctness fix — the agent already queries both.

**Would become important at scale.** At 20+ sources, making N separate
retrieve calls becomes impractical. The agent would need either a
multi-source search tool or a two-phase approach: coarse domain
selection followed by targeted retrieval.

**Recommendation**: Defer #34 until the catalog grows beyond 5-10
sources. At current scale, agent-driven source selection works well
enough. Revisit when the number of sources or the degree of domain
overlap increases.

## Artifacts

- `eval/cross_dataset_reasoning/eval_questions.json` — 20-question
  eval set
- `eval/cross_dataset_reasoning/prompts/v0.yaml` — baseline prompt
- `eval/cross_dataset_reasoning/prompts/v1.yaml` — disambiguation
  prompt
- `eval/cross_dataset_reasoning/runs/v0-baseline/` — baseline results
- `eval/cross_dataset_reasoning/runs/v1-disambiguate/` — v1 results
- `scripts/eval_cross_dataset_agent.py` — eval harness
- `retrieval-hub-agent/` — agent scaffold (sibling project)
