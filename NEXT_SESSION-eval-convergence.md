# Next Session — eval-convergence

## Next: Phase 4 — Industry leaderboards and publication

Research which retrieval/RAG leaderboards are relevant, understand their
eval protocols, and position retrieval-hub's results for submission.

1. **Survey existing leaderboards**
   MTEB, BEIR, MIRACL, domain-specific clinical NLP benchmarks (n2c2,
   OHNLP, etc.). Identify which accept custom retrieval systems vs.
   only embedding models.

2. **Map our eval metrics to leaderboard protocols**
   For leaderboards that accept retrieval systems: identify gaps (different
   query formats, different corpora, different metrics).

3. **Prepare a submission-ready eval run**
   If a suitable leaderboard exists, prepare the data in their format.

4. **Draft the arXiv paper**
   Abstract and methods section using the accumulated eval register data.
   The refine-strategy sweep results are the headline finding.

**Session start protocol:**
- Premise checks (~5 min):
  - Databases up (`pg_isready -h 127.0.0.1 -p 5433` and `-p 5434`)
  - Review eval register data: `SELECT * FROM eval_run ORDER BY completed_at DESC LIMIT 10;`
  - Read the sweep results summary in `session-summaries/2026-08-26-eval-convergence-phase2-completion.md`
- Rules with history:
  - gpt-oss-120b reasoning off via `enable_thinking=False` in `extra_body`
  - **Use 127.0.0.1 not localhost** for Postgres connections
  - All embedding models resolve from the model registry — no local loading
- Stop-and-ask before: submitting to external leaderboards; publishing drafts

## Remaining epic phases

### Phase 1: Full answer-quality eval pipeline — DONE

Built in session 2026-08-20 (morning). See Runs 1-5.

### Phase 2: EvalHub integration — DONE

Completed 2026-08-24 through 2026-08-28.
- EvalHub container, deploy/submit/sweep scripts, auto-registration
- Nomic v1.5 TEI service deployed, all models via registry
- Production readiness: /health endpoint, DB credentials via Secret,
  model health probe CronJob, deploy-platform.sh orchestrator
- Per-batch JSONL checkpointing with PVC-backed persistence
- Refine-strategy sweep: 4 runs completed, results in eval register

See `session-summaries/2026-08-24-eval-convergence-evalhub-and-prod-readiness.md`
and `session-summaries/2026-08-26-eval-convergence-phase2-completion.md`.

**Sweep results (no refine is the Pareto winner):**

| Config | ctx_prec | ans_rel | faith |
|---|---|---|---|
| no refine | 0.732 | 0.725 | 0.843 |
| adjacent-2 | 0.353 | 0.735 | 0.838 |
| adjacent-4 | 0.272 | 0.724 | 0.847 |
| section | 0.253 | 0.728 | 0.877 |

### Phase 3: Retrieval configuration sweep — DONE

Completed 2026-08-22. Winner: 512/0 with Nomic v1.5.

### Phase 5: Query set expansion and statistical rigor — DONE

Completed 2026-08-22 (evening). 107-query dataset with bootstrap CIs.

### Phase 4: Industry leaderboards and publication — NEXT

See "Next" section above.

## What landed last session (2026-08-26/28)

Per-batch JSONL checkpointing for the scoring stage, PVC-backed run data,
48h default deadline, and all 4 refine-strategy sweep runs completed.
See session summary for details.

## Watch out for

- **Test failure from parallel session:** `test_resolve_embedding_endpoint_unhealthy_model`
  in `tests/test_retrieval/test_api.py` — needs investigation, not from eval work.
- **Untracked `eval/aircraft-sb-test/`** from parallel session.
- gpt-oss-120b sandbox cluster may be reprovisioned. deploy-platform.sh handles this.
