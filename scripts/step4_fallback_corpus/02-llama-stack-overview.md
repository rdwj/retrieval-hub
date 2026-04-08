# Working with Llama Stack in OpenShift AI 3

Llama Stack is a unified, OpenAI-compatible API surface for building AI
agent applications. It ships in OpenShift AI 3 as a Technology Preview
component, deployed via the **Llama Stack Operator** and the
`LlamaStackDistribution` custom resource.

## Why Llama Stack

A typical agent application needs to combine model inference, tool
calling, vector storage, retrieval, evaluation, telemetry, and safety
checks. Each of these has its own SDK, its own auth story, and its own
ways of failing in production. Llama Stack provides a consistent API
surface across all of them so an agent developer can target one API and
still swap the underlying provider later.

On OpenShift AI 3, Llama Stack is deployed into a dedicated namespace by
the Llama Stack Operator. The operator watches for `LlamaStackDistribution`
custom resources, each of which declares a distribution image, replicas,
the vector-store backend (Milvus by default, FAISS inline, or pgvector
external), and a `run.yaml` configuration block.

## The APIs Llama Stack exposes

Llama Stack 0.3.x and later expose the following OpenAI-compatible APIs:

- **Inference**: `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`,
  `/v1/messages`
- **Vector stores**: `/v1/vector_stores`, `/v1/files` — for simple
  "upload PDFs, run file search" workflows
- **Tool groups**: `/v1/toolgroups` — register external MCP servers as
  toolgroups that agents can discover and invoke
- **Evaluation**: `/v1alpha/eval` — asynchronous benchmark execution
  with pluggable scoring providers (Ragas is the provider shipped with
  OpenShift AI for RAG-quality metrics)
- **Telemetry**: `/v1/telemetry/events` for OpenTelemetry-compatible
  tracing with W3C Trace Context propagation

## Enabling Llama Stack on your cluster

Llama Stack is not enabled by default on OpenShift AI 3. A cluster
administrator enables it by activating the Llama Stack Operator through
the OpenShift AI dashboard or by applying the operator's Subscription
manifest directly. Once the operator is running, AI engineers can create
`LlamaStackDistribution` resources in their own namespaces to bring up
Llama Stack instances.

See Chapter 2 of the *Working with Llama Stack* guide for step-by-step
activation instructions and the model-preload prerequisites.
