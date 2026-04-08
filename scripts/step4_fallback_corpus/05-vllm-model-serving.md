# Serving models with vLLM on OpenShift AI

Red Hat OpenShift AI uses **vLLM** as the primary inference runtime for
large language models. vLLM is an open-source, high-throughput inference
engine that supports continuous batching, PagedAttention for efficient
KV cache management, and a wide range of model architectures.

## Why vLLM

For large language model serving, the two things that matter most are
throughput (how many tokens per second can you serve at a given latency
budget) and cost (how much GPU memory and compute does it take). vLLM
optimizes both through PagedAttention, which treats the KV cache as a
paged virtual memory system and lets the runtime pack more concurrent
requests into the same GPU memory than naive approaches would allow.

On OpenShift AI, vLLM is deployed through the **KServe** model-serving
framework as a serving runtime. Cluster administrators install the
vLLM serving runtime once; data scientists then deploy models against
it by creating `InferenceService` resources.

## Supported model families

The vLLM serving runtime on OpenShift AI 3 supports a broad range of
open-weights model families, including:

- **Granite** (IBM's Granite family, including `granite-3.3-8b-instruct`
  and larger variants)
- **Llama** (Meta's Llama 3 and Llama 3.3 families)
- **Mistral** and **Mixtral**
- **Phi** (Microsoft's Phi family)
- **Qwen** (Alibaba's Qwen family)

In a default OpenShift AI 3 deployment, `granite-3.3-8b-instruct` is
pre-staged as a cluster-default small-fast model suitable for query
rewriting, function calling, and other latency-sensitive workflows.

## Deploying a model

To deploy a model with the vLLM runtime, create an `InferenceService`
resource in your project:

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: granite-3-8b
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      runtime: vllm-serving-runtime
      storageUri: oci://registry.redhat.io/rhelai1/granite-3-8b-instruct:latest
      resources:
        limits:
          nvidia.com/gpu: "1"
```

After applying this resource, the model is available at a per-service
route and can be called through the standard OpenAI-compatible chat
completions API. It also becomes available to Llama Stack and to
retrieval-hub as a cluster-resident LLM option.
