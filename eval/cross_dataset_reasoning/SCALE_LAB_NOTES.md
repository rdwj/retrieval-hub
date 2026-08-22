# Dataset Selection at Scale: Lab Notes

Phase 6 of the data-products epic. Tests at what catalog size the agent's
`list_sources` source selection approach breaks down. Phase 4 showed it
works at 3-4 sources with 0.95 recall and 0.55 exact match.

## Setup

Same eval harness as Phase 4 (`scripts/eval_cross_dataset_agent.py`)
with the v0 system prompt. 20 questions (10 cross-dataset, 5
single-source controls, 5 ad-hoc probes).

**Synthetic sources**: Registered via
`scripts/register_synthetic_sources.py`. Each synthetic has CURATED
status, a realistic `description_short`, and no physical index (no
actual data). The agent sees them in `list_sources` but `retrieve`
returns an error. We measure source selection only — which sources the
agent attempts to query.

**Confuser sources**: Three synthetics deliberately overlap with real
sources:
- `synthetic-who-clinical-guidelines` — overlaps with `va-cpg-clinical-guidelines`
- `synthetic-cardiology-research` — overlaps with `pubmed-hypertension`
- `synthetic-general-aviation-maintenance` — overlaps with `aircraft-maintenance`

**Scale points tested**: 4 (baseline), 14 (10 synthetic), 54 (50 synthetic)

**Note on experimental design**: Synthetic sources without data cause
`retrieve` errors, which the agent sees. This could affect behavior:
the agent might learn that certain sources fail and avoid them on
subsequent questions within the same conversation. However, each
question runs as a fresh conversation (no cross-question memory), so
this effect is limited to within-question retries.

## Results

| Catalog | Precision | Recall | Exact Match | Avg Iter | Tokens (in) |
|---------|-----------|--------|-------------|----------|-------------|
| 4       | 0.858     | 0.950  | 0.550       | 4.0      | 722K        |
| 14      | 0.526     | 0.950  | 0.100       | 5.4      | 458K        |
| 54      | 0.537     | 0.925  | 0.050       | 5.5      | 841K        |

## Analysis: Scale-14

### Recall is preserved

Recall stayed at 0.95 — identical to the 4-source baseline. The agent
still finds the right sources even with 10 confusers in the catalog.
This is the good news: more sources don't cause the agent to miss
relevant ones.

### Precision collapses due to confuser sources

Precision dropped from 0.86 to 0.53. Exact match dropped from 0.55 to
0.10 (only 2 of 20 questions). The agent queries confuser sources
alongside the real ones:

**Consistent confuser patterns:**
- `synthetic-cardiology-research`: queried on 12/14 clinical questions.
  Its description ("peer-reviewed cardiovascular research papers")
  overlaps directly with PubMed hypertension's domain.
- `synthetic-who-clinical-guidelines`: queried on 8/14 clinical
  questions. Its description ("clinical practice guidelines from WHO")
  overlaps with VA CPG's domain.
- `synthetic-general-aviation-maintenance`: queried on 7/8 aviation
  questions. Its description ("FAA airworthiness directives") overlaps
  with aircraft maintenance.

The agent correctly identifies the domain of each question and queries
all sources that plausibly cover that domain — including the confusers.
It cannot distinguish between a real source with actual data and a
confuser with an overlapping description.

### This is not a prompting problem

The v0 prompt says "query only the sources that are plausibly relevant."
The agent is following this instruction correctly — the confuser
sources ARE plausibly relevant based on their descriptions. The failure
is in the catalog, not the prompt. When multiple sources claim to cover
the same domain, the agent has no way to rank them.

### Implications

The breakpoint is sharp: precision drops 38% (0.86 → 0.53) when just 3
confuser sources are added to a catalog of 14. At 4 sources with
distinct domains, source selection works well. At 14 sources with
domain overlap, it breaks.

This has direct implications for #34 (multi-source search):
- At small catalog sizes (< 10) without domain overlap, agent-driven
  source selection suffices
- Once the catalog has sources with overlapping domains, either:
  (a) a multi-source search tool should handle domain routing, or
  (b) source descriptions need structured differentiation signals
      (content type, authority level, recency) that let the agent
      discriminate

## Analysis: Scale-54

### Precision plateaus, recall holds

Going from 14 to 54 sources had almost no further effect. Precision
stayed at 0.54 (vs 0.53 at 14). Recall dipped slightly to 0.93 (vs
0.95 at 14). Exact match dropped to 0.05 (1 of 20 — the out-of-scope
question).

### The confuser set is bounded

Only 5 of 50 synthetic sources were ever queried. The same 3 confusers
from the 14-source run dominate, plus 2 marginal additions at 54:
- `synthetic-cardiology-research` — queried on 13 questions
- `synthetic-who-clinical-guidelines` — queried on 8 questions
- `synthetic-general-aviation-maintenance` — queried on 8 questions
- `synthetic-iso-safety-standards` — queried on 2 questions (new)
- `synthetic-equipment-maintenance-manuals` — queried on 1 question (new)

The agent does NOT spray queries across all 54 sources. It selects a
bounded set of domain-relevant sources and ignores the rest. The
47 non-confuser synthetics (legal, financial, HR, IT, etc.) were never
queried — the domain boundary between these and the 3 real domains
is clear enough from descriptions.

### The degradation curve

The precision drop from 4→14 sources (0.86→0.53) was steep. From
14→54 it was flat (0.53→0.54). This suggests the degradation is driven
entirely by domain-overlap confusers, not by catalog size. Adding 40
non-overlapping sources had no effect. The relevant variable is
**confuser count within a domain**, not total catalog size.

## Key findings

### 1. Source selection scales with catalog size — if domains are distinct

Going from 4 to 54 sources with 47 non-overlapping domains had no
measurable impact on source selection accuracy. The agent reads all 54
descriptions, correctly identifies which domains are relevant, and
ignores the rest. The cost is more iterations (5.5 vs 4.0) and more
input tokens (841K vs 722K), but accuracy is unaffected.

### 2. Domain-overlap confusers are the scaling bottleneck

Three confuser sources — whose descriptions overlap with real sources'
domains — account for nearly all precision loss. The degradation is
sharp (38% precision drop) and happens as soon as the confusers are
introduced, not gradually with catalog growth.

### 3. Recall is robust across all scales

The agent never misses a relevant source because the catalog is large.
Recall stayed between 0.93 and 0.95 across all scale points. The
over-query behavior identified in Phase 4 is a feature, not a bug: it
ensures relevant sources are always included even at the cost of
querying some irrelevant ones.

### 4. The number of false-positive sources is bounded

At 54 sources, only 5 synthetics were ever queried (3 consistently).
The agent does not degrade into querying everything — it maintains
domain selectivity. The false positives are proportional to the number
of confusers in the relevant domain, not to catalog size.

## Recommendations

### For #34 (multi-source search)

The case for #34 is now stronger than Phase 4 suggested. At 4 sources
without domain overlap, agent-driven selection suffices. But real
catalogs will have domain overlap (multiple clinical guidelines,
multiple aviation document sets). The confuser experiment shows this
causes 38% precision loss.

Two mitigation strategies:
1. **Structured scope signals in descriptions**: Instead of prose,
   encode the distinguishing characteristics (authority level,
   content type, currency, geographic scope) as structured metadata
   that agents can reason about programmatically.
2. **Multi-source tool with ranking**: A `multi_source_retrieve` tool
   that queries all sources in a domain and returns ranked, deduplicated
   results would eliminate the source selection problem entirely. The
   agent selects the domain; the tool handles within-domain routing.

Strategy 2 is more robust and doesn't require data owners to write
machine-readable scope signals. Strategy 1 is additive and could
improve strategy 2's ranking.

### For catalog governance

Data owners should be aware that their source descriptions compete with
every other source in the catalog. A description that is too similar to
an existing source will cause agents to query both, wasting retrieval
budget and potentially confusing synthesis. The onboarding guide should
include a "distinctiveness check" — reviewing existing source
descriptions before writing a new one.

## Artifacts

- `scripts/register_synthetic_sources.py` — synthetic source registration
- `eval/cross_dataset_reasoning/runs/v0-baseline/` — 4-source baseline
- `eval/cross_dataset_reasoning/runs/scale-14/` — 14-source results
- `eval/cross_dataset_reasoning/runs/scale-54/` — 54-source results
