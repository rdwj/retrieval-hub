# Data Owner's Guide to Onboarding a Dataset

You have a corpus of documents. You want AI agents to be able to search it,
retrieve relevant passages, and cite them properly. This guide walks you
through what you need to provide and decide.

RetrievalHub handles the infrastructure: vector storage, embedding, query
rewriting, and a single MCP server that serves all sources to any connected
agent. Your job is to describe your data, define how agents should use it,
and validate that retrieval quality meets your standards.

For a worked example of this process with the VA/DoD Clinical Practice
Guidelines, see [onboarding-journey-va-cpg.md](onboarding-journey-va-cpg.md).

## Getting started

Scaffold your ingestion script first. This generates a complete template
with all required fields, guidance comments, and the full pipeline:

```bash
make new-source SLUG=my-data-source

# Or with explicit name and family:
make new-source SLUG=my-data-source NAME="My Data Source" FAMILY=clinical_document
```

This creates `scripts/ingest_my_data_source.py` with TODO placeholders for
every field you need to fill in. The rest of this guide explains what each
field means and how to choose good values.

## What you will need

Before you begin, gather:

- **Your corpus** in a machine-readable format (extracted Markdown, BioC
  JSON, or structured text). If your source is PDFs, the platform team can
  help set up a Docling extraction pipeline.
- **Source URLs** for each document, so retrieval results can link back to
  the original. A JSON mapping file works well (see the VA CPG
  `pdf-urls.json` for an example).
- **30-50 evaluation queries** with known answers and the source document
  that contains each answer. These are essential for measuring retrieval
  quality. Include both expert-register and lay-register queries if your
  audience spans both.
- **Governance rules** for your content: citation requirements, scope
  disclaimers, handling constraints. You are the authority on how your data
  should be presented.
- **Contact information** for your team so the platform knows who owns the
  source.

## Step 1: Prepare your corpus

The ingestion pipeline reads from a local directory of extracted documents.
Each document becomes one or more searchable chunks.

**Format requirements.** The pipeline supports Markdown (for general
documents) and BioC JSON (for biomedical literature with section-level
structure). If your source is in another format, talk to the platform team
about adding a parser.

**Organize by category.** If your documents span multiple topics or
categories, organize them in subdirectories. The directory structure becomes
part of the document metadata, which helps with retrieval and filtering.

**Provenance matters.** Each document should be traceable to its original
source. Provide a URL mapping so that retrieved chunks include a link to the
authoritative document. Agents use this for citation, and users use it to
verify answers.

## Step 2: Define governance rules

Governance rules travel with every retrieval response. Any agent querying
your source will see these rules and is expected to follow them. Define
them before ingestion so they are part of the source record from day one.

You define four categories:

**Citation.** How should agents cite your content? Include the expected
format: source URL, document title, section, recommendation number, or
whatever makes sense for your corpus. Example: "Always cite the VA.gov
source URL along with the CPG title, section, and recommendation number."

**Scope disclaimer.** What should agents say about the limits of your data?
If your guidelines come from a specific organization, note that other
organizations may have different recommendations. If your data has a known
coverage gap, say so here.

**Handling constraints.** How should agents treat your content? Clinical
data might require a "does not replace clinical judgment" disclaimer.
Legal data might require noting jurisdiction. Internal documentation might
require noting that it reflects a point in time.

**Custom rules.** Any source-specific instructions. Examples: "Always
include the recommendation strength rating when citing a recommendation."
"If the retrieved content does not address the user's question, say so
explicitly."

**Data freshness.** When was this data last refreshed? How often is it
updated? Where can users find the most current version? This metadata
helps agents qualify their answers with appropriate freshness caveats.

### Governance template

```yaml
citation: >
  [How agents should cite this source. Include expected format.]

scope_disclaimer: >
  [What agents should say about the limits and provenance of this data.]

handling: >
  [Constraints on how agents should present this content.]

custom_rules:
  - [Source-specific rule 1]
  - [Source-specific rule 2]

data_freshness:
  source_name: [Authoritative source name]
  source_url: [Primary URL]
  last_refreshed: [YYYY-MM-DD]
  refresh_cadence: [on_demand | daily | weekly | monthly | quarterly]
  staleness_note: >
    [Human-readable note about when this data might become outdated.]
```

## Step 3: Write evaluation queries

Evaluation queries are how you and the platform measure retrieval quality.
Without them, there is no way to tell whether the system is returning the
right content for your users' questions.

**What to include for each query:**
- The question itself
- A reference answer (what a correct response should contain)
- The source document and section where the answer lives
- The language register: "clinical" for expert terminology, "lay" for
  everyday language
- A category or topic tag for stratified analysis

**Coverage.** Aim for 30-50 queries that span the breadth of your corpus.
If your corpus covers 10 topics, include queries from each. If your
audience includes both experts and non-experts, include both registers.

**Quality over quantity.** A smaller set of well-crafted queries with
verified reference answers is more useful than a large set with uncertain
ground truth. Each query should have a clear, verifiable answer in your
corpus.

The platform stores these as a JSON dataset. See
`eval/autorag/qa_dataset_draft.json` for the format used by the VA CPG
source.

## Step 4: Configure the semantic layer (optional)

The semantic layer improves retrieval for sources with specialized
terminology. It has two parts: vocabulary mappings for the query rewriter,
and entity definitions for cross-reference navigation.

**Vocabulary mappings.** If your users might search with different
terminology than your documents use, define lay-to-canonical term mappings.
The query rewriter uses these to translate user queries before retrieval.
For clinical data, this means mapping "high blood pressure" to
"hypertension" and "shell shock" to "post-traumatic stress disorder."

**Entity definitions and relationships.** If your corpus contains named
concepts that relate to each other, define them. Conditions, treatments,
instruments, and their connections (comorbidity, treats, screens_for) help
the refine tool navigate between related content across documents.

**Abbreviation expansions.** If your domain uses abbreviations heavily,
provide an expansion dictionary. The rewriter uses this alongside
vocabulary mappings.

This step is optional for the initial onboarding. You can add the semantic
layer after the source is live and you have seen which queries perform
poorly.

## Step 5: Choose chunking and embedding

The platform team will help you run experiments to find the best chunking
strategy and embedding model for your data. Your involvement is reviewing
results and making the final call.

**Chunking.** Documents are split into fixed-size token chunks for
retrieval. The two main parameters are chunk size (256, 512, or 1024
tokens) and overlap (0 or 64 tokens). The platform runs a sweep across
configurations and reports hit rate and ranking quality for each. You
review the results and pick the winner.

One finding from our evaluations so far: the best configuration varies by
corpus. The VA CPG guidelines performed best at 512 tokens with zero
overlap. The PubMed hypertension articles performed best at 256 tokens with
zero overlap using section-aware chunking. There is no universal default.

**Embedding model.** The embedding model determines how text is represented
in vector space and has a large effect on retrieval quality. The right
model depends on your corpus, not your domain. In our testing, a
general-purpose model (nomic-embed-text-v1.5) outperformed a
domain-specific biomedical model (PubMedBERT) on clinical guidelines. The
only way to know which model works best for your data is to run the
comparison.

The platform runs the embedding comparison using your evaluation queries
and reports context precision, answer relevancy, and hit rate for each
candidate. You review the results and approve the final choice.

**What you hand to ops.** Once the chunking and embedding choices are made,
the data owner hands the ops team a requirements summary: the embedding
model name, its memory footprint, and any prefix conventions it requires.
Ops is responsible for hosting the model. Consuming agents never see which
model is used.

## Step 6: Review evaluation results

After ingestion with the chosen configuration, the platform runs a formal
evaluation using your queries. The eval pipeline measures:

- **Context precision.** Are the retrieved chunks relevant and well-ranked?
- **Answer relevancy.** Do answers generated from retrieved context address
  the question?
- **Faithfulness.** Are generated answers grounded in the retrieved content?
- **Hit rate and MRR.** Does retrieval find the right source document?

Results are broken down by language register (lay vs. expert) and by
category if your queries are tagged. Review the per-query results to spot
problem areas: queries where retrieval finds the wrong document, or where
the right document is retrieved but poorly ranked.

If results are below your quality bar, the platform team can iterate on
chunking, embedding model, or semantic layer configuration. The eval
pipeline makes this a structured comparison, not guesswork.

## Step 7: Hand off to ops

Once you approve the eval results, provide ops with:

1. **The ingestion script** (the platform team writes this with you; it
   encodes all your pipeline decisions)
2. **Embedding model requirements:** model name, memory estimate (~3x the
   on-disk weight), and any prefix conventions
3. **Refresh schedule:** how often the corpus should be re-ingested (on
   demand, monthly, quarterly)
4. **Contact information** for questions about the source

Ops runs the ingestion, deploys the embedding model if it isn't already
hosted, and verifies the source appears in the catalog. You do a final
verification by running sample queries against the live MCP server.

## After onboarding

**Content updates.** When your source documents change, re-run the
ingestion script. The platform handles recipe versioning: the new index
replaces the old one, and agents see the updated content immediately. No
deployment is needed.

**Quality monitoring.** Re-run the evaluation periodically, especially
after content updates, to catch regressions. If a content update changes
the terminology or structure significantly, the semantic layer may need
updating too.

**Governance updates.** If your citation requirements or disclaimers
change, update the governance rules. These are stored on the source
record and can be updated independently of the content.
