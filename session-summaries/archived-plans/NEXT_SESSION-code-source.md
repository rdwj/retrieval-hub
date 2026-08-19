# Next Session — code-source

## Next: Extend `retrieve` with live GitHub file fetch and harden code retrieval

The code adapter works and retrieval quality is validated. This session completes the code source story: add live file access to the `retrieve` tool (Option A from the server mesh research), fix the quality issues found in evaluation, and close out stale issues from earlier sessions.

1. **Add `file_path` + `ref` parameters to the `retrieve` MCP tool**
   When `file_path` is provided, skip vector search and fetch the file from GitHub's public REST API (`GET /repos/{owner}/{repo}/contents/{path}?ref={ref}`). No PAT needed for public repos (60 req/hr unauthenticated). The recipe's `data_freshness.source_url` or a new `github_repo` field on the recipe provides `owner/repo`. Return the file content in the same `RetrievalResponse` shape (single hit, score=1.0, full file text). When `file_path` is absent, existing vector search behavior is unchanged. Update the MCP server tests to cover the new path.

2. **Add minimum chunk size threshold to the AST chunker**
   The evaluation found 16-token fragments from sibling merging. Add a `min_tokens` parameter (default ~50) to `chunk_code_file()`. When a chunk is below the threshold after header + code, merge it with the next or previous sibling chunk rather than emitting it standalone. This reduces noise in the index without changing the algorithm's structure.

3. **Register `github_repo` on code source recipes**
   Extend the ingestion script's recipe content to include `"github_repo": "owner/repo"` when the repo has a GitHub remote. The `retrieve` tool reads this field to construct the GitHub API URL. Update `ingest_code_repo.py` to detect the remote with `git remote get-url origin` and parse the owner/repo from the URL.

4. **Write a code query demo script**
   Create `scripts/query_code_demo.py` following the `query_va_cpg_demo.py` pattern but defaulting to the `retrieval-hub-code` source. Include a `--file` flag that exercises the new live file fetch path. This serves as both a demo and a smoke test.

5. **Close stale issues**
   Issues #8, #11, #12, #13, #14 were completed in prior sessions. Close them with one-line resolution notes.

**Sequencing.** Items 1 and 2 are independent. Item 3 feeds into item 1 (the tool needs `github_repo` from the recipe to know where to fetch). Item 4 depends on 1. Item 5 is housekeeping, do anytime.

**Constraints for the session:**
- The existing `retrieve` tool signature is the MCP server's public API — the new parameters must be optional and backward-compatible
- The VA CPG source and MCP server on gpt-oss-120b must keep working (don't modify the deployed server; changes are local-first)
- GitHub unauthenticated rate limit is 60/hr per IP — adequate for dev/demo, but the code should log remaining quota from response headers
- The `retrieve` tool currently delegates to `retrieval_hub.retrieval.api.query()` — the file-fetch path bypasses this and calls GitHub directly via `httpx`

**Session start protocol:**
- Premise checks (before item 1, ~5 min):
  - Verify local databases are up (`pg_isready -p 5433` and `-p 5434`)
  - Verify the `retrieval-hub-code` source exists in the catalog (`SELECT slug FROM source WHERE slug='retrieval-hub-code'`)
  - Verify `httpx` is available in the venv (or install it — likely already a transitive dep)
  - Quick smoke test: `curl -s https://api.github.com/repos/rdwj/retrieval-hub/contents/README.md | head -5` to confirm unauthenticated GitHub API works
- Rules with history:
  - Embedding models are shared cluster resources — don't change the jina-code-embeddings setup, it's working
  - The MCP server uses FastMCP `Depends()` for session injection — the B008 lint warnings are intentional, don't "fix" them
- Stop-and-ask before: modifying the deployed MCP server on gpt-oss-120b; any changes to the VA CPG source or its pgvector table
- Close ritual: session summary to `session-summaries/`; if stale issues are closed, note the count

**Loop design:** Not loop-shaped. Items are discrete features with different shapes.

## What landed last session (2026-08-14)

Built and validated the code-family adapter using this repo as the first worked example. 117 Python files, 327 AST-aware chunks, jina-code-embeddings-0.5b (896d), 44.7s total ingestion time. Retrieval quality good-to-excellent on 4 of 5 test queries. FastMCP server mesh research completed — confirmed Option A (extend `retrieve`) for MVP, Option C (proxy mount) for production.

Commits: `9b548c6` (feat: code adapter + chunker), `44b9eaa` (docs: session summary + research)

Key decisions:
- Skipped TEI deployment for jina-code-embeddings (decoder-based, uncertain compatibility) — sentence-transformers in-process works
- Reused DocumentAdapter for SourceFamily.CODE rather than separate CodeAdapter — per-recipe config handles differences
- Added prompt_name support to ChunkEmbedder/QueryEmbedder for models with task-specific prefixes

## Watch out for

- GitHub's unauthenticated rate limit was tightened in May 2025 — if 60/hr proves too low, the fallback is a read-only fine-grained PAT with `public_repo` scope
- The `retrieve` tool's `file_path` parameter creates a second code path in the MCP server — test both paths (vector search + file fetch) to avoid regressions
- The chunker's min_tokens change could shift chunk boundaries for already-ingested sources — re-ingest after the change to validate
- `httpx` may need to be added as an explicit dependency in `retrieval-hub-mcp/pyproject.toml`

## If blocked

- If GitHub API is unreachable or rate-limited during development, implement the file-fetch path against local filesystem first (`file://` URLs from `data_freshness.source_url`), then swap to GitHub API
- If the min_tokens threshold proves tricky to get right, skip it and focus on items 1, 3, 4 — the 16-token fragments are a quality nit, not a blocker
