# Session Summary -- 2026-08-22 · data-products · Phases 4-7 (epic complete)

**Plan:** NEXT_SESSION-data-products.md   **Commits:** `aba4d0a`..`a78aa4b` (4 data-products commits)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual

Planned: Phase 4 (cross-dataset reasoning agent test). Shipped: Phases 4, 5, 6, and 7, completing the entire epic. No slippage. Scope stayed tight across all phases; Phase 5 pivoted from documentation to tooling (existing docs were sufficient, scaffolding tool was the real gap).

## Shipped

- `aba4d0a` Phase 4: 20-question eval harness with Anthropic API + MCP tool proxy, 2 prompt iterations, source selection scoring
- `3754c2c` Phase 5: `scripts/new_source.py` scaffolding tool (generates ingestion scripts), 43 tests, Makefile target, doc update
- `9077cbb` Phase 6: Scale experiments at 4/14/54 sources with 50 synthetic confusers, `register_synthetic_sources.py`
- `a78aa4b` Phase 7: Consolidated lab notes (373 lines) and paper outline (399 lines)
- `2b18df6` Epic retro with cross-retro pattern analysis
- Filed #37, #38, #39 from retro findings; commented on #34 with scale evidence

## Verification and confidence

- Phase 4: eval harness ran end-to-end against live MCP server, 20 questions x 2 iterations, automated source selection metrics
- Phase 5: 43 unit tests (all pass), generated script compiles and `--help` works, Makefile target verified
- Phase 6: 3 scale points (4/14/54) ran against live MCP + Anthropic API, automated metrics consistent across runs
- Phase 6 false start caught and re-run: MCP cache served stale catalog, invalid runs deleted
- Confidence: **high** on eval results and tooling; **medium** on the scale experiment's generalizability (synthetic confusers without data may behave differently than real overlapping sources)

## Judgment calls and deviations

- Switched from `claude-sonnet-4-20250514` (deprecated, 404) to `claude-sonnet-5` (no temperature support). Added model-family check for temperature parameter.
- Phase 5: pivoted from "write onboarding docs" to "build scaffolding tool" after discovering existing docs were comprehensive.
- Phase 6: used selection-only measurement (synthetic sources with no data) instead of creating real data for 50 sources. Faster but less realistic.
- Restored `pubmed-hypertension` as catalog-only entry (no vector data) after discovering it had vanished from the catalog DB.

## Backlog delta

Filed: #37 (MCP cache), #38 (catalog audit), #39 (model ID pinning). Commented on #34 (scale evidence strengthens case). Planning file: `NEXT_SESSION-retro-followups.md`.

## Drift and forward-collisions

- Backward: #34 (multi-source search) now has quantitative evidence for when it's needed. Still valid, priority unchanged, but the "defer until domain overlap" threshold is now data-backed.
- Forward: none.

## For the reviewer

- Sanity-check: the Phase 6 confuser methodology (synthetic sources with no data, selection-only measurement). Does this adequately simulate real domain overlap, or does the `retrieve` error on synthetics change agent behavior in ways that bias the results?
- Thin verification: `new_source.py` output has not been used to ingest a real corpus yet. The generated script compiles and its argparse works, but the 7-stage pipeline has not been exercised from a generated script.
- Wants guidance: none.

## Risks and watch-fors

- Catalog DB instability: two sources had unexpected state changes (PubMed missing, VA CPG in DRAFT). Root cause unknown. #38 addresses this.
- MCP server cache: `cache_ttl=3600` on FastMCP caused stale `list_sources` results. Any workflow that registers sources then queries the MCP server will hit this. #37 addresses this.
