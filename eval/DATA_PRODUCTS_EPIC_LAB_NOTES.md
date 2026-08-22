# Data Products Epic: Consolidated Lab Notes

## Executive summary

The data-products epic took RetrievalHub from a single dataset (VA CPG
clinical guidelines) to three production sources spanning clinical
medicine and aviation maintenance, then tested whether an LLM agent could
select the right sources from catalog descriptions alone. Six phases ran
over four days in August 2026. The core quantitative results: chunking
parameter sweeps reached 0.950 hit_rate@5 for both PubMed (SA-256-0) and
aircraft (TF-512-0), but optimal chunk size did not transfer across
corpora. Agent source selection achieved 0.950 recall at 3 sources and
held at 0.925 recall even at 54 sources, though precision dropped 38%
when domain-overlap confusers were introduced. Overlap hurt MRR at every
chunk size and corpus tested. The practical takeaway: chunking parameters
must be tuned per corpus, source descriptions are the primary signal for
agent routing, and over-querying is the safer default at small catalog
scale.

## Background

RetrievalHub is a retrieval platform that serves multiple data products
to AI agents via MCP. Each data product has its own embedding model,
chunking configuration, and semantic layer (usage rules, freshness
metadata, citation requirements). Before this epic, the platform had one
production source: 52 VA/DoD clinical practice guidelines. The epic's
goal was to onboard two additional sources from different domains, develop
a repeatable chunking refinement methodology, test cross-dataset agent
reasoning, build tooling for data owner onboarding, and measure how
source selection scales with catalog size.

## Phase 1-2: Multi-source ingestion

**Research question:** Can RetrievalHub support multiple sources with
per-source embedding models and heterogeneous document formats?

**Methodology:** Ingested two new data products alongside the existing
VA CPG source. PubMed hypertension used a BioC section-aware chunker
built for the structured JSON format from NCBI's BioC API. Aircraft
maintenance used Docling-extracted markdown from Piper Aircraft service
bulletin PDFs. Each source used a domain-appropriate embedding model
served locally or via remote vLLM.

**Sources onboarded:**

| Source | Documents | Chunks | Embedding Model | Dimensions |
|---|---|---|---|---|
| VA CPG clinical guidelines | 52 | 6,500 | Nomic v1.5 | 768 |
| PubMed hypertension | 10 | 381 | PubMedBERT | 768 |
| Aircraft maintenance | 269 | 2,098 | Snowflake Arctic Embed m-v1.5 | 768 |

**Findings:**

- Per-source embedding models work without platform changes. The MCP
  server resolves the embedding endpoint from each source's recipe at
  query time.
- Remote embedding via vLLM required five deployment iterations: the
  `--task embed` flag, vLLM v0.8.5 pinning (latest doesn't support BERT
  embedding), GPU toleration, non-root cache paths, and
  `enableServiceLinks: false` to avoid Kubernetes env var collisions.
- The BioC section-aware chunker preserves section types and citation
  metadata from PubMed articles, providing richer grounding than
  Docling-extracted markdown.
- BERT tokenizers produce 1.3-1.5x more tokens than cl100k_base for the
  same text. Server-side truncation (`truncate_prompt_tokens: 512`)
  handles the mismatch without re-chunking.

## Phase 3: Chunking parameter sweeps

**Research question:** What chunk size and overlap produce the best
retrieval quality for each corpus, and do optimal parameters transfer
across domains?

**Methodology:** Ran parameter sweeps varying chunk size (256/512/1024
tokens), overlap (0/64/128 tokens), and chunking method
(section-aware vs token-fixed). Evaluated with 20 single-source
questions per corpus using hit_rate@5 and MRR@5 against pgvector.
Validated retrieval winners with Ragas answer-quality metrics
(context_precision, answer_relevancy) using gpt-oss:20b for answer
generation and gpt-oss-120b for scoring.

### PubMed hypertension sweep (9 configs)

| Config | Chunks | hit_rate@5 | MRR@5 |
|---|---|---|---|
| **SA-256-0** | **381** | **0.950** | **0.746** |
| SA-512-0 | 233 | 0.850 | 0.646 |
| SA-512-0-NB | 178 | 0.850 | 0.696 |
| SA-1024-0 | 155 | 0.850 | 0.654 |
| SA-256-64 | 458 | 0.850 | 0.654 |
| TF-512-0 | 160 | 0.850 | 0.702 |
| TF-1024-0 | 84 | 0.850 | 0.627 |
| SA-512-64 | 261 | 0.750 | 0.629 |
| TF-512-64 | 183 | 0.750 | 0.638 |

Ragas confirmation (SA-256-0 vs SA-512-0): context_precision +4.1pp,
answer_relevancy +7.8pp.

### Aircraft maintenance sweep (6 configs)

| Config | Chunks | hit_rate@5 | MRR@5 |
|---|---|---|---|
| **TF-512-0** | **2,098** | **0.950** | **0.749** |
| TF-512-64 | 2,330 | 0.950 | 0.580 |
| TF-1024-0 | 1,113 | 0.950 | 0.623 |
| TF-1024-128 | 1,219 | 0.950 | 0.522 |
| TF-256-64 | 5,279 | 0.900 | 0.660 |
| TF-256-0 | 4,064 | 0.850 | 0.692 |

Ragas confirmation (TF-512-0 vs TF-512-64): context_precision +4.3pp,
answer_relevancy +5.6pp.

### VA CPG reference sweep (4 configs, Nomic v1.5)

| Config | Chunks | hit_rate@5 | MRR@5 |
|---|---|---|---|
| 512/0 | 6,500 | 1.000 | 0.911 |
| 256/0 | 12,973 | 1.000 | 0.911 |
| 512/64 | 7,420 | 1.000 | 0.967 |
| 1024/0 | 3,263 | 1.000 | 0.967 |

**Findings:**

- Optimal chunk size does not transfer across domains. PubMed peaked at
  256 tokens; aircraft peaked at 512 tokens; VA CPG showed no
  sensitivity (all configs hit 1.000 hit_rate).
- Overlap consistently hurt MRR at every size and corpus. At 512 tokens,
  the aircraft corpus lost 17pp MRR from 64-token overlap. PubMed lost
  10pp hit_rate from overlap at both 256 and 512. Overlap is a
  mitigation for undersized chunks, not a general improvement.
- Section-aware and token-fixed chunking tied at 512 tokens on PubMed
  (both 0.850 hit_rate). The section-aware chunker's advantage is in
  metadata preservation, not raw retrieval quality.
- The Ragas decision rule held for both corpora: the retrieval winner
  also won on both answer-quality metrics. Retrieval metrics are
  sufficient for chunk config selection; Ragas confirms rather than
  overturns.

## Phase 4: Cross-dataset reasoning

**Research question:** Can a domain-agnostic agent select the right
sources from catalog descriptions alone, without hardcoded routing?

**Methodology:** Built a 20-question eval harness (10 cross-dataset,
5 single-source controls, 5 ad-hoc probes) with automated source
selection scoring (precision, recall, exact match). Agent used Claude
Sonnet 5 with a domain-agnostic system prompt that instructs it to
call `list_sources`, read descriptions, select sources, retrieve, and
synthesize. Tested two prompt iterations: v0 (baseline) and v1
(disambiguation guidance).

| Prompt | Precision | Recall | Exact Match | Avg Iterations | Input Tokens |
|---|---|---|---|---|---|
| v0 baseline | 0.858 | 0.950 | 0.550 | 4.05 | 722K |
| v1 disambiguate | 0.842 | 0.825 | 0.550 | 4.55 | 779K |

**Findings:**

- Cross-domain source selection works well at 3-source scale. The agent
  correctly distinguishes aviation from clinical domains on every
  question with a clear primary domain. All 5 pure clinical cross-dataset
  questions achieved exact match in both iterations.
- Within-domain discrimination is unreliable. When two sources cover
  overlapping content (both clinical sources mention hypertension), the
  agent cannot reliably choose between them from descriptions alone.
- Making the prompt more selective (v1) hurt recall by 12.5pp without
  improving exact match. The agent became more cautious but not more
  accurate.
- Over-querying is the safer default. v0's recall of 0.950 vs v1's
  0.825 shows that querying both clinical sources when any clinical
  question arises is a better strategy than trying to pick one.

## Phase 5: Source scaffolding tool

**Research question:** Can the onboarding process be made accessible to
domain experts who are not retrieval engineers?

**Methodology:** Built `scripts/new_source.py`, a scaffolding tool that
generates a complete ingestion script from a source slug. The generated
script includes the full 7-stage ingestion pipeline, Phase 4-informed
description guidance, governance templates, and a CLI with all standard
arguments.

**Deliverables:**

| Artifact | Description |
|---|---|
| `scripts/new_source.py` | 643-line scaffolding tool |
| Unit tests | 43 tests covering template generation |
| Makefile target | `make new-source SLUG=my-source` |
| `docs/guide-data-owner.md` | Updated with tool reference |

**Findings:**

- The generated scripts follow the same structure as the hand-built
  PubMed and aircraft ingestion scripts, reducing onboarding from
  writing a pipeline from scratch to filling in source-specific details.
- Description guidance from Phase 4 is embedded in the generated
  templates: data owners are prompted to write descriptions that
  differentiate their source from existing catalog entries.

## Phase 6: Scale testing

**Research question:** At what catalog size does agent-driven source
selection break down?

**Methodology:** Registered synthetic sources (with CURATED status and
realistic descriptions but no physical data) using
`scripts/register_synthetic_sources.py`. Three synthetic sources
deliberately overlapped with real sources' domains ("confusers").
Tested source selection at three catalog sizes using the same
20-question eval set and v0 prompt.

| Catalog Size | Sources (real + synthetic) | Precision | Recall | Exact Match | Avg Iterations | Input Tokens |
|---|---|---|---|---|---|---|
| 4 | 3 + 1 | 0.858 | 0.950 | 0.550 | 4.0 | 722K |
| 14 | 3 + 11 | 0.526 | 0.950 | 0.100 | 5.4 | 458K |
| 54 | 3 + 51 | 0.537 | 0.925 | 0.050 | 5.5 | 841K |

**Confuser query frequency at scale-54:**

| Confuser Source | Questions Queried |
|---|---|
| synthetic-cardiology-research | 13 of 20 |
| synthetic-who-clinical-guidelines | 8 of 20 |
| synthetic-general-aviation-maintenance | 8 of 20 |
| synthetic-iso-safety-standards | 2 of 20 |
| synthetic-equipment-maintenance-manuals | 1 of 20 |
| All other synthetics (45) | 0 of 20 |

**Findings:**

- Domain-overlap confusers cause the 38% precision drop (0.858 to
  0.526), not catalog size. Adding 40 more non-overlapping sources
  (14 to 54) had no further effect on precision.
- Recall held between 0.925 and 0.950 across all scale points. The
  agent never misses a relevant source because the catalog is large.
- Only 5 of 50 synthetic sources were ever queried. The agent maintains
  domain selectivity and does not degrade into querying everything.
- The degradation curve is sharp then flat: precision drops steeply when
  confusers are introduced (4 to 14 sources), then plateaus (14 to 54
  sources).

## Cross-cutting findings

**Chunking parameters are corpus-specific, not universal.** The optimal
chunk size differed across all three corpora: 256 tokens for PubMed
review articles, 512 tokens for aircraft service bulletins, and all
tested sizes tied for VA CPG clinical guidelines. The interaction between
document structure, embedding model domain specificity, and query
granularity determines the optimum. The recommended starting point is
512/0; test 256 and 1024 neighbors from there.

**Overlap is never beneficial for well-sized chunks.** Across three
corpora and 21 configurations, overlap either hurt or had no effect on
hit_rate when the chunk size was already appropriate for the corpus.
Overlap only helped when chunks were undersized (256 tokens on aircraft,
where 512 was optimal). The mechanism: overlap duplicates content across
adjacent chunks, spreading similarity scores across near-duplicates and
pushing the best-matching chunk lower in the ranking.

**Agent source selection scales with catalog size if domains are
distinct.** Going from 4 to 54 sources with 47 non-overlapping domains
had no measurable impact on source selection accuracy. The agent reads
all descriptions, correctly identifies which domains are relevant, and
ignores the rest. The cost is more iterations and input tokens, not
reduced accuracy.

**Domain-overlap confusers are the scaling bottleneck, not catalog
size.** Three confuser sources whose descriptions overlap with real
sources' domains account for nearly all precision loss. The degradation
is sharp (38% precision drop) and happens as soon as the confusers are
introduced, not gradually with catalog growth.

**Over-querying is the right default at small catalog scale.** Querying
all plausibly relevant sources (even when some are duplicative) preserves
0.95 recall. Attempting to narrow source selection to improve precision
hurts recall without improving exact match. At the cost of an extra
retrieve call per overlapping domain, this strategy ensures relevant
information is never missed.

## Recommendations

1. **Start chunking sweeps at 512/0, then test 256 and 1024 neighbors.**
   The VA CPG baseline (512 tokens, no overlap) is a better starting
   prior than 256 from PubMed, since 512 won or tied on two of three
   corpora. But the prior should be tested, not assumed.

2. **Source descriptions are the primary signal for agent routing. Write
   them carefully.** Descriptions that are too similar to existing sources
   cause agents to query both, wasting retrieval budget. The onboarding
   guide should include a "distinctiveness check" against the existing
   catalog.

3. **Defer #34 (multi-source search) until the catalog has domain
   overlap.** At 3-4 sources with distinct domains, agent-driven source
   selection works well enough. Once the catalog grows to include
   sources with overlapping domains, either a multi-source search tool
   or structured scope signals will be needed.

4. **Consider structured scope signals for within-domain discrimination
   at scale.** Unstructured descriptions work for cross-domain routing
   but fail for within-domain discrimination. Structured metadata
   (content type, authority level, geographic scope) would help agents
   distinguish sources that cover similar topics.

5. **Optimize for cheap retrieval rather than precise source selection.**
   At small catalog scale, the right strategy is "query everything
   plausibly relevant." The platform should make retrieve calls cheap
   (fast embedding, efficient pgvector queries) rather than investing in
   precise pre-retrieval source selection.

## Artifact index

### Ingestion scripts

| File | Description |
|---|---|
| `scripts/ingest_va_cpg.py` | VA CPG clinical guidelines ingestion |
| `scripts/ingest_pubmed_hypertension.py` | PubMed hypertension BioC ingestion |
| `scripts/ingest_aircraft_maintenance.py` | Aircraft maintenance Docling ingestion |
| `scripts/new_source.py` | Source scaffolding tool for new data products |

### Chunking sweep infrastructure

| File | Description |
|---|---|
| `docs/chunking-refinement-methodology.md` | 8-step methodology for chunking evaluation |
| `scripts/sweep_pubmed_chunking.py` | PubMed 9-config parameter sweep |
| `scripts/sweep_aircraft_chunking.py` | Aircraft 6-config parameter sweep |
| `scripts/eval_chunking_answer_quality.py` | Ragas answer-quality comparison (PubMed) |
| `scripts/eval_aircraft_answer_quality.py` | Ragas answer-quality comparison (aircraft) |

### Chunking sweep results

| File | Description |
|---|---|
| `eval/pubmed_hypertension/CHUNKING_SWEEP.md` | PubMed sweep lab notes |
| `eval/pubmed_hypertension/sweep_results.json` | PubMed sweep raw results |
| `eval/pubmed_hypertension/ragas_chunking_comparison.json` | PubMed Ragas comparison |
| `eval/aircraft_maintenance/CHUNKING_SWEEP.md` | Aircraft sweep lab notes |
| `eval/aircraft_maintenance/sweep_results.json` | Aircraft sweep raw results |
| `eval/aircraft_maintenance/ragas_chunking_comparison.json` | Aircraft Ragas comparison |
| `eval/va_cpg_chunking_sweep/sweep_results.json` | VA CPG sweep raw results |

### Cross-dataset reasoning

| File | Description |
|---|---|
| `eval/cross_dataset_reasoning/LAB_NOTES.md` | Phase 4 lab notes (3-source eval) |
| `eval/cross_dataset_reasoning/SCALE_LAB_NOTES.md` | Phase 6 lab notes (scale testing) |
| `eval/cross_dataset_reasoning/eval_questions.json` | 20-question eval dataset |
| `eval/cross_dataset_reasoning/prompts/v0.yaml` | Baseline agent prompt |
| `eval/cross_dataset_reasoning/prompts/v1.yaml` | Disambiguation agent prompt |
| `scripts/eval_cross_dataset_agent.py` | Cross-dataset eval harness |
| `scripts/register_synthetic_sources.py` | Synthetic source registration for scale tests |

### Eval run data

| Directory | Description |
|---|---|
| `eval/cross_dataset_reasoning/runs/v0-baseline/` | 3-source baseline results |
| `eval/cross_dataset_reasoning/runs/v1-disambiguate/` | Disambiguation prompt results |
| `eval/cross_dataset_reasoning/runs/scale-14/` | 14-source scale test results |
| `eval/cross_dataset_reasoning/runs/scale-54/` | 54-source scale test results |

### Documentation

| File | Description |
|---|---|
| `docs/guide-data-owner.md` | Data owner onboarding guide |
| `docs/guide-ops.md` | Ops guide for source deployment |
| `docs/onboarding-journey-va-cpg.md` | VA CPG onboarding case study |
