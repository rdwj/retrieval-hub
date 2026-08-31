# Next Session -- Self-Serve Onboarding

## Epic: Auth, AutoRAG-style Onboarding, and New Data Families

Build the auth layer, a self-serve source onboarding pipeline, and onboard
new datasets that exercise the four unrepresented source families (tabular,
graph, process, external). The self-serve pipeline replaces the idea of
adopting an external AutoRAG framework by wrapping our own eval sweep
infrastructure into an onboarding workflow.

## What landed

- **Phase 1 (Auth): Complete.** See `session-summaries/
  2026-08-27-self-serve-onboarding-auth-and-pipeline.md`.

- **Phase 2 (Onboarding pipeline): Complete.** Full eval sweep proven
  end-to-end (3 configs, 156 QA pairs, Ragas scoring). Winner selected
  and promoted. Source `aircraft-sb-test` is CURATED and queryable.
  `--skip-eval` fast path added. MCP server redeployed with all fixes.
  See `session-summaries/2026-08-30-self-serve-onboarding-proving-run-completion.md`.

- **Phase 3b (Process): Code complete, not yet proven.** ProcessAdapter
  with procedure-aware chunking implemented. Tested on individual SB
  documents (step-aligned chunks verified). Needs ingestion run and
  procedure refine strategy test against real data.

## Remaining epic phases

### Phase 2 — Polish (data card auto-population)

Pipeline proven end-to-end. One remaining item: wire eval baseline scores
and winning chunk config into `describe_source` metadata so data cards
show quality metrics.

### Phase 3a — Tabular (ClinicalTrials.gov)

**Design questions to resolve first:**
- Row-per-chunk vs. group-of-rows-per-chunk?
- Semantic search over NL-rendered text, or structured filters?
- How does `refine` work on tabular data?

**Work:** Download extract, build TabularAdapter, ingestion script, QA +
eval. Wire into retrieval adapter factory.

### Phase 3b — Process (Aircraft maintenance procedures)

**Work:** Re-model existing Piper SB data as structured procedures. Build
ProcessAdapter (procedure context around a step, not just the chunk).
The raw data already exists. The `refine` entity-arc strategy may work for
procedure traversal.

### Phase 3c — Graph (SNOMED-CT or similar)

Most architecturally novel. May warrant a spike first. Pick a dataset,
design chunk representation (entity-as-chunk vs. relationship-as-chunk),
build GraphAdapter.

### Phase 3d — External (federation to public API)

Integration pattern, not a new data shape. Simplest version: an adapter
that makes HTTP calls instead of pgvector queries. Participates in
multi-source RRF.

**Sequencing:** 3a and 3b first (highest value, clearest path), then 3c
(spike), then 3d.

**Epic definition of done:** At least 3 of 4 families have a live source
with eval baseline. Onboarding pipeline successfully onboards at least one.

## Next session

**Focus: Prove ProcessAdapter end-to-end + data card auto-population.**

1. **Ingest aircraft SBs as process family.** Run `onboard_source.py
   --slug aircraft-sb-process --data-dir .../piper-cherokee/extracted/
   --family process --skip-eval`. Verify procedure-aware chunks in the
   DB: check that `doc_section` values follow the `instructions/step-N`
   and `instructions/part-P/step-N` patterns.

2. **Test the `procedure` refine strategy.** Query the new source via
   the retrieval API, then call `refine(strategy="procedure")` on a
   step hit. Verify it returns the full instruction sequence plus header.
   Fix any issues in `ProcessAdapter._fetch_procedure_chunks()`.

3. **Data card auto-population.** Wire eval baseline scores (from the
   `aircraft-sb-test` proving run) and winning chunk config into
   `describe_source` metadata. When a source has a completed eval run,
   `describe_source` should include `eval_baseline` with the metrics
   and `chunk_config` with the winning parameters.

4. **Redeploy MCP server** with ProcessAdapter if ingestion succeeds.

**Sequencing.** Items 1-2 together (prove the process family). Item 3
is independent and can be done before or after. Item 4 gates on 1-2.

**Constraints for the session:**
- Port-forward DB and embedding before ingestion (see infrastructure
  notes below). Use `--skip-eval` for the process ingestion — the full
  eval sweep is only needed for high-value quality baselines.
- The `aircraft-sb-test` source (technical_document family, flat chunks)
  already exists. The new `aircraft-sb-process` source is a separate
  re-modeling of the same data with procedure-aware chunking.

**Session start protocol:**
- Premise checks: verify port-forwards work, embedding pod is running,
  `aircraft-sb-test` source still exists in catalog (from the proving
  run). Check that no parallel session modified the model registry.
- Rules with history: the nomic TEI pod OOMs under batch embedding
  (8Gi limit). Use `--embedding-endpoint ""` (local sentence-transformers)
  for ingestion, or port-forward with small batches for query embedding.
  The health probe CronJob marks models unhealthy; the fallback in
  `_resolve_embedding_endpoint` handles this but logs warnings.
- Stop-and-ask before: dropping existing sources or vector tables.

**Infrastructure notes:**
- Port-forward DB: `scripts/port_forward_cluster_pg.sh`
- Port-forward embedding: `oc port-forward --context=gpt-oss-120b -n
  retrieval-hub svc/retrieval-hub-embedding-nomic 8180:8080`
- Set model registry for local use: `UPDATE model_endpoint SET
  endpoint_url='http://127.0.0.1:8180', status='healthy' WHERE
  model_name='nomic-ai/nomic-embed-text-v1.5'`
- Restore cluster URLs before leaving: revert the model_endpoint rows

## Open issues this epic addresses

- #24 Keycloak realm and role allowlist example (Phase 1 stretch, deferred)
- #27 Production ingestion runners (Phase 2 via EvalHub, partially advanced
  by pipeline.py — see comment on issue)

## Open issues this epic does NOT address

- #31 MCP-level end-to-end eval (eval-convergence epic)
- #29 Elicitation (future epic)
- #25 Operator with CRDs (future)
- #23 Grafana dashboard (future)
- #17 SDK / #18 CLI (future)
