# Next Session — eval-convergence

## Epic status: COMPLETE

All five phases are done. Phase 4 (leaderboards/publication) was surveyed
on 2026-08-31 and closed as not relevant for now — details below.

### Phase 4 disposition (2026-08-31)

**Leaderboards:** No relevant leaderboard accepts custom retrieval system
submissions on custom corpora. MTEB/BEIR are embedding-model-only. TREC
RAG 2026 is the right shape but the deadline passed (Aug 8) and requires
running against MS MARCO, not our own data. BioASQ evaluates over PubMed,
not custom clinical corpora. CRAG and RAGBench evaluate LLMs or provide
benchmark datasets, not submission slots.

**Publication venues:** Nearest reachable targets are the 9th Clinical NLP
Workshop (dates TBD, likely late 2026) and SIGIR 2027 (CFP ~Jan 2027).
Both would accept a system paper. Decision: defer paper work until a
concrete CFP with a reachable deadline appears.

**What we have if we revisit:**
- 107-query VA CPG dataset with bootstrap CIs (Phase 5)
- 156-query aircraft-sb-test dataset (proving run, 2026-08-30)
- Refine-strategy sweep: no-refine is Pareto winner
- Chunk-size sweep: 512/64 winner on aircraft-sb-test
- Full eval register in cluster Postgres
- Per-batch JSONL checkpointing, PVC-backed, 48h deadlines

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

### Phase 4: Industry leaderboards and publication — CLOSED

No relevant leaderboard. Paper deferred to 2027 venues. See disposition above.

## What landed last session (2026-08-26/28)

Per-batch JSONL checkpointing for the scoring stage, PVC-backed run data,
48h default deadline, and all 4 refine-strategy sweep runs completed.
See session summary for details.

## Watch out for

- **Test failure from parallel session:** `test_resolve_embedding_endpoint_unhealthy_model`
  in `tests/test_retrieval/test_api.py` — needs investigation, not from eval work.
- **Untracked `eval/aircraft-sb-test/`** from parallel session.
- gpt-oss-120b sandbox cluster may be reprovisioned. deploy-platform.sh handles this.
