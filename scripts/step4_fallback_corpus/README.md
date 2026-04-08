# Fallback corpus for step 4 ingestion

Hand-written Markdown files that act as the retrieval corpus when network
access to docs.redhat.com is unavailable (rate limiting, offline dev,
corporate proxy, etc.).

The content is about **Red Hat AI 3 / OpenShift AI / LlamaStack**, written
in the style of product documentation. It is **not copied from real Red Hat
docs** — it's representative-but-fabricated content designed to make
semantic retrieval produce meaningful results during the first hand-run of
the ingestion pipeline.

This is not production content. When we move to ingesting real Red Hat
documentation in a later step, the corpus loader will pull from
docs.redhat.com directly and this directory becomes a development-only
fallback.

Usage: `scripts/step4_ingest_rh_aai_docs.py` loads every `*.md` file in
this directory as a `FetchedDocument` when the primary (network) fetch
path fails or is explicitly disabled via `--fallback`.
