# Session Summary — 2026-08-21 · eval-convergence · Embedding model comparison + onboarding guides

**Plan:** NEXT_SESSION-eval-convergence.md (Phase 3, step 2)   **Commits:** `da92735` (main)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual

Planned: compare PubMedBERT vs. jina-embeddings-v3 vs. BioLORD-2023 on the
full 30-query eval. Shipped: compared PubMedBERT vs. BioLORD-2023 vs.
nomic-embed-text-v1.5 (jina failed to load; nomic substituted per fallback
plan), plus ran Nomic + hybrid_0.3 reranking (unplanned, completed same
session). Also drafted two onboarding guides (data owner + ops) at user
request. Scope expanded beyond the original plan to include reranking and
documentation.

## Shipped

- `da92735` — Embedding model comparison (Run 7): Nomic v1.5 dominates
  PubMedBERT (+1.3pts ctx_precision, +9.4pts answer_relevancy). BioLORD
  ranks poorly (~30pts lower ctx_precision). Switched VA CPG active index
  to Nomic.
- Run 8 (Nomic + hybrid_0.3 reranking): Nomic raw is Pareto-optimal.
  Reranking adds marginal ctx_precision (+1.7pts) but costs -5.2pts
  answer_relevancy. Recommendation: use Nomic without reranking.
- `scripts/ingest_va_cpg_alt_embedding.py` — parameterized re-ingestion
  for embedding model comparison experiments
- `--prior-retrieval` flag on `scripts/eval_rerank_strategies.py`
- `docs/guide-data-owner.md` and `docs/guide-ops.md` (draft, uncommitted)

## Verification & confidence

- Retrieval verified against live pgvector indexes with 30-query eval set
- Ragas scoring via gpt-oss-120b (reasoning off) for all three models
- Per-register (lay/clinical) breakdowns confirm Nomic advantage is
  consistent across both registers
- Confidence: **high** — three models compared on identical pipeline, same
  30 queries (seed 42), same scoring LLM

## Judgment calls & deviations

- Substituted nomic-embed-text-v1.5 for jina-embeddings-v3 when jina failed
  to load (transformers version mismatch). The fallback was specified in the
  session plan.
- Ran hybrid_0.3 reranking on Nomic in the same session (originally planned
  for next session) because the embedding comparison finished faster than
  expected and the user approved proceeding.
- Recommended dropping hybrid reranking for Nomic — the simpler config is
  Pareto-optimal. This reverses the Run 6 conclusion that hybrid_0.3 was
  the best overall config (it was, for PubMedBERT).

## Backlog delta

Memory `design-per-source-model-selection` — embedding/rerank models are
per-source config; data owners choose, ops hosts, agents don't care.
Deferred: updating `docs/onboarding-journey-va-cpg.md` step 3 (still
recommends PubMedBERT; now superseded).

## Drift & forward-collisions

- Backward — none
- Forward — the onboarding guides (`guide-data-owner.md`, `guide-ops.md`)
  partially address new-source-onboarding (future epic). Not a collision;
  the guides are process documentation, not infrastructure.

## For the reviewer

- Sanity-check: the finding that a general-purpose embedding model beats a
  domain-specific one on clinical text is counterintuitive. The eval data
  backs it (Run 7 scores in `runs/embed-nomic/scores.json`), but worth
  noting this may not generalize to all clinical corpora.
- Thin verification: faithfulness was not scored in Run 7 (only
  context_precision and answer_relevancy). Run 8 scored faithfulness for
  Nomic + reranking (0.845) but not for Nomic raw. A future run should
  fill this gap.
- Wants guidance: none

## Risks / watch-fors

- Nomic v1.5 OOMs at batch_size=32 on Apple Silicon MPS. Use batch_size=8
  for local ingestion. Recorded in NEXT_SESSION-eval-convergence.md.
- The `onboarding-journey-va-cpg.md` doc still recommends PubMedBERT. It
  should either be updated or marked as a historical case study.
