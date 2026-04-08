# Red Hat OpenShift AI 3 Overview

Red Hat OpenShift AI is an integrated artificial intelligence and machine
learning platform built on Red Hat OpenShift. It provides a consistent,
scalable foundation for building, deploying, and managing AI-enabled
applications across hybrid cloud environments.

## What's new in OpenShift AI 3

OpenShift AI 3 introduces a number of platform-level changes aimed at
making generative AI workloads first-class on the cluster. The headline
additions include a new **AI Hub** experience for discovering approved
models and AI assets, a **gen AI Studio** for interactive experimentation,
and built-in support for running **Llama Stack** as a supported
Technology Preview component alongside existing model-serving and
pipeline capabilities.

OpenShift AI 3 is available in two editions: **OpenShift AI
Self-Managed**, which customers deploy and operate on their own clusters,
and **OpenShift AI Cloud Service**, which Red Hat manages.

## Core capabilities

Operators, data scientists, and AI engineers use OpenShift AI to:

- Serve large language models (LLMs) and traditional ML models using
  vLLM, Triton, and other runtimes through the KServe integration.
- Run data science workbenches with Jupyter notebooks, pre-configured
  with common ML libraries and access to cluster compute resources.
- Build training and inference pipelines using Kubeflow Pipelines and
  Tekton-backed automation.
- Manage and govern AI assets — models, agents, MCP servers, and
  knowledge sources — through the AI Hub and the new AI Assets catalog.
- Integrate with the broader Red Hat AI ecosystem including Red Hat
  Enterprise Linux AI (RHEL AI) and the InstructLab fine-tuning tools.

## Supported components vs Technology Preview

OpenShift AI 3 distinguishes between **supported** components (covered
by Red Hat's standard subscription support) and **Technology Preview**
components (provided for early evaluation without production support
commitments). Llama Stack, MCP server management, and the AI Assets
catalog are currently Technology Preview. Core model serving and
pipeline capabilities are fully supported.
