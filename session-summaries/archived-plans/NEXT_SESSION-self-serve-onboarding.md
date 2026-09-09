# Next Session -- Self-Serve Onboarding

## Epic: Auth, AutoRAG-style Onboarding, and New Data Families

**Status: COMPLETE.** Epic definition-of-done met. All planned phases
delivered across 8 sessions (2026-08-27 through 2026-09-01).

## What landed

- **Phase 1 (Auth):** Machine-to-machine OAuth 2.1 + Google OAuth for
  interactive login. Email-domain access control.
- **Phase 2 (Onboarding pipeline):** Full eval sweep, `--skip-eval` fast
  path, data card auto-population.
- **Phase 3a (Tabular):** TabularAdapter, 307 chunks as
  `clinicaltrials-hypertension`.
- **Phase 3b (Process):** ProcessAdapter, 2,456 chunks as
  `aircraft-sb-process`.
- **Phase 3c (Graph):** GraphAdapter with Memgraph-backed refine, FHIR
  (22,305 nodes), Hetionet (769 nodes), SNOMED-CT (353 nodes). Three
  domain-specific renderers.

## Remaining

Phase 3d (External/federation adapter) deferred as standalone issue. The
epic DoD required 3 of 4 families live; all three non-external families
are delivered.

## Session summaries

- `2026-08-27-self-serve-onboarding-auth-and-pipeline.md`
- `2026-08-27-self-serve-onboarding-proving-run.md`
- `2026-08-30-self-serve-onboarding-proving-run-completion.md`
- `2026-08-31-self-serve-onboarding-phases-2-3a-3b.md`
- `2026-09-01-self-serve-onboarding-google-oauth.md`
- `2026-09-01-self-serve-onboarding-graph-family.md`
- `2026-09-01-self-serve-onboarding-snomed-ct-ingest.md`
