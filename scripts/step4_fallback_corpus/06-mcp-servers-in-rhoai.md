# MCP servers in OpenShift AI 3

The Model Context Protocol (MCP) is a standard for agent-to-tool
communication developed by Anthropic and adopted as a first-class
primitive in OpenShift AI 3. MCP servers expose tools that agents can
discover and invoke — a clean separation between agent logic (LLM
inference + reasoning) and tool implementations (retrieval, database
access, code execution, etc.).

## How MCP fits into OpenShift AI

OpenShift AI 3 supports MCP servers as deployable components that show
up in the **AI Assets** catalog alongside other approved AI building
blocks (models, agents, knowledge sources, guardrails). Cluster
administrators review and approve MCP servers for use by agent
developers; approved servers become discoverable through the catalog.

Agent runtimes on the cluster — Llama Stack, Kagenti-hosted agents,
and others — connect to approved MCP servers through one of several
registration mechanisms:

1. **Llama Stack toolgroups** — the MCP server is registered as a
   toolgroup with `provider_id=model-context-protocol`. Tools become
   visible to Llama Stack agents as `<toolgroup_id>::<tool_name>`.
2. **Kagenti MCP Gateway** — the MCP server is registered as a backend
   behind the cluster's Envoy-based MCP Gateway via an `MCPServer`
   custom resource. The gateway applies tool prefixing and handles
   audience-scoped token exchange.
3. **Direct connection** — for off-cluster consumers or development
   use cases, agents can connect directly to an MCP server's route
   with a valid JWT.

## Streamable-HTTP transport

Modern MCP servers on OpenShift AI use **streamable-HTTP** as the
transport. The older SSE (Server-Sent Events) transport is deprecated
in favor of streamable-HTTP because it supports bidirectional streaming
cleanly and integrates better with standard HTTP infrastructure.

Agent runtimes, gateways, and retrieval-hub itself all use
streamable-HTTP. Developers building new MCP servers should target
streamable-HTTP from day one.

## Developing an MCP server

Red Hat's **fips-agents** project provides a template for building
FIPS-compliant MCP servers on Red Hat UBI 9 base images. The template
scaffolds a FastMCP 3 project with tests, a Containerfile, OpenShift
manifests, and a set of slash-command workflows (`/plan-tools`,
`/create-tools`, `/exercise-tools`, `/deploy-mcp`) that walk the
developer through tool design, implementation, and deployment.

See the fips-agents documentation for the full template and workflow.
