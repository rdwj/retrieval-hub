# Next Session — code-source

## Next: Build and validate the code-family adapter using this repo as first worked example

Can RetrievalHub ingest a live Python codebase with AST-aware chunking and code-specific embeddings, and produce retrieval results that genuinely help an agent understand the code? This session answers that question using the retrieval-hub repo itself as the test subject.

1. **Build the AST-aware code chunker** (`src/retrieval_hub/ingestion/chunking/ast_treesitter.py`)
   Use tree-sitter with the cAST algorithm (recursive AST splitting, sibling merging, scope ancestry headers). Target ~512 tokens per chunk. Must produce `Chunk` objects compatible with the existing pipeline. See `research-code-source-adapter.md` for the cAST paper and the `code-chunk` / `astchunk` libraries. Start with Python grammar only; the tree-sitter approach generalizes to other languages by adding grammars.

2. **Deploy jina-code-embeddings as a shared TEI service**
   Follow the PubMedBERT TEI deployment pattern (`deploy/openshift/retrieval-hub/embedding/tei.yaml`). Model: `jinaai/jina-code-embeddings-0.5b` (494M params, 896 dims, 32K sequence). Deploy alongside PubMedBERT — separate Deployment + PVC, same namespace. Each source family declares its embedding model; the platform serves it.

3. **Write the code ingestion script** (`scripts/ingest_code_repo.py`)
   Accept `--repo` (local path or GitHub URL), `--ref` (branch/tag/commit, default `main`), `--slug`. Clone if remote, walk the tree, AST-chunk Python files, embed with jina-code-embeddings, write to pgvector. Register as family `code` with appropriate usage rules ("This index was built from commit {sha} on branch {branch}. Code may have changed.").

4. **Ingest this repo and evaluate retrieval quality**
   Run the ingestion against `retrieval-hub/` itself. Then test retrieval with questions an AI engineer would ask:
   - "How does the ingestion pipeline work?"
   - "Where is the DocumentAdapter defined?"
   - "Show me the query rewriter design"
   - "What embedding models does RetrievalHub support?"
   Compare results to what Claude Code finds via grep/read — the vector search should surface relevant code that an agent would otherwise need multi-step exploration to find.

5. **Assess: does this work, and what breaks?**
   Honest evaluation. If retrieval quality is poor, document why (wrong chunk boundaries? embedding model not matching? code too interconnected for isolated chunks?). If it works, register the source in the catalog and exercise it via the MCP server.

**Sequencing.** Items 1-2 are independent (chunker + embedding model). Item 3 depends on both. Item 4 depends on 3. Item 5 is the judgment call that determines whether the code family ships or needs redesign.

**Constraints for the session:**
- The `code` family enum value already exists in `SourceFamily` but no adapter exists yet
- The retrieval API dispatch (`_build_adapter` in `api.py`) needs a `SourceFamily.CODE` case
- jina-code-embeddings uses no prefix convention (like PubMedBERT) — our configurable prefix system handles this
- The gpt-oss-120b cluster may be resource-constrained (4 GPUs used by the 120B model, TEI runs on CPU)

**Session start protocol:**
- Premise checks (before item 1, ~5 min):
  - Verify gpt-oss-120b cluster is accessible and retrieval-hub namespace is intact (`oc get pods --context=gpt-oss-120b -n retrieval-hub`)
  - Verify port-forward to catalog DB works (or the BFF pod can be exec'd into)
  - Check if `tree-sitter` and `tree-sitter-python` are pip-installable in the project venv
  - Check if jina-code-embeddings-0.5b is available on HuggingFace and TEI-compatible
- Rules with history:
  - Embedding models are shared cluster resources, not per-service dependencies (see `design-shared-model-serving` memory). Deploy jina-code as a TEI service, don't bake it into containers.
  - Usage rules ride with every retrieval (see `design-usage-rules-with-data` memory). Code sources need different rules than clinical docs.
- Stop-and-ask before: deploying a new TEI instance that might conflict with existing PVCs (check node scheduling); modifying the existing document adapter or MCP server (the clinical demo must keep working)
- Close ritual: session summary to `session-summaries/`; if the code adapter works, update the onboarding journey doc with lessons learned

**Loop design:** Not loop-shaped. This is exploratory — the outcome determines whether we ship the code family or redesign it.

## What landed last session (2026-08-14)

Full MVP vertical deployed on gpt-oss-120b: PostgreSQL+pgvector, MCP server (FastMCP 4), BFF, live UI with real data, playground with 120B LLM generation. VA CPG corpus: 52 docs, 6,500 chunks, PubMedBERT embeddings, AutoRAG-validated chunking (Token-512-0), usage rules + data freshness, eval results in catalog. TEI deployed as shared PubMedBERT service. See `session-summaries/2026-08-14-mvp-vertical-va-cpg.md`.

**Key design principles established:**
- Embedding models are shared cluster infrastructure
- Usage rules ride with every retrieval
- Data freshness cards follow the CDC pattern
- Source owner controls citation/handling rules

## Watch out for

- The existing demo on gpt-oss-120b must keep working — don't break the VA CPG source or MCP server while adding code support
- The cluster is a sandbox that could be reclaimed — the work products (code, manifests, scripts) are the durable output, not the deployment
- This session's uncommitted changes from the MVP build should be committed first — 15 modified files + 15 new packages/dirs
- jina-code-embeddings is decoder-based (Qwen2.5-Coder backbone) — TEI's CPU image may or may not support it; verify before deploying

## If blocked

- If tree-sitter AST chunking proves too complex to integrate in one session, fall back to the `code-chunk` library (pre-built, pip-installable)
- If jina-code-embeddings doesn't work with TEI CPU, use sentence-transformers in-process (same pattern as PubMedBERT MVP)
- If code retrieval quality is poor with vector search alone, consider augmenting with GitHub MCP server's `search_code` as a fallback retrieval pattern
