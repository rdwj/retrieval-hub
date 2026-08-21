# Chunking Refinement Methodology

A repeatable process for arriving at the best chunking strategy for any
data product onboarded to RetrievalHub. Most teams pick 512 tokens and
move on. This methodology shows how to start with an informed hypothesis,
evaluate it against alternatives, and document the result so future
re-evaluations have a baseline to compare against.

## Why this matters

Chunking is the first decision that shapes retrieval quality, and it
compounds through every downstream step. Chunks that are too large
dilute the embedding signal; too small and they lose answer-model
context; split mid-thought and they match queries but can't answer
them; ignore source structure and they throw away metadata that could
improve both retrieval and grounding.

Despite this, chunking is rarely evaluated systematically. The default
in most RAG tutorials is a fixed token window with some overlap, chosen
once and never revisited. This methodology takes 4-8 hours of
additional work during onboarding and produces measurable evidence for
the chosen strategy.

## Contents

1. [Understand your source format](#step-1-understand-your-source-format)
2. [Form a starting hypothesis](#step-2-form-a-starting-hypothesis)
3. [Build an evaluation dataset](#step-3-build-an-evaluation-dataset)
4. [Define the sweep grid](#step-4-define-the-sweep-grid)
5. [Run the sweep](#step-5-run-the-sweep)
6. [Analyze and select](#step-6-analyze-and-select)
7. [Validate with answer quality](#step-7-validate-with-answer-quality)
8. [Record in the data card](#step-8-record-in-the-data-card)
9. [Appendix: Source format case study](#appendix-source-format-case-study--bioc-json-vs-markdown)

---

## Step 1: Understand your source format

Before choosing chunking parameters, evaluate what structural information
your source format provides. **The source format you chunk from affects
retrieval quality before you even get to chunking parameters.**

Some formats carry explicit structure that informs chunking. PubMed
Central articles in BioC JSON provide section labels (INTRO, METHODS,
RESULTS, DISCUSS, CONCL), paragraph-level passage boundaries, typed
reference passages with DOIs and PMIDs, and figure/table captions.
Chunking from this format preserves all of that. Extracting the same
article to markdown first loses most of it. See the
[appendix](#appendix-source-format-case-study--bioc-json-vs-markdown).

**Decision tree for format selection:**

1. Does your source have explicit section or passage structure (XML,
   JSON with typed passages, structured HTML with semantic tags)?
   - **Yes**: chunk from the structured format. Use section-aware
     chunking as the default hypothesis. Each passage or paragraph
     becomes a natural chunk boundary.
   - **No**: proceed to step 2.

2. Can you extract to markdown with a layout-aware tool (Docling)?
   - **Yes**: extract to markdown, then chunk with token-fixed
     splitting. Docling preserves headings and tables that inform
     section boundaries even without explicit passage structure.
   - **No**: extract to plain text and chunk with token-fixed splitting.

3. Does the structured format have metadata you want to attach to chunks
   (section type, citation data, figure references)?
   - **Yes**: propagate that metadata as chunk-level fields during
     ingestion. These enable section-aware retrieval, citation
     grounding, and filtering by passage type.

**Time:** 1-2 hours to assess your source format and decide on an
extraction path. This step often reveals information you did not know
your source provided.

---

## Step 2: Form a starting hypothesis

Use priors from related corpora to avoid testing configurations that are
unlikely to win. The goal is not to skip evaluation, but to start from
an informed position and prune the sweep grid.

**Clinical/biomedical text baseline** (from VA CPG evaluation, 52
documents, 50 evaluation queries):

| Config | Recall@5 | MRR@5 | Chunks |
|---|---|---|---|
| Token-512-0 | 0.680 | 0.321 | 15,539 |
| Token-512-64 | 0.640 | 0.334 | 17,756 |
| Token-1024-0 | 0.660 | 0.371 | 8,309 |
| Token-1024-64 | 0.640 | 0.315 | 8,882 |
| Sentence-512-0 | 0.440 | 0.216 | 7,956 |

**Findings that transfer:**

- **Token-based splitting outperformed sentence-based** by 24 percentage
  points on recall@5 (0.68 vs. 0.44). Clinical text uses structured
  headings, numbered recommendations, and tables that do not align with
  sentence boundaries. Sentence-based chunks split recommendations
  mid-thought or merge unrelated sections.
- **512 tokens was the best size for recall.** 1024-token chunks
  produced competitive MRR (0.371 vs. 0.321) but lower recall. For
  recall-oriented use cases where surfacing multiple relevant passages
  matters, 512-token chunks with more granular coverage performed better.
- **Overlap provided no benefit for structured documents.** Token-512-64
  scored lower than Token-512-0 (0.64 vs. 0.68) while increasing chunk
  count by 14%. Documents with clear section structure already have
  natural boundary alignment; overlap adds redundancy without improving
  boundary coverage.
- **For structured sources (BioC JSON, well-formed XML), section-aware
  chunking is the default hypothesis.** Natural passage boundaries (one
  paragraph = one passage) provide better chunk boundaries than
  heuristic text splitting.

**Forming your hypothesis:** If your corpus resembles clinical
guidelines (structured, technical, section-heavy), start with
Token-512-0. If your source provides explicit passage boundaries,
start with section-aware chunking. If your text is conversational or
unstructured, include sentence-based chunking in your sweep.

---

## Step 3: Build an evaluation dataset

You need 20-50 question/answer pairs with manually identified relevant
passages. This is the ground truth that makes the sweep meaningful.
Without it, you are optimizing in the dark.

**Requirements:**

- Each Q/A pair maps to one or more specific passages in the corpus.
  "Relevant document" is not enough; you need the passage-level ground
  truth so that retrieval metrics (hit_rate@5, MRR@5) measure whether
  the right chunks surface, not just the right documents.
- Stratify by query type. For clinical corpora, the VA CPG evaluation
  used two registers: lay-language queries ("What should I do about high
  blood pressure?") and clinical-register queries ("First-line
  pharmacologic options for treating hypertension"). The rewriting and
  reranking pipeline performed differently on each register.
- Include at least three query types: factual lookup ("What is the
  recommended blood pressure target?"), comparative reasoning ("How do
  VA guidelines compare to AHA guidelines on beta-blockers?"), and
  procedural ("What are the steps for titrating ACE inhibitors?").

**Practical guidance:** Domain experts write better evaluation queries
than engineers. If the data owner can contribute 10-15 queries,
supplement with LLM-generated queries validated by a domain expert.
For a 50-query set, aim for roughly equal coverage of both registers.
Store the dataset in a reusable format (`eval/autorag/qa_dataset.json`)
so future re-evaluations use the same ground truth.

**Time:** 2-4 hours. This is the largest time investment in the
methodology, and it is the step that most determines the quality of your
results.

---

## Step 4: Define the sweep grid

The sweep tests configurations across three dimensions: chunk method,
chunk size, and overlap. If your source supports section-aware chunking,
add a fourth dimension for section boundary behavior.

**Dimensions:**

| Dimension | Values | Notes |
|---|---|---|
| Chunk method | token-fixed, sentence, section-aware | Section-aware only if source has explicit structure |
| Chunk size | 256, 512, 1024 tokens | Measured by the embedding model's tokenizer |
| Overlap | 0, 64, 128 tokens | Test 0 first; add overlap only if boundary effects appear |
| Section boundaries | respect (never cross), ignore (continuous) | Only for section-aware method |

**Full factorial is expensive.** 3 methods x 3 sizes x 3 overlaps = 27
configurations, each requiring re-ingestion and a full eval run. Use
your hypothesis from Step 2 to prune.

**Recommended grid (8-12 configurations):** Start with the hypothesis
winner and its nearest neighbors: (1) hypothesis winner, (2) one size
step up and down, (3) overlap variants, (4) the alternative method at
the hypothesis size, (5) section-aware variants if structured source,
(6) any domain-specific chunker (e.g., recommendation-boundary for
clinical text).

**AutoRAG configuration template:**

```yaml
modules:
  - module_type: llama_index_chunk
    chunk_method:
      - Token
      - Sentence
    chunk_size:
      - 256
      - 512
      - 1024
    chunk_overlap:
      - 0
      - 64
    add_file_name: en
```

This template produces 12 configurations (2 methods x 3 sizes x 2
overlaps). Add section-aware configurations manually if your source
supports them.

**Time:** 30-60 minutes to define the grid and write the configuration.

---

## Step 5: Run the sweep

For each configuration in the grid: re-ingest the corpus with the new
chunking parameters, run the retrieval evaluation against your ground
truth dataset, and record the metrics.

**Per-configuration steps:**

1. Re-chunk the corpus with the new parameters.
2. Re-embed all chunks with the same embedding model. Do not change
   the embedding model during a chunking sweep; that is a separate
   experiment.
3. Load chunks into a temporary pgvector index.
4. Run the evaluation query set. Record hit_rate@5 and MRR@5.
5. Record aggregate metrics and chunk count.

**Results table template** (one row per configuration):

| Config | Recall@5 | MRR@5 | Chunk count | Notes |
|---|---|---|---|---|
| Token-512-0 | | | | hypothesis winner |
| Token-256-0 | | | | |
| Token-1024-0 | | | | |
| Sentence-512-0 | | | | |
| Section-aware | | | | if applicable |

If your evaluation dataset is stratified, record metrics per stratum.
Aggregate metrics can hide important differences.

**Time:** 10-15 minutes per configuration for re-ingestion, 5-10
minutes per configuration for evaluation. A 10-configuration sweep
takes 2-4 hours total.

---

## Step 6: Analyze and select

**Primary metric: recall@5** (hit_rate@5). For recall-oriented use
cases (enterprise retrieval, clinical decision support, research), the
first priority is surfacing at least one relevant chunk in the top 5.
A configuration with 0.68 recall is better than one with 0.66 recall,
even if the latter has better MRR.

**Tiebreaker 1: MRR@5.** When two configurations have the same recall,
prefer the one with higher Mean Reciprocal Rank. Higher MRR means the
first relevant chunk appears higher in the ranking, which matters for
user experience and for answer models that attend more to early context.

**Tiebreaker 2: chunk count.** When recall and MRR are tied, prefer
fewer chunks. A smaller index is cheaper to store and faster to search.

**Watch for:**

- **Method effects dominating size effects.** In the VA CPG sweep,
  sentence vs. token was a 24-point gap on recall. Size differences
  within the same method were 2-4 points. If you see a large method
  effect, the method choice matters more than fine-tuning the size.
- **Overlap providing negative value.** If overlap configurations
  score equal to or below their zero-overlap counterparts, overlap is
  pure cost for your corpus.
- **Stratum-specific effects.** A configuration that wins overall may
  lose on a specific query type. Weight accordingly.

**Document the trade-offs.** The winning configuration should be
justified with specific comparisons, not just "it had the highest
recall." State what it beat and by how much.

---

## Step 7: Validate with answer quality

Retrieval metrics tell you whether the right chunks were found. Answer
quality metrics tell you whether those chunks produced good answers.
A configuration that wins on retrieval but produces worse answers may
not be the right choice.

Run Ragas metrics on the winner and the runner-up:

| Metric | Winner config | Runner-up config | Delta |
|---|---|---|---|
| context_precision | | | |
| answer_relevancy | | | |
| faithfulness | | | |

**context_precision:** Are the retrieved chunks relevant to the
question? High recall with low context_precision means you are finding
the right document but the wrong section.

**answer_relevancy:** Does the generated answer address the question?
The VA CPG evaluation found that cross-encoder reranking improved
context_precision by 12.1% but reduced answer_relevancy by 7.9%,
showing that retrieval precision and answer-model affinity are
different optimization targets.

**faithfulness:** Is the answer grounded in the retrieved context? In
the VA CPG evaluation, faithfulness was stable across all retrieval
strategies (~0.84), suggesting it depends more on the answer model
than the chunking strategy.

**Decision rule:** If the retrieval winner also wins or ties on all
three Ragas metrics, ship it. If the runner-up wins on answer quality
by more than 5 points, investigate. Common causes: chunks too small
(answer model lacks context), chunks too large (answer model gets
distracted), or section-aware chunks that cross-cut topics.

**Time:** 1-2 hours for Ragas evaluation on two configurations.

---

## Step 8: Record in the data card

Populate the source's recipe with the winning configuration so the
platform can reproduce the index and future evaluations have a baseline.

**Recipe fields to set:**

```yaml
chunking:
  method: token_fixed     # or sentence, section_aware
  size: 512               # in tokens
  overlap: 0              # in tokens
  tokenizer: cl100k_base  # must match embedding model's tokenizer
  source_format: markdown  # or bioc_json, xml, plain_text
evaluation:
  recall_at_5: 0.680
  mrr_at_5: 0.321
  chunk_count: 15539
  sweep_configs_tested: 5
  sweep_results_path: eval/autorag/results/
```

**Link to the sweep results.** Store the full results table and Ragas
output in the eval directory. Future re-evaluations should compare
against this baseline. The bar for changing a production configuration
is "measurably better on the same evaluation dataset."

---

## Appendix: Source format case study -- BioC JSON vs. Markdown

PubMed Central articles are available as PDF, plain text, and BioC JSON
(via the NCBI BioC API). The source format you chunk from determines
what information is available for retrieval, independent of chunking
parameters.

**What BioC JSON preserves that markdown loses:**

| Feature | BioC JSON | Markdown (via Docling or similar) |
|---|---|---|
| Section type labels | INTRO, METHODS, RESULTS, DISCUSS, CONCL per passage | Lost. Headings survive but are not typed. |
| Passage boundaries | One paragraph = one passage, explicitly delimited | Inferred from blank lines, often incorrect |
| Citation metadata | DOI and PMID per reference passage | Lost or flattened to plain text |
| Figure/table captions | Typed passages with source file references | Partially preserved, no source file links |
| Passage type | title, paragraph, table, figure_caption, ref | All become undifferentiated text |

**Why this matters for retrieval:**

1. **Section-aware retrieval.** With `section_type` labels, the
   retrieval pipeline can boost or filter by section. A "what methods
   were used" query prioritizes METHODS chunks. Without section labels,
   every chunk competes equally regardless of its role in the document.

2. **Natural chunk boundaries.** BioC passages align with the author's
   paragraph structure, producing chunks that correspond to complete
   thoughts. Token-fixed chunking on markdown splits mid-paragraph or
   merges unrelated paragraphs depending on where the window falls.

3. **Citation grounding.** BioC reference passages carry DOI and PMID
   per citation. Markdown extraction flattens references to "[42]" with
   no machine-readable link.

4. **Passage-type filtering.** Figure captions, tables, and references
   are typed in BioC. Agents that need only narrative text can filter
   them out before retrieval. In markdown, everything is
   undifferentiated text.

**When to prefer structured formats:** Any time your source carries
explicit structural metadata and you want that metadata to inform
retrieval. The cost is a format-specific ingestion parser rather than
a generic markdown chunker.

**When markdown is sufficient:** When your source is unstructured text
(blog posts, transcripts, emails) or when Docling preserves enough
structure through headings and tables. The key question: does your
source format carry information that would be lost in extraction?

**This finding generalizes beyond BioC.** S1000D XML for maintenance
manuals, FHIR JSON for clinical data, structured HTML for legal
documents: any domain with structured source formats faces this same
trade-off.
