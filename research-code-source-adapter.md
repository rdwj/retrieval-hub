# Research: Code Source Family Adapter for RetrievalHub

**Date:** 2026-08-14

## Summary

Building a code-family adapter for RetrievalHub is feasible and the ecosystem is mature. The recommended approach is a **hybrid architecture**: AST-aware chunking via tree-sitter for the vector index (handles "find code related to X" queries), combined with **GitHub's official MCP server for live file access** at specific branches/refs (handles "show me the current implementation of Y"). This dual approach solves the freshness problem — the vector index provides semantic search, while the GitHub MCP server provides up-to-the-commit file access. For embedding, jina-code-embeddings (0.5B) is the best self-hostable option, outperforming general-purpose models on code retrieval by 5+ percentage points.

**Recommendation:** Build the code adapter with three layers: (1) AST-chunked vector index for semantic search, (2) GitHub API integration for live file/branch access, (3) periodic re-indexing via webhook or cron with Merkle-tree-based incremental updates. For the first worked example (this repo), start with layer 1 to validate the retrieval quality, then add layer 2 for freshness.

## Architecture Options

| Approach | Freshness | Retrieval Quality | Complexity | Best For |
|---|---|---|---|---|
| **Static vector index** (re-index on demand) | Low (stale until re-run) | High (AST-aware, code embeddings) | Low | Stable codebases, reference docs |
| **Live GitHub API** (fetch on query) | Perfect (real-time) | Low (no semantic search, just file fetch) | Low | "Show me file X" queries |
| **Hybrid: vector index + live API** | Good (index for search, API for current) | High | Medium | **Recommended for RetrievalHub** |
| **Knowledge graph** (Codebase-Memory style) | Medium (rebuild on change) | Highest (structural relationships) | High | Large monorepos, cross-file navigation |
| **Incremental re-index** (webhook/Merkle tree) | Near-real-time | High | Medium-High | Active development repos |

## A. Code Parsing and Chunking

### cAST (tree-sitter AST chunking) — the clear winner

The [cAST paper](https://arxiv.org/html/2506.15655v1) (EMNLP 2025, CMU + Augment Code) established the state of the art: recursive AST-based chunking that splits large nodes and merges siblings while respecting a size budget. Results: **+4.3 points on Recall@5** vs. naive chunking on RepoEval.

Key design goals that align with RetrievalHub:
1. **Syntactic integrity** — chunk boundaries align with complete syntactic units (functions, classes, blocks)
2. **High information density** — chunks packed up to a fixed size budget
3. **Language invariance** — no language-specific heuristics (tree-sitter handles the grammar)
4. **Plug-and-play** — concatenating chunks reproduces the original file

**Tools:**
- [astchunk](https://lib.rs/crates/astchunk) (Rust crate) — production implementation of cAST with `ContextualFormatter` that prepends scope ancestry headers to each chunk
- [code-chunk](https://github.com/supermemoryai/code-chunk) (by Supermemory) — tree-sitter-based chunker with higher IoU than naive approaches
- Python `ast` module — works for Python-only; tree-sitter is the multi-language path

**Controlled empirical study** ([May 2026](https://arxiv.org/html/2605.04763v1)): systematically tested chunking strategies for code completion. Function-level chunking via AST consistently outperforms line-based and fixed-size approaches. Tree-sitter is the recommended parser.

### For RetrievalHub:

Use tree-sitter with the cAST algorithm. Target chunk size: ~512 tokens (matches our document adapter's sweet spot). Include the scope ancestry header (module path + enclosing class/function signature) so the embedding model has context. The `astchunk` Rust crate or the Python `code-chunk` library are both viable; for integration with our Python pipeline, `code-chunk` or a direct tree-sitter Python binding is simpler.

## B. Code Embedding Models

### jina-code-embeddings — best self-hostable option

| Model | Size | Avg. on 25 Code Benchmarks | Self-Hostable | Notes |
|---|---|---|---|---|
| [voyage-code-3](https://voyageai.com/) | Unknown | 79.23% | No (API only) | Best quality, but proprietary |
| [jina-code-embeddings-1.5B](https://jina.ai/news/jina-code-embeddings-sota-code-retrieval-at-0-5b-and-1-5b/) | 1.5B | 79.04% | Yes | Matches Voyage, open-weight |
| [jina-code-embeddings-0.5B](https://jina.ai/news/jina-code-embeddings-sota-code-retrieval-at-0-5b-and-1-5b/) | 494M | 78.41% | Yes | Best ratio of quality to size |
| gemini-embedding-001 | Unknown | 77.38% | No (API only) | Google proprietary |
| Qwen3-Embedding-0.6B | 600M | ~73% | Yes | General-purpose, not code-specific |
| General models (gte, bge) | Varies | ~82-87% retrieval@10 | Yes | 10-15% gap vs. code-specific |

**Recommendation: jina-code-embeddings-0.5B** for the first worked example. It's:
- Open-weight, self-hostable via sentence-transformers or [jina-embeddings-v4-vllm-code](https://huggingface.co/jinaai/jina-embeddings-v4-vllm-code)
- 896 dimensions, 32K max sequence length (handles large functions)
- Matryoshka support (can truncate to 256d for faster search)
- Outperforms Qwen3-Embedding-0.6B by 5pp despite being smaller

**Serving:** TEI supports BERT-class models but the Jina code model is decoder-based (Qwen2.5-Coder backbone). For vLLM, there's a pre-merged adapter variant at `jinaai/jina-embeddings-v4-vllm-code`. For sentence-transformers (our current pattern), the standard HuggingFace path works.

**TEI as shared service:** Deploy jina-code-embeddings alongside PubMedBERT in the shared TEI/embedding service. One TEI instance per model, same PVC pattern for weight caching.

## C. Live Repo Integration

### GitHub's Official MCP Server — the right tool for live access

[github/github-mcp-server](https://github.com/github/github-mcp-server) provides:
- `get_file_contents` — fetch file at a specific ref (branch, tag, commit SHA)
- `search_code` — GitHub's code search with qualifiers (repo, language, path)
- `get_repository_tree` — recursive directory listing
- `list_commits` — recent commit history

This gives RetrievalHub's code adapter **live file access without maintaining a clone**. The agent calls `retrieve` to find relevant code via vector search, then optionally calls `get_file_contents` via the GitHub MCP server to get the current version at HEAD.

### Incremental Re-indexing

For the vector index to stay fresh:
- **Merkle tree diffing** (the Cursor approach) — hash the file tree, compare with the previous index, re-embed only changed files. Cursor re-indexes every ~10 minutes.
- **GitHub webhooks** — on push events, trigger a re-index of changed files. The webhook payload includes the list of modified files.
- **Git diff-based** — `git diff --name-only HEAD~1 HEAD` identifies changed files; re-chunk and re-embed only those.

**For the first worked example:** start with periodic re-index on demand (manual `python scripts/ingest_code.py`). Add webhook-triggered incremental re-index as a follow-up. The Merkle tree approach is the production path.

## D. Existing MCP Servers for Code Context

### Evaluated

| Server | Approach | Live Repo? | Self-Hostable? | Best For |
|---|---|---|---|---|
| [Claude Context](https://github.com/zilliztech/claude-context) (Zilliz) | Hybrid BM25+vector, AST chunking, Merkle tree incremental | Local clone only | Yes | Full-text semantic search over local repos |
| [jCodeMunch](https://github.com/jgravelle/jcodemunch-mcp) | tree-sitter AST, symbol-level retrieval | Local + GitHub | Yes | Precise function/class lookup |
| [Codebase-Memory](https://github.com/DeusData/codebase-memory-mcp) | Knowledge graph, 158 languages | Local clone | Yes (Go binary) | Structural navigation, dependency tracing |
| [GitHub MCP Server](https://github.com/github/github-mcp-server) (official) | GitHub API (REST + GraphQL) | **Yes — live** | Yes | File access, search, PRs, issues |
| [Context7](https://github.com/upstash/context7) | Documentation + code examples | Live docs | Yes | Library documentation |

### Key insight

None of these solve the RetrievalHub use case end-to-end because they're designed as **per-agent tools**, not as a **platform service**. RetrievalHub's value is that it manages retrieval quality, chunking strategy, embedding model, eval metrics, and usage rules centrally — agents just call `retrieve`. The existing MCP servers are inspirations for the adapter's internals, not replacements.

The **Claude Context** architecture is the closest match for our vector index layer (AST chunking + hybrid search + incremental indexing). The **GitHub MCP Server** is the right choice for the live-access layer.

## E. Feasibility Assessment

### Is vector-based retrieval right for frequently-changing code?

**Yes, with a layered approach:**

1. **Vector index for semantic search** — answers "find code related to authentication" or "show me the adapter pattern." This doesn't need to be real-time; re-indexing on merge to main (or every few hours) is sufficient. The cAST paper shows this works well for code.

2. **Live API for current-state access** — answers "show me the current implementation of `retrieve` in `server.py`." This needs to be real-time and is handled by the GitHub API (via the GitHub MCP server or direct API calls).

3. **The agent combines both** — semantic search finds the relevant code areas; live access gets the current version. The retrieve tool returns chunk text + file path + function name; the agent can then fetch the live version if needed.

### What about just giving the agent the full repo?

For small repos (<50 files, <100K tokens), stuffing the full repo into context works. For larger repos, it doesn't — and the retrieval quality degrades as context length increases. The RetrievalHub repo itself is ~150 files and growing; it's already at the boundary.

More importantly, RetrievalHub's value proposition is that retrieval expertise lives next to the data. If "just stuff the repo" were sufficient, there'd be no need for a retrieval platform. The code adapter demonstrates that even for code, curated retrieval with domain-specific chunking and embedding outperforms naive context stuffing.

### Re-index latency

| Strategy | Latency | Cost | Best For |
|---|---|---|---|
| On-demand (manual) | Minutes | Low | First worked example |
| Cron (hourly) | Minutes, periodic | Low | Stable repos |
| Webhook (on push) | Seconds after push | Medium | Active development |
| Merkle tree (continuous) | Sub-second diffing | Medium | Production |

For the first worked example: on-demand is fine. The repo changes during development sessions, not continuously.

## Recommendations for RetrievalHub

### Build (the code adapter)

1. **Code chunker** — tree-sitter-based AST chunker following the cAST algorithm. Python first via tree-sitter-python; the tree-sitter approach generalizes to other languages without code changes (just add grammars). Integrate as `src/retrieval_hub/ingestion/chunking/ast_treesitter.py` alongside the existing `token_fixed.py`.

2. **Code adapter** — `src/retrieval_hub/adapters/code.py` implementing the `SourceAdapter` interface. Uses jina-code-embeddings for query embedding, pgvector for ANN search (same as document adapter).

3. **Ingestion script** — `scripts/ingest_code_repo.py` that clones a repo at a specific ref, runs AST chunking, embeds with jina-code-embeddings, writes to pgvector. Accept `--repo`, `--ref`, `--branch` arguments.

4. **Usage rules for code** — different from clinical docs: "This index was built from commit {sha} on branch {branch}. Code may have changed since. Always verify against the live repo."

### Integrate (existing tools)

1. **GitHub MCP Server** — deploy alongside the RetrievalHub MCP server. Agents that need live file access use it directly. The retrieve tool's response includes file paths and function names that map to GitHub API calls.

2. **jina-code-embeddings-0.5B** — deploy as a second TEI/embedding service in the `retrieval-hub` namespace, following the same pattern as PubMedBERT. This is the "shared model infrastructure" principle — the platform serves the model, not each service.

### Don't build (use existing)

1. **Don't build a custom GitHub API client** — the official GitHub MCP server handles auth, rate limiting, and the full API surface. Agents connect to it directly.

2. **Don't build a knowledge graph** — the Codebase-Memory approach (knowledge graph of code relationships) is powerful but a different product. RetrievalHub's differentiator is retrieval quality and source management, not graph navigation. If graph-based code navigation is needed later, it's a separate source family or an integration.

## Sources

- [cAST: AST-Based Code Chunking (EMNLP 2025)](https://arxiv.org/html/2506.15655v1)
- [astchunk Rust crate](https://lib.rs/crates/astchunk)
- [code-chunk by Supermemory](https://github.com/supermemoryai/code-chunk)
- [How Does Chunking Affect Retrieval-Augmented Code Completion? (May 2026)](https://arxiv.org/html/2605.04763v1)
- [Codebase-Memory: Tree-Sitter Knowledge Graphs (2026)](https://arxiv.org/html/2603.27277v1)
- [Jina Code Embeddings](https://jina.ai/news/jina-code-embeddings-sota-code-retrieval-at-0-5b-and-1-5b/)
- [jina-embeddings-v4-vllm-code](https://huggingface.co/jinaai/jina-embeddings-v4-vllm-code)
- [6 Best Code Embedding Models Compared (Modal)](https://modal.com/blog/6-best-code-embedding-models-compared)
- [Best Embedding Models 2026 (Milvus)](https://milvus.io/blog/choose-embedding-model-rag-2026.md)
- [GitHub MCP Server](https://github.com/github/github-mcp-server)
- [Claude Context (Zilliz)](https://github.com/zilliztech/claude-context)
- [jCodeMunch MCP](https://github.com/jgravelle/jcodemunch-mcp)
- [Codebase-Memory MCP](https://github.com/DeusData/codebase-memory-mcp)
- [vLLM Embedding Docs](https://docs.vllm.ai/en/latest/models/pooling_models/embed/)
