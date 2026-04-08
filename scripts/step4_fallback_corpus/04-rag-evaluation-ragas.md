# Evaluating RAG systems with Ragas in OpenShift AI

Retrieval-augmented generation (RAG) systems depend on two things
working well together: a retriever that finds relevant context for a
query, and a generator that produces grounded answers from that context.
Evaluating the whole system requires measuring both halves.

OpenShift AI ships a **Ragas** provider for the Llama Stack evaluation
API. Ragas is an open-source framework for evaluating RAG pipelines. It
provides a set of metrics specifically designed for RAG quality rather
than for classical information-retrieval ranking.

## Metrics the Ragas provider supports

The Ragas provider on OpenShift AI 3 computes the following per-case
metrics during an evaluation run:

- **Faithfulness** — whether the generated answer is grounded in the
  retrieved context. Measured by an LLM judge that checks whether each
  claim in the answer can be verified against the retrieved passages.
- **Answer relevancy** — whether the generated answer addresses the
  question. Uses a reverse-question generator: from the answer, generate
  a question that would elicit it, and measure the semantic similarity
  to the original question.
- **Context precision** — what fraction of the retrieved passages are
  actually relevant to answering the question.
- **Context recall** — what fraction of the information needed to
  answer the question is present in the retrieved passages.
- **Answer correctness** — how well the generated answer matches a
  reference ground-truth answer, combining factual accuracy and
  semantic similarity.

## What Ragas does NOT compute

Ragas is a **RAG-quality** framework, not a classical information
retrieval framework. Metrics like **Recall@k**, **MRR** (Mean Reciprocal
Rank), and **NDCG** (Normalized Discounted Cumulative Gain) are
classical IR metrics that measure ranking quality. They are not in the
Ragas metric set.

If you need classical IR ranking metrics in addition to Ragas quality
metrics, compute them separately before calling the evaluation API.

## Running a Ragas evaluation

Llama Stack's evaluation API is exposed at `/v1alpha/eval` (the API is
still in v1alpha). Benchmark registration and evaluation invocation go
through the Python client's `client.alpha.*` namespace:

```python
from llama_stack_client import LlamaStackClient

client = LlamaStackClient(base_url="http://llamastack.example.com")

client.alpha.benchmarks.register(
    benchmark_id="rag-eval-1",
    dataset_id="my-qa-dataset",
    scoring_functions=[
        "ragas::faithfulness",
        "ragas::answer_relevancy",
        "ragas::context_precision",
    ],
    provider_id="ragas",
)

job = client.alpha.eval.run_eval(
    benchmark_id="rag-eval-1",
    benchmark_config={
        "eval_candidate": {
            "type": "model",
            "model": "ollama/granite3.3:2b",
        },
        "num_examples": 100,
    },
)
```

The call is asynchronous; poll `client.alpha.eval.jobs.status(job_id=...)`
to check progress and `client.alpha.eval.jobs.retrieve(...)` to fetch
the final result.
