# Reconciliation — 2026-08-18 · backlog sweep

**Range:** All open issues filed 2026-04-08, never updated. Triggered by code-source epic close + query-rewriter epic bootstrap.  
**Plan:** NEXT_SESSION-query-rewriter.md

## Backlog reconciled

| # | Was | Action | Why |
|---|-----|--------|-----|
| #10 | Run --try-network against docs.redhat.com | Closed | Superseded by real-world pipeline validation (VA CPG, code repos) |
| #16 | Wikipedia + public code repos corpora | Closed | Code repos done (9b548c6). Wikipedia can be re-filed standalone if needed |
| #17 | SDK peer component | Kept | Still valid, not urgent |
| #18 | CLI peer component | Kept | Still valid, depends on SDK |
| #19 | UI stage 3: SPA + BFF | Re-scoped | BFF partially landed (2adf1b2). Updated body to reflect what exists vs what remains |
| #20 | LlamaStack integration | Kept | Depends on cluster availability |
| #21 | MLflow integration | Kept | Round-2 for rewriter; standalone fallback is round-1 |
| #22 | Kagenti integration | Kept | Depends on Kagenti presence on cluster |
| #23 | Grafana dashboard JSON | Kept | Low effort, good filler |
| #24 | Keycloak realm example | Kept | Low priority until multi-tenant |
| #25 | Operator with CRDs | Kept | Explicitly deferred in its own description |
| #26 | Full cluster deploy manifests | Re-scoped | Partial manifests exist. Updated body to inventory what's there vs missing |
| #27 | Production ingestion runners | Kept | Hand-run scripts still fine |

## Critique

On track. The project has shipped steadily (core library, MCP server, two source families, cluster deploy) while these issues sat untouched. The backlog was filed as a batch roadmap dump in April and never triaged against actual progress. This reconciliation brings it current. No recurring friction pattern -- this is a first-time cleanup.

## Guidance for next

Query rewriter epic is bootstrapped and the next session is planned. The remaining 11 open issues are all valid but none are urgent blockers for the rewriter work. Revisit after the rewriter epic lands.
