# Session Summary — 2026-08-23 · retro-followups · Close out retro issues #37, #38, #39

**Plan:** NEXT_SESSION-retro-followups.md   **Commits:** 0d2076f..2e0f5b9 (main)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: investigate and fix three issues from data-products retro (#37 cache, #38 audit logging, #39 model IDs). Shipped: all three resolved and closed. Slipped: none.
Scope: stayed in scope.

## Shipped
- `0d2076f` — Removed `cache_ttl=3600` / `cache_scope="public"` from FastMCP constructor; investigation confirmed no server-side caching exists and `tools/call` is not a cacheable MCP method (#37)
- `c523f45` — Added model-availability probe to eval harness startup (exits early on 404/API error); extracted `_supports_temperature()` helper replacing three inline checks (#39)
- `7a7215e` — Implemented `write_audit_record()` utility and instrumented `register_document_source()` (source.created, source.updated) and `Source.transition_to()` (source.status_changed) (#38)
- `2e0f5b9` — Archived the completed planning doc

## Verification & confidence
- 338 tests pass (including 6 new audit tests), zero regressions
- Gitleaks clean, no secrets
- Lint: 1 import-sort issue in new test file fixed; 7 pre-existing warnings unchanged
- Confidence: high for #38 and #39 (tests cover the new code paths); medium for #37 (removed the TTL but root cause of the original scale-experiment staleness was external to this codebase — documented in the commit and issue comment)

## Judgment calls & deviations
- Used explicit `write_audit_record()` calls at mutation sites instead of SQLAlchemy event listeners, per the existing `AuditRecord` docstring's anticipation of an `AuditWriter` service pattern. Event listeners would have complicated session management during flush.
- Made `session` and `actor` optional on `Source.transition_to()` to preserve backward compatibility with existing callers.

## Backlog delta
Closed #37, #38, #39. Filed: none. Memory: none.

## Drift & forward-collisions
- Backward — none; these were self-contained retro issues with no overlap.
- Forward — none.

## For the reviewer
- Sanity-check: the #37 investigation concluded the staleness was external (client or HTTP layer), not server-side. If the problem recurs, the next step is to instrument the MCP client or check HAProxy response headers.
- Thin verification: #37 fix (removing cache_ttl) was not tested against the deployed cluster — only confirmed by source-code analysis of FastMCP internals.
- Wants guidance: none.

## Risks / watch-fors
- The audit writer is not yet called from all mutation paths (e.g., `model_registry.py` model endpoint changes, or any future admin CLI). As new mutation sites are added, they need `write_audit_record` calls.
