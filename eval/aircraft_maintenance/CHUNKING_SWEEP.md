# Chunking Parameter Sweep: Aircraft Maintenance Service Bulletins

## Experiment metadata

- **Date:** 2026-08-21
- **Operator:** Wes Jackson
- **Epic:** data-products Phase 3
- **Methodology:** docs/chunking-refinement-methodology.md

## Corpus summary

269 Piper Aircraft service documents across two families: Cherokee (PA-28)
and Saratoga (PA-32). Document types include Service Bulletins (SB),
Service Letters (SL), Supplemental Service Letters (SSL), Vendor Service
Publications (VSP), and Customer Information Letters (CIL).

Source format: Docling-extracted markdown from original PDFs. No structured
passage boundaries or section type labels — the source format provides
headings and tables but not typed passages. Baseline ingestion: 2330 chunks
at 512 tokens, 64 overlap.

Evaluation dataset: 20 single-source questions (5 cross-dataset questions
excluded from sweep eval). Stratified by category: procedure (5), parts (4),
applicability (4), cross_aircraft (4), document_type (3).

## Infrastructure

| Component | Value |
|---|---|
| Embedding model | Snowflake/snowflake-arctic-embed-m-v1.5 (768-dim) |
| Embedding backend | Remote vLLM endpoint (OpenAI-compatible) |
| Vector store | pgvector (local, port 5433) |
| Sweep table | idx_aircraft_maintenance_sweep |
| Production table | idx_aircraft_maintenance_v1 (untouched) |
| Eval dataset | eval/aircraft_maintenance/qa_dataset.json (20 questions) |
| Tokenizer | cl100k_base (chunking) / WordPiece (embedding) |
| Truncation | truncate_prompt_tokens: 512 (server-side) |
| Top-k | 5 |
| Metrics | hit_rate@5, MRR@5 |

## Sweep grid

6 configurations testing chunk size (256/512/1024) and overlap (0/64/128)
with token-fixed chunking only. No section-aware chunker — the source is
Docling-extracted markdown without typed passage boundaries.

| Config ID | Tokens | Overlap | Rationale |
|---|---|---|---|
| TF-512-64 | 512 | 64 | Current production baseline |
| TF-512-0 | 512 | 0 | Isolates overlap effect at current size |
| TF-256-0 | 256 | 0 | PubMed winner transferred |
| TF-256-64 | 256 | 64 | Tests overlap at PubMed-optimal size |
| TF-1024-0 | 1024 | 0 | Large chunks for maximum context |
| TF-1024-128 | 1024 | 128 | Tests if large chunks benefit from overlap more than small/medium |

## Hypothesis

*Written before running the sweep. Left unedited after results.*

**Primary prediction: TF-256-0 wins on hit_rate@5.**

Reasoning:

- The PubMed sweep found 256-token chunks optimal (0.950 hit_rate vs 0.850
  for 512). The win came from more focused embedding targets that matched
  query intent better.
- Aircraft service bulletins are shorter and more topically focused than
  PubMed review articles. Each bulletin covers a single service action with
  specific part numbers, compliance times, and serial number ranges. These
  are exactly the kind of dense, factual passages where smaller chunks
  should excel — the relevant fact often fits in a single paragraph.
- The eval questions are highly specific (part numbers, torque values,
  serial number ranges). Smaller chunks isolate these facts rather than
  bundling them with surrounding procedural text, making the embedding
  signal stronger for precision queries.

**Secondary predictions:**

- TF-512-0 will outperform TF-512-64 (current baseline) due to the
  overlap penalty observed in PubMed (-10pp). Production was set with
  64-token overlap as a reasonable default, not because it was validated.
- Overlap will provide no benefit or actively hurt at every size,
  consistent with the PubMed finding (-10pp hit_rate). Aircraft bulletins
  have clear structural boundaries between procedures, parts lists,
  applicability sections, and compliance instructions. Overlap duplicates
  content across these boundaries without improving retrieval.
- TF-1024-0 will underperform 256 and 512 on hit_rate. In PubMed,
  512 and 1024 tied at 0.850, both losing to 256 (0.950). For aircraft
  bulletins (shorter documents, 1-3 pages), 1024-token chunks will
  often capture an entire document, diluting the embedding signal.
- TF-1024-128 tests whether large chunks benefit from overlap more than
  small/medium chunks. If overlap helps at 1024 but not at 256/512, it
  would suggest overlap's value depends on how much unique content each
  chunk captures — an important nuance.

**What would surprise us:**

- If TF-512-0 or TF-512-64 wins, it would suggest that Snowflake Arctic
  Embed (a general-purpose model) needs more context per chunk than
  PubMedBERT (a domain-specific model) to discriminate between passages.
  This would be a paper-worthy finding about the interaction between
  embedding model domain specificity and optimal chunk size.
- If overlap helps at any size, it would contradict both the PubMed and
  VA CPG findings. The PubMed corpus had even sharper passage boundaries
  via BioC JSON; if overlap helps with less-structured markdown, that
  would suggest the format-structure interaction matters.
- If TF-1024-0 matches or beats 512-token configs, it would suggest that
  short, focused documents (service bulletins) behave differently from
  longer articles — fewer documents means less noise in the search space,
  and a single large chunk per document might be sufficient.

**Cross-domain comparison question:**

Do chunking defaults transfer across domains? If 256/0 wins for both
PubMed clinical literature and aircraft maintenance bulletins despite
different embedding models, source formats, and document structure, that
strengthens the case for 256/0 as a general-purpose starting point for
structured technical content. If the optimal differs, the interaction
between corpus properties (document length, structural density, domain
vocabulary) and chunking parameters is more complex than a single
default can capture.

---

## Results

Total sweep time: 259.8s (6 configs, 263 documents each, 20 eval questions).

Note: the first sweep run produced corrupted results due to an IPv4/IPv6
port conflict between the local Podman Postgres container and a concurrent
`oc port-forward` on port 5433. `write_chunks` and `count_rows` connected
to different backends non-deterministically. Fixed by using `127.0.0.1`
instead of `localhost` in the connection string. The corrected results
below are from the second run.

| Config ID | Chunks | hit_rate@5 | MRR@5 | mean_score | Notes |
|---|---|---|---|---|---|
| **TF-512-0** | **2098** | **0.950** | **0.749** | **0.629** | **winner** |
| TF-512-64 | 2330 | 0.950 | 0.580 | 0.628 | production baseline |
| TF-1024-0 | 1113 | 0.950 | 0.623 | 0.620 | |
| TF-1024-128 | 1219 | 0.950 | 0.522 | 0.628 | |
| TF-256-64 | 5279 | 0.900 | 0.660 | 0.638 | |
| TF-256-0 | 4064 | 0.850 | 0.692 | 0.640 | |

Four configs tie at 0.950 hit_rate@5 (19/20 questions). TF-512-0 wins the
MRR@5 tiebreaker at 0.749, meaning it ranks the first relevant chunk highest
on average. The gap is large: +17pp over TF-512-64 (production), +13pp
over TF-1024-0, +23pp over TF-1024-128.

**Per-question analysis:**

All configs miss am-015 (Saratoga variants of SB 1197E). The expected
document is `SB_1197E (Saratoga)`, but the Cherokee version of the same SB
scores higher and fills the top-5 with Cherokee chunks. This is a data
quality issue, not a chunking issue.

TF-256-0 additionally misses am-003 (edge distance tolerance, 0.19 inches)
and am-011 (Warrior III/Archer III serial numbers). Both involve dense
tabular data or dimensional tolerances embedded within multi-step procedures.
At 256 tokens, these tables and procedures are split across multiple chunks,
diluting the embedding signal for the specific fact the query targets.

TF-256-64 recovers am-003 (overlap captures the boundary crossing) but
still misses am-011.

## Effect decomposition

### Size effect (256 vs 512 vs 1024)

At 0 overlap:
- TF-256-0: 0.850 hit_rate, 0.692 MRR, 4064 chunks
- TF-512-0: 0.950 hit_rate, 0.749 MRR, 2098 chunks
- TF-1024-0: 0.950 hit_rate, 0.623 MRR, 1113 chunks

512 and 1024 tie on hit_rate (0.950), both beating 256 by 10pp. But 512
wins on MRR (0.749 vs 0.623) — 512-token chunks are large enough to
capture tabular data and procedures while still focused enough to rank well.
1024-token chunks capture even more content but dilute the embedding signal,
reducing ranking precision.

256 is too small for this corpus. Service bulletins contain dense structural
content (serial number tables, parts lists, multi-step procedures) that
needs to be kept together for the embedding to capture the full meaning.

### Overlap effect

| Size | 0 overlap | With overlap | Delta |
|---|---|---|---|
| 256 | 0.850 | 0.900 (+64) | +5pp |
| 512 | 0.950 | 0.950 (+64) | 0pp |
| 1024 | 0.950 | 0.950 (+128) | 0pp |

At 256 tokens, overlap HELPS hit_rate (+5pp) by recovering boundary-crossing
content (am-003 edge distance tolerance). At 512 and 1024, overlap is
NEUTRAL on hit_rate.

However, overlap consistently HURTS MRR at every size:
- 256: 0.692 → 0.660 (-3pp)
- 512: 0.749 → 0.580 (-17pp)
- 1024: 0.623 → 0.522 (-10pp)

The 512 overlap penalty is dramatic: -17pp MRR. Overlap duplicates content
in adjacent chunks, spreading similarity scores across near-duplicates and
pushing the best-matching chunk lower in the ranking. The production config
(TF-512-64) was penalized by this effect — dropping overlap improves MRR
by 17pp with no hit_rate cost.

## Cross-domain comparison with PubMed findings

| Finding | PubMed sweep | Aircraft sweep |
|---|---|---|
| Best config | SA-256-0 | TF-512-0 |
| Best hit_rate@5 | 0.950 | 0.950 |
| Best MRR@5 | 0.746 | 0.749 |
| Best chunk size | 256 tokens | 512 tokens |
| Overlap effect | Harmful (-10pp hit_rate) | Mixed (helps at 256, neutral at 512/1024, always hurts MRR) |
| Embedding model | PubMedBERT (domain-specific) | Snowflake Arctic (general-purpose) |
| Source format | BioC JSON (structured passages) | Markdown (Docling-extracted) |
| Corpus size | 10 articles | 263 documents |
| Chunk count (winner) | 381 | 2098 |

**Key differences:**

1. **Optimal chunk size does NOT transfer across domains.** PubMed (256)
   vs aircraft (512). The interaction is between corpus structure and query
   specificity: PubMed review articles have discrete factual claims that
   fit in 256-token chunks. Aircraft bulletins embed facts in dense tables
   and procedures that need 512 tokens to stay coherent.

2. **Embedding model domain specificity interacts with chunk size.**
   PubMedBERT (domain-specific) discriminates well with 256-token chunks
   because its vocabulary is tuned for biomedical text — small chunks are
   still semantically rich. Snowflake Arctic (general-purpose) needs more
   context (512 tokens) to achieve the same discrimination on aviation
   maintenance text, a domain far from its training distribution.

3. **Overlap effect depends on corpus structure.** PubMed: uniformly
   harmful (-10pp). Aircraft: size-dependent. At 256 tokens where chunks
   are too small for this corpus, overlap compensates for boundary issues
   (+5pp hit_rate). At 512 and 1024 where chunks are already well-sized,
   overlap is pure cost (0pp hit_rate, -10 to -17pp MRR).

4. **Absolute performance converges.** Both corpora reach 0.950 hit_rate
   and ~0.75 MRR at their optimal configs. The floor for unoptimized
   configs differs more (PubMed: 0.750; aircraft: 0.850), suggesting the
   aircraft corpus is more forgiving of chunking choices, possibly because
   shorter, more focused documents have more redundant coverage.

**Methodological takeaway:** The chunking refinement methodology
(docs/chunking-refinement-methodology.md) was followable for the second
domain and produced a clear winner. But the recommended prior ("start
with 512/0 for structured text") happened to be correct for aircraft
rather than the PubMed-derived "start with 256/0." A better general
recommendation: start with 512/0, then test 256 and 1024 neighbors.
The prior should come from the VA CPG baseline (which also found 512
optimal) rather than the PubMed exception.

## Surprises

**The primary hypothesis was wrong.** TF-256-0 did not win; TF-512-0 did.
The PubMed prior (256 wins) did not transfer. This is the most important
cross-domain finding: chunking parameters are corpus-specific, not
universal. The hypothesis correctly predicted overlap would hurt, but got
the optimal size wrong.

**1024-token chunks matched 512 on hit_rate.** TF-1024-0 scored 0.950,
tying with TF-512-0. Large chunks did not dilute retrieval as expected —
service bulletins are short enough that 1024-token chunks often capture
an entire document or large section, providing excellent coverage. The
MRR penalty (0.623 vs 0.749) shows the trade-off: large chunks find the
right content but rank it less precisely.

**Overlap helped at 256 but not at larger sizes.** TF-256-64 recovered
one question (am-003) that TF-256-0 missed, improving hit_rate from 0.850
to 0.900. This is the first case in our sweeps where overlap provided
a measurable benefit. The mechanism: when chunks are too small for the
corpus, overlap compensates by capturing boundary-crossing content that
would otherwise be split. This suggests overlap is a mitigation for
undersized chunks, not a general improvement.

**The production config was suboptimal but close.** TF-512-64 (production)
scored 0.950 hit_rate, tying with the winner. The only cost of the
64-token overlap is MRR degradation (0.580 vs 0.749). Dropping overlap
is a pure win: same recall, much better ranking, 10% fewer chunks.

## Answer quality validation (Methodology Step 7)

*To be filled after Ragas evaluation.*

## Production re-ingestion

Production table `idx_aircraft_maintenance_v1` re-ingested with TF-512-0
parameters on 2026-08-21:
- OVERLAP_TOKENS: 64 -> 0
- CHUNK_TOKENS: 512 (unchanged)
- Chunk count: 2330 -> 2098
- Recipe version: v1
- Source UUID: 45b9aef7-3eec-4749-b089-745ffd055fe2
- Wall time: 39.9s

## Replication

```bash
# Run the chunking parameter sweep
python scripts/sweep_aircraft_chunking.py \
  --embedding-endpoint https://vllm-snowflake-embedding-retrieval-hub.apps.cluster-khsm8.khsm8.sandbox780.opentlc.com \
  --vectors-db-url 'postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors'

# Run Ragas answer-quality comparison (winner vs baseline)
python scripts/eval_aircraft_answer_quality.py \
  --embedding-endpoint https://vllm-snowflake-embedding-retrieval-hub.apps.cluster-khsm8.khsm8.sandbox780.opentlc.com
```

## Raw data

- Per-config checkpoints: `eval/aircraft_maintenance/sweep_configs/`
- Aggregate results: `eval/aircraft_maintenance/sweep_results.json`
- Ragas comparison: `eval/aircraft_maintenance/ragas_chunking_comparison.json` (pending)
