# Next Session -- Ontology

## Epic: Enterprise ontology registry for cross-source concept mapping

A first-class ontology registry that maps canonical concept names to
per-source entity types, enabling agents to query across heterogeneous
sources without knowing source-specific terminology.

**Status: CLOSING.** All build phases shipped. Final item is #56
(CronJob deployment for drift detection).

## Next: Deploy ontology doctor CronJob (#56)

Ship the doctor as a scheduled CronJob on OpenShift, then close the
epic. Remaining ontology work tracked as future issues (#61, #62, #63,
#64) for a future epic.

## Remaining epic phases

### Phase 6: Doctor CronJob (#56) — final phase

Deploy `scripts/ontology_doctor.py --skip-retrieval --json` as a
periodic CronJob on OpenShift. Alert when WARN count > 0.

**Work:**
1. Write CronJob manifest (`deploy/openshift/retrieval-hub/ontology-doctor/`)
2. Configure in-cluster DB connection (no port-forward needed)
3. Add Slack webhook or OpenShift alert on non-zero WARN
4. Test: apply manifest, verify first run produces a clean report

**Definition of done:** CronJob runs on schedule, produces JSON report,
alerts on WARN findings. Verified by one successful scheduled run.

**Dependencies:** None — doctor script is complete.

## What landed (2026-09-08 through 2026-09-09)

**Phases 1-5e shipped across 9 sessions:**
- Phase 1: Registry foundation (#49, #51)
- Phase 2: Discovery API (#50, #52)
- Phase 3: Hierarchical concepts (#53)
- Phase 4: Cross-concept relationships (#54)
- Phase 5a: Authority scoring (#55)
- Phase 5b: Benchmark (#57)
- Phase 5c: Family-aware hierarchy expansion
- Phase 5d: Ontology doctor (9 checks, CLI, tests)
- Phase 5e: Full source onboarding (all 11 sources, 0 WARN)

**Commits:** 2e53ed8..e39d267 (main)

**Umbrella #48 closed.** Source issues #58, #59, #60 closed.

## Future work (separate epic)

These issues are filed but out of scope for this epic's close:
- #27 — Production ingestion runners (Tekton/Jobs)
- #61 — Automated onboarding pipeline with HITL
- #62 — Concept-first retrieval with fan-out
- #63 — Eval-driven self-improvement loops
- #64 — Query success monitoring with triggers

## Watch out for

- In-cluster DB connection string differs from port-forwarded one
- CronJob needs the `retrieval_hub` package installed (or run from
  a container image that includes it)
- The doctor's `--skip-retrieval` flag avoids needing the embedding
  service, which simplifies the CronJob (no embedding port-forward)

## If blocked

- If cluster access is unavailable, write the manifests and test
  locally with `--dry-run`. Deploy next session.
