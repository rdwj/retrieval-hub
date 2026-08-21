# Session Summary — 2026-08-20 · refine-tool · Tale of Two Cities ingestion + entity-arc validation

**Plan:** NEXT_SESSION-refine-tool.md (Tale ingestion steps 1-3)   **Commits:** pending
**Deployed:** dev (route fix + einops + memory limit)   **Model:** Claude Opus 4.6 (1M)

## Plan vs. actual
Planned: ingest Tale of Two Cities, define semantic context, validate entity-arc. Shipped: all three steps plus three deployment fixes discovered during validation.
Scope: expanded to include deployed MCP server fixes (trailing-slash route, missing einops dep, OOMKill memory limit) discovered when the user tested from a separate project.

## Shipped
- Ingestion script for Tale of Two Cities (376 chunks, 192K tokens, Nomic v1.5)
- Semantic context seeder (9 characters with aliases, 8 relationships, 3 refinement strategies)
- Entity-arc validation: Sydney Carton arc (idle lawyer → sacrifice), Evrémonde alias resolution (→ Darnay), Doctor Manette arc (imprisonment → recovery → Bastille account)
- Route path fix: `/mcp/` → `/mcp` in openshift.yaml and deploy.sh (was causing 503 via redirect loop)
- Added `einops>=0.7` to container requirements (Nomic v1.5 runtime dep)
- Memory limit 2Gi → 4Gi for MCP server pod (Nomic model OOMKilled at 2Gi)
- CLAUDE.md with three lessons learned

## Verification & confidence
- Ingestion verified: chunk counts, doc_section population, chunk_index ordering checked via direct SQL
- Entity-arc verified: three queries via mcp-test-mcp against local MCP server, all returned coherent narrative arcs in chunk_index order
- Deployment fixes verified: curl tests confirmed 200 on POST /mcp; pod survived model load with 0 restarts at 4Gi
- Confidence: high for ingestion and entity-arc; high for deployment fixes (tested live)

## Judgment calls & deviations
- Chose Nomic v1.5 over PubMedBERT for the fiction corpus — general-purpose model for non-biomedical text, also happens to be the system default in embed.py
- Chapter numbers repeat across books in doc_section (e.g., "CHAPTER I." in all three books) because Docling's HTML→markdown conversion flattens the heading hierarchy. Accepted for now — entity-arc uses chunk_index, not doc_section
- Wrote scripts directly after sub-agent API errors, rather than retrying delegation

## Backlog delta
Filed: none. Closed: none. Memory: `feedback-container-deploy-checks` (new).

## Drift & forward-collisions
- Backward: #33 (stable chunk identifiers) — still valid, not affected by this session
- Forward: none

## For the reviewer
- Sanity-check: the 4Gi memory limit — is that enough headroom long-term, or should we plan for TEI serving (design-shared-model-serving memory) to avoid in-process model loading?
- Thin verification: Tale of Two Cities data only exists in local databases, not the deployed cluster PostgreSQL. Entity-arc on the deployed server untested for this source.
- Wants guidance: none

## Risks / watch-fors
- Deploying new embedding models will hit the same einops/OOM pattern. The CLAUDE.md lessons should prevent it, but a pre-deploy checklist or CI step would be more reliable.
- doc_section ambiguity (repeated chapter numbers) could confuse the section refinement strategy for multi-book works. Not a problem today but worth noting if more literary sources are ingested.
