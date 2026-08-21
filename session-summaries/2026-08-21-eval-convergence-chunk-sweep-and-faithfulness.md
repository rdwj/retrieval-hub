# Session Summary — 2026-08-21 · eval-convergence · Chunk sweep + faithfulness + model registry epic

**Plan:** NEXT_SESSION-eval-convergence.md (Phase 3, step 4)   **Commits:** 8d9209f..585b639 (main)
**Deployed:** none   **Model:** Claude Opus 4.6

## Plan vs. actual
Planned: make the Nomic switch official, run chunk sweep, score faithfulness, update docs.
Shipped: all four items plus the localhost→127.0.0.1 fix, a new sweep script, and a new epic.
Scope: expanded to include model-registry-and-health epic planning (emerged from design discussion about how the tool resolves embedding endpoints).

## Shipped
- `8d9209f` — Fix localhost→127.0.0.1 across 22 files; switch VA CPG to Nomic v1.5; add chunk/overlap CLI flags to alt-embedding script; add Faithfulness metric to eval script; update onboarding docs (parallel session committed this)
- `f8eb840` — Chunk sweep results (4 configs, all 100% hit_rate@5, MRR: 512/64 and 1024/0 at 0.967) + faithfulness scoring (raw 0.854, rewrite 0.813) + batch_size=8 fix + sweep script
- `585b639` — Model registry and health epic file (6 phases) + eval-convergence update

## Verification & confidence
- Chunk sweep: verified row counts on 127.0.0.1 for all 4 tables (12973, 6500, 7420, 3263). Sweep script ran clean against all tables.
- Faithfulness: Ragas scored 28/30 queries (2 NaN), aggregate 0.854. Consistent with prior run metrics.
- Production index: confirmed active index points to idx_va_cpg_nomic_v1 with Nomic v1.5, 512 tokens.
- Confidence: high — all eval numbers are from real Ragas scoring against gpt-oss-120b. The localhost fix was validated by catching a real dual-backend issue during the 256/0 ingestion.

## Judgment calls & deviations
- Skipped creating idx_va_cpg_v2 table (plan said to). The existing idx_va_cpg_nomic_v1 already had the right data; user confirmed no need to duplicate.
- Used batch_size=2 for 1024-token chunks after batch_size=8 OOM'd on MPS. Added to NEXT_SESSION watch-out section.
- Copied idx_va_cpg_nomic_v1 from cluster to Podman via CSV export/import because pg_dump version mismatch (v14 local vs v16 server).
- Expanded scope to model-registry-and-health epic planning — design discussion emerged naturally from reviewing how the MCP tool uses embedding models.

## Backlog delta
Filed: none. Closed: none. New epic: model-registry-and-health (6 phases, not yet started). Memory: design-model-registry-and-health.

## Drift & forward-collisions
- Backward — none. This session's work (chunk sweep, faithfulness) is additive to eval-convergence Phase 3.
- Forward — the model-registry-and-health epic (Phase 3: always-remote retrieve) will change how the MCP server embeds queries, which touches the same adapter code this session's eval work depends on. No conflict now, but the Phase 3 migration should re-run the eval suite to confirm no regression.

## For the reviewer
- Sanity-check: the chunk sweep MRR results show 512/64 and 1024/0 both at 0.967. Worth running full Ragas answer-quality on these two before deciding whether to switch from 512/0.
- Thin verification: the faithfulness NaN on 2/30 queries (q004, q048) wasn't investigated. Could be Ragas limitation or something about those specific questions.
- Wants guidance: none.

## Risks / watch-fors
- Dual-backend risk (localhost IPv4/IPv6) is now mitigated in scripts but the library defaults in `document.py` and `engine.py` also changed — any downstream code using those defaults will now go to 127.0.0.1. Should be fine for local dev, but worth noting.
- MPS OOM at batch_size=8 for 1024-token chunks is a recurring constraint. If larger chunk sizes become common, need a smarter adaptive batch sizing approach.
