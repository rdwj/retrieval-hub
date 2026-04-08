# Red Hat Enterprise Linux AI and InstructLab

Red Hat Enterprise Linux AI (RHEL AI) is a foundation model platform
that provides a curated, supported environment for serving, fine-tuning,
and aligning large language models. It pairs with OpenShift AI to cover
the full AI stack: RHEL AI for model-level work, OpenShift AI for
application-level AI workloads running on a cluster.

## What RHEL AI includes

A RHEL AI install provides:

- **Granite foundation models** from IBM, pre-packaged and optimized
  for the Red Hat AI ecosystem
- **vLLM** for high-throughput inference on single nodes
- **The InstructLab toolchain** for aligning and fine-tuning open
  models with synthetic data
- A **bootable image** that includes all of the above plus the OS,
  so a compatible server can go from bare metal to serving a model
  in minutes

RHEL AI runs on supported hardware that includes NVIDIA, AMD, and Intel
accelerators. For clusters, RHEL AI nodes typically feed OpenShift AI
as part of a model-training or model-serving workflow.

## InstructLab and synthetic data generation

**InstructLab** is the toolchain RHEL AI uses for fine-tuning and
aligning open LLMs without requiring large human-curated datasets. It
uses a **synthetic data generation** approach: a taxonomy of skills
and knowledge, paired with a small number of seed examples per leaf,
is expanded into a much larger training dataset by a teacher LLM. The
expanded dataset is then used to fine-tune the target model via LoRA
or full-weight adaptation.

Red Hat maintains the **SDG Hub** — a hub of reusable synthetic-data-
generation recipes that customers can apply to their own domain
content. Recipes cover Q&A generation, summary generation, reasoning
traces, and other common fine-tuning task formats.

## How RHEL AI relates to OpenShift AI

RHEL AI and OpenShift AI are designed to work together but serve
different stages of the AI lifecycle:

- **RHEL AI** is where foundation models are **prepared** — pre-training
  validation, fine-tuning, alignment, benchmarking.
- **OpenShift AI** is where prepared models are **served and consumed**
  by applications — deployed via KServe + vLLM, orchestrated through
  pipelines, exposed through agents and retrieval systems.

A typical customer flow: fine-tune a Granite model on RHEL AI using
InstructLab with domain-specific SDG recipes, export the resulting
model, deploy it to OpenShift AI via KServe, and then make it
available to Llama Stack agents and retrieval-hub query rewriters as
a cluster-resident LLM.
