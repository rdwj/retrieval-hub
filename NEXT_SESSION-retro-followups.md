# Next Session -- retro-followups

One-off session to address three issues from the data-products epic retro.

## Issues

1. **#37 MCP cache invalidation** -- Investigate whether FastMCP's
   `cache_ttl=3600` is server-side or client-hint. Fix catalog tool
   caching so `list_sources` reflects newly registered sources without
   an MCP server restart.

2. **#38 Catalog audit logging** -- Add a `source_audit_log` table and
   SQLAlchemy event listeners on the Source model to record mutations
   (create, update, delete, status change). Alembic migration needed.

3. **#39 Model ID pinning** -- Audit all scripts for dated Anthropic
   model IDs. Switch to aliases. Add a model-availability check to the
   eval harness startup.

## Suggested order

Start with #37 (fastest to investigate, highest impact on eval
reliability). Then #39 (quick audit + grep). Then #38 (most code, but
straightforward schema + listener work).

## Session start

```bash
git status
gh issue view 37 38 39
grep -r 'claude-sonnet-4\|claude-3' scripts/ --include='*.py'
```
