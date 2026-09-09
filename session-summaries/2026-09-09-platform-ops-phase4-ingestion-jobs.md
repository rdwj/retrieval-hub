# Session Summary: Platform-Ops Phase 4 — Production Ingestion Runners

**Date:** 2026-09-09
**Epic:** Platform Ops (operational reliability and deployment catchup)
**Phase:** 4 (final)
**Issue:** #27 (closed)

## What shipped

Production ingestion runners: sources can now be re-ingested via
`oc create -f` in-cluster, without local port-forwards.

### Deliverables

1. **Ingestion container image** (`retrieval-hub-ingestion/`)
   - Containerfile: UBI9 Python 3.11, core library (no [ingest] extras),
     scripts, optional baked-in source data
   - deploy.sh: Binary build script with `--source=<slug>` for data staging
   - BuildConfig + ImageStream in OpenShift

2. **Hetionet Job manifest** (`ingestion-job-hetionet.yaml`)
   - Concrete, tested Job that re-ingests the hetionet hypertension subgraph
   - Connects to in-cluster PG, vLLM, and Memgraph via service DNS
   - Completed in 9 seconds (resume mode skipped already-embedded chunks)
   - Data verified queryable via MCP server

3. **TEI cooldown removal** (`embed.py`)
   - Removed 5s/50-batch and 0.5s inter-batch sleeps (TEI memory-leak
     workarounds no longer needed with vLLM)
   - Retry backoff preserved

4. **Lazy imports for code_ast** (`pipeline.py`, `chunking/__init__.py`)
   - Fixed: tree-sitter was eagerly imported at pipeline import time,
     crashing the ingestion container (which doesn't need tree-sitter
     for graph/document families)
   - Lesson learned added to CLAUDE.md

### What we decided NOT to do

- **Health probe changes**: Already working correctly; Error pods were from
  transient PubMedBERT TEI unavailability, not probe bugs
- **Generalized Job template**: Start with concrete per-source Jobs, generalize
  later if the pattern proves out
- **Docling-enabled image variant**: Document family sources needing Docling
  parsing require a heavier image; out of scope for this session

## Commits

- 6082fbd: feat: Add in-cluster ingestion Job runner (#27)

## Epic status

All platform-ops issues now closed:
- #27: Production ingestion runners (this session)
- #66: TEI memory leak (replaced by vLLM, session 2026-09-09)
- #67: Checkpoint-resume (session 2026-09-09)
- #70: MCP server deploy catchup (session 2026-09-09)

**Epic complete.** Run `/retro platform-ops` to close out.
