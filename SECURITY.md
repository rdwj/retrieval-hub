# Security Policy

retrieval-hub is a retrieval platform for AI agents running on OpenShift. It manages access to data sources on behalf of agents and users under a scoped, governed model. Taking vulnerability reports seriously is a first-class concern.

**Please do not file public GitHub issues for security vulnerabilities.**

Report vulnerabilities privately through GitHub's private vulnerability reporting:

- Go to the repository **Security** tab and select **Report a vulnerability**
- Or navigate directly to `https://github.com/rdwj/retrieval-hub/security/advisories/new`

If for any reason you cannot use GitHub's reporting flow, open a minimal public issue asking for a private contact channel (without disclosing details of the vulnerability).

When reporting, please include:

- A description of the issue and the affected component (`retrieval_hub` core library, `retrieval-hub-mcp`, `retrieval-hub-auth`, `retrieval-hub-ui`, or the deploy manifests)
- Steps to reproduce or a minimal proof of concept
- The version or commit SHA you observed the issue on
- The impact you believe the issue has (confidentiality, integrity, availability; scoped or cross-tenant)

You should receive an acknowledgement within a few business days. We will work with you to confirm the issue, assess impact, and coordinate a fix and disclosure timeline.

## Supported Versions

retrieval-hub is pre-1.0 and under active development. Fixes are applied to `main`; only the latest release of each published package receives security updates:

| Package | Supported |
|---------|-----------|
| `retrieval-hub` (core library) | Latest release |
| `retrieval-hub-mcp` | Latest deployed revision |
| `retrieval-hub-auth` | Latest deployed revision |
| Others | `main` branch only |

## Scope

In scope:

- Authentication and authorization bypass
- Source access policy violations (cross-scope data access)
- Credential or token leakage
- Injection vulnerabilities in MCP tools, the auth server, or the UI BFF
- Provenance or content integrity bypass (forged signatures, tampered content hashes)
- Container or deployment misconfigurations that weaken FIPS or compliance posture

Out of scope:

- Findings that require compromising the underlying OpenShift cluster or PostgreSQL instance
- Denial-of-service via resource exhaustion against unauthenticated endpoints (rate limiting is a deployment concern)
- Issues only reproducible against example or scaffold code in `scripts/` or sample datasets
- Best-practice recommendations without a demonstrated impact

## Disclosure

We prefer coordinated disclosure. Once a fix is available, we will credit the reporter (unless anonymity is requested) in the release notes and any GitHub Security Advisory published for the issue.
