# Next Steps

Things to think about before the next session.

## Decisions to make

1. **Positioning vs. RHOAI AI Hub / AI Assets.** This shapes everything else. See `open-questions.md` for the three options.
2. **Memory-hub boundary.** Is `put` a real operation, or is retrieval-hub read-only-for-agents?
3. **Query-rewriter LLM default.** Caller-supplied, cluster-resident, or both?
4. **Working name.** Keep `retrieval-hub`, or commit to something more marketable.

## Things that would unblock real progress

- **Pick one concrete source as the v0 example.** Something real, with real data, that we can actually build a card and a recipe for. Medical KB? S1000D corpus? An internal document set? Once we have one, the data model and the MCP surface design get a lot easier.
- **Talk to whoever owns AI Assets at Red Hat.** Even a half-hour chat would tell us whether option (a) is on the table or whether they'd rather we play in lane (b).
- **Look at RAGFlow seriously.** Either we use parts of it or we know exactly why we're not.

## Things to ponder when stepping away

- What would make a domain expert *want* to publish a source here vs. handing over a CSV?
- What's the smallest version that's still genuinely useful?
- Where does evaluation live — does retrieval-hub run evals, or just display them?
- Is "query rewriting as a property of the source" the killer feature, or just one feature among many? If it's the killer, we should lean into it harder in the pitch.

## When ready

- `/imagine` again to keep exploring
- `/pitch` once positioning is decided — that's the document that needs to land with whoever owns AI Assets
- `/brief` for a structured briefing once we have the v0 source picked
- `/propose` only after the boundary with AI Assets is clear
