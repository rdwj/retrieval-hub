# Next Session — query-rewriter

## Epic: COMPLETE

All five phases of the query-rewriter epic are done. The rewriter is built,
tested, integrated, documented, and validated with an eval showing
measurable lift on lay-register queries.

## What landed (2026-08-19)

Phase 4: Rewrite lift eval. Ran a 30-query eval (14 lay, 16 clinical)
comparing raw vs. rewritten retrieval on the VA CPG source.

**Result:** Rewriting produces measurable improvement on lay-register
queries: hit_rate@5 +7.1%, MRR@5 +8.3%, mean_score +11.7%. Clinical
queries show no hit_rate change and slight MRR degradation (-14.6%),
which is expected when the original already uses domain terminology.

- `scripts/eval_rewrite_lift.py`: automated eval script
- `eval/rewrite_lift/`: per-query CSV + aggregate JSON results
- `session-summaries/2026-08-19-rewrite-lift-eval.md`: full analysis

## All phases

- Phase 1 (core rewriter service): `625a750`
- Phase 2 (VA CPG metadata): `625a750`
- Phase 3 (wire into retrieve): `625a750`
- Phase 4 (eval -- rewrite lift measurement): 2026-08-19 session
- Phase 5 (README quick-start): `6ec9bfe`

## Previous session (2026-08-18)

Phases 1, 2, 3, and 5 in a single session. Core rewriter module with async
LLM client, YAML prompt template, structured output validation. 64 unit
tests. VA CPG metadata seeded (49 vocabulary mappings, 8 sample queries).
Retrieve tool integration with `no_rewrite` parameter. README quick-start.
