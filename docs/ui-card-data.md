# UI Card Data: Field Listing and Data Dictionary

This document is the **information architecture** for retrieval-hub's catalog UI. It lists every field that appears on a source card (both the grid card a developer sees when browsing and the detail page they see after clicking in) and provides a formal data dictionary: where each field comes from, its type, its display format, an example value, and when it's visible.

This is **stage 1** of the UI work. Stage 2 — visual mockups in PatternFly + React, deployed as an RHOAI application — comes after the fields are settled. Resist the urge to sketch pixels before this document is right. A bad field list produces a pretty UI that doesn't help developers make decisions; a good field list produces a UI that almost draws itself.

The inspiration is the [HuggingFace model card](https://huggingface.co/docs/hub/model-cards) experience: a developer should be able to look at a retrieval source's card and make an informed decision about whether to use it, without having to read external documentation or ask the source owner questions. Everything the developer needs is on the card.

## Who the card is for

Three audiences, in roughly this priority:

1. **Agent developers** — building an agent that might need RAG. Looking for sources they can connect to, evaluating which ones are right for their use case, copying configuration snippets. The heaviest users of the card.
2. **Source owners** — checking on their own source's state, looking at eval scores, reviewing agent write activity. Secondary audience, but they use the same cards (plus the owner-only edit affordances).
3. **Platform admins** — auditing the catalog, reviewing access policy, spot-checking sources. Lighter use, with access to admin-only fields.

Every field in this document is tagged with which audience sees it and at what level of detail.

## The two views

The catalog UI has two primary views that share a data model but differ in density:

- **Catalog grid** (`/sources`) — a grid of source cards, one card per source, browseable with filters and search. Each card is a **summary projection** with ~10–15 fields. This is what a developer sees first.
- **Source detail page** (`/sources/<slug>`) — one source at a time, the full record, with tabs for different aspects (overview, recipe, evals, rewriter, sample prompts, access, lineage, audit). This is where developers go to confirm a choice and copy configuration.

The card is not a separate object from the source record; it is a projection of a subset of fields. Nothing on the card is invented; everything comes from the catalog. Different fields are visible at different scales.

## Section 1: Catalog grid card fields (browse view)

When a developer opens the catalog and sees a grid of source cards, each card shows the following fields. The order matters — this is visual priority from top to bottom of the card.

### Header section (always visible, largest visual weight)

| # | Field | Purpose |
|---|---|---|
| 1 | **Name** | The source's human-readable name. The single most important field. Example: "VA Clinical Practice Guidelines" |
| 2 | **Family badge** | Visual indicator of source family (`document`, `clinical_document`, `code`, `tabular`, `graph`, `external`). Color-coded and iconified. |
| 3 | **Status badge** | `Published` for browseable sources (the default filter hides other statuses from agent developers). Owners and admins see `Draft`, `Curated`, `Retired` too. |
| 4 | **Visibility badge** | `Public` or `Restricted`. Restricted sources show a lock icon and the groups that are allowed. |

### Description and context

| # | Field | Purpose |
|---|---|---|
| 5 | **Short description** | 1–2 sentences explaining what the source contains. The sentence that answers "is this source about the thing I care about?" |
| 6 | **Domain tags** | Owner-declared tags (`clinical`, `technical-docs`, `general-knowledge`, `source-code`, `regulated`, `public`, etc.). Used for filtering and for at-a-glance context. |
| 7 | **Languages** | List of primary languages in the corpus (`en`, `es`, `fr`, etc.). Shown only if it's not "just English." Matters for multilingual agents. |

### Quality signals — the load-bearing section for agent developer decisions

The grid card uses a **composite best-score** approach rather than a full per-LLM table. This keeps the card scannable at balanced density while preserving the per-LLM detail one click away on the detail page's At-a-glance block and Evaluations tab.

| # | Field | Purpose |
|---|---|---|
| 8 | **Best score (composite)** | The highest `recall_at_5` across all evaluated LLMs for this source, rendered as a single large number with the LLM name next to it. Example: `R@5 0.79 · gpt-4o`. This is the "is this any good at all" single data point. |
| 9 | **Rewrite lift delta on the best score** | If the rewriter is enabled, the best score is annotated with its lift: `(+0.18 with rewriter)`. Same evidence the rewriter is earning its keep, just expressed once instead of per-LLM. |
| 10 | **"See all N scores" drill-down** | A small affordance below the best score: `3 LLMs evaluated · see all scores`. Hover expands a tooltip showing every evaluated LLM's `recall_at_5` and rewrite lift; click goes to the detail page's Evaluations tab. |
| 11 | **Rewriter available badge** | A prominent badge indicating the rewriter is enabled on this source. Agent developers looking for rewriter support can filter by this. |
| 12 | **Latency hint** | Approximate p95 latency for a typical query (from recent eval runs), formatted as "~1.8s p95" or similar. Helps developers decide whether a source fits their per-turn latency budget. |
| 8a | **Answer quality** | The `answer_correctness` score from the most recent end-to-end eval run, rendered as a second large number below the retrieval best score. Example: `AQ 0.79 . granite-3.3-8b`. The pinned LLM name appears because all end-to-end evals use the same cluster-level pinned model for comparability. Only shown when the source has at least one end-to-end eval run. |
| 8b | **Faithfulness** | The `faithfulness` score from the same end-to-end eval run, rendered as a smaller annotation next to the answer quality score. Example: `Faith. 0.88`. Tells data owners "how well does my data keep agents grounded?" |

The retrieval score (R@5) remains the primary quality signal on the card. When end-to-end eval data is available, the answer quality and faithfulness line appears below it, giving the card two complementary views of quality: one for retrieval accuracy, one for agent answer correctness. Sources without end-to-end evals show only the retrieval score, so nothing changes for existing sources.

### Size and freshness

| # | Field | Purpose |
|---|---|---|
| 12 | **Size summary** | Family-appropriate: "184,302 documents," "18.4M chunks," "~50k code symbols," "180k rows." Helps developers calibrate "how much is in here." |
| 13 | **Last refresh** | Relative timestamp: "Refreshed 2 hours ago," "Refreshed 3 days ago." Critical for sources with volatile content (Wikipedia, docs). |
| 14 | **Refresh cadence** | "Weekly," "Nightly," "On demand," etc. Implies how fresh the data will *stay*. |

### Recipe headline (one-line summary)

| # | Field | Purpose |
|---|---|---|
| 15 | **Embedding model** | E.g. "nomic-embed-text-v1.5." Experienced developers will recognize these and form expectations. |
| 16 | **Chunking summary** | E.g. "semantic, 512 tok / 64 overlap." For code family: "AST-aware, symbol-level." For tabular: "per-row." |
| 17 | **Backend kind** | E.g. "pgvector," "Apache AGE (graph)," "DuckDB (tabular)." |

### Capability indicators

| # | Field | Purpose |
|---|---|---|
| 18 | **Retrieval patterns supported** | Small icons for each supported pattern: `vector_ann`, `vector_with_filters`, `graph_traverse_from_seed`, `structured_query`, `hybrid`. The developer can tell at a glance what query shapes the source handles. |
| 19 | **Agent writable badge** | If `agent_write_policy.allowed = true`, a badge ("Accepts agent writes") with hover tooltip showing the allowed modes. Most sources will not have this. |
| 20 | **Owner team** | Small text at the bottom. E.g. "clinical-informatics." A developer who wants to ask a question knows who to ask. |
| 21 | **Card completeness** | A small progress indicator next to the owner team name showing how completely the card's judgment-intensive fields are filled in (e.g., a ring showing 68% or a fraction like "8/12 fields"). Creates visibility into card quality without cluttering the card. Only counts judgment-intensive fields (guardrails, intended use, limitations, population coverage, conclusions), not mechanical fields (name, family, recipe). |

### Interaction affordances on the card

Every card has a small set of action buttons visible on hover or always-visible on touch devices:

- **Open** — go to the detail page.
- **Copy MCP config** — copies a ready-to-paste MCP configuration snippet for this source to the clipboard.
- **Test in playground** — opens the playground with this source pre-selected.
- **Bookmark** (if the signed-in user has a bookmarks feature) — adds to their "my sources" list.

## Section 2: Source detail page fields

When a developer clicks into a source, the detail page opens with tabs. Every field from the grid card is also present on the detail page (usually in the Overview tab), plus the following additions organized by tab.

### Action bar (always visible, above the tabs)

Four primary actions that live above the tabs and are visible on every sub-view of the detail page. These are the 90% workflow — everything else is in a tab.

| Action | Purpose |
|---|---|
| **🧪 Test in Playground** | Opens the Playground with this source pre-selected. Greyed out with a tooltip if the user doesn't have access. |
| **📋 Copy MCP Config** | Copies a ready-to-paste MCP configuration snippet to the clipboard. The snippet is tailored to the cluster's available transports (Kagenti MCP Gateway URL if present, LlamaStack connector config if present, direct Route for off-cluster consumers). |
| **📝 Copy Sample Prompt** | Copies the recommended system prompt for the user's "current LLM family" (settable per-user or picked from the best-evaluated LLM as default). |
| **📧 Contact Owner** | Opens a `mailto:` link to the source owner's contact emails, pre-populated with the source slug and a suggested question template. |
| **Download Card (JSON-LD)** | Downloads the source's full data card as a structured JSON-LD document. The export maps all card fields to Schema.org, PROV-O, and retrieval-hub vocabularies. Designed for AI agents and audit tooling that need machine-readable source metadata. |

### Access-required banner (detail page, shown only when the user lacks access)

When a developer opens a restricted source their agent identity cannot access, the detail page shows a banner above the tabs with the reason and next steps. The rest of the detail page remains browseable (so the developer can read the description, the eval scores, and the rewriter details to decide whether the source is worth requesting) — but action buttons like "Test in Playground" are disabled with a tooltip explaining why.

| Field | Purpose |
|---|---|
| **Banner heading** | E.g. "⚠ Access required" with a warning variant style. |
| **Your identity** | Shows the requesting identity's `sub` claim (truncated) and `rh_identity_kind`. Answers "which identity am I being evaluated as?" |
| **Your current groups** | List of the user's `rh_identity_groups` as pills. |
| **Required groups** | List of the source's `access.allowed_groups` as pills, with the missing ones highlighted. |
| **Owner contact** | The owner team name + a prominent "Contact Owner" button that opens a pre-populated `mailto:` link. |
| **Suggested email template** | A small expand-on-click preview of the email content, showing the subject line and body the mailto will populate. Gives the user confidence they'll send something reasonable. |

The banner is intentionally simple — no in-product request queue, no owner inbox, no approval workflow. The round-1 posture is "show the developer exactly what they need and who to ask, then let them handle it out-of-band." A full request-and-approval workflow is a round-2 feature (see "What's Open" below).

### Overview tab (default)

Everything from the card, plus:

| Field | Purpose |
|---|---|
| **At-a-glance block** | A dense `DescriptionList` with the headline quality/capability facts: best score + LLM + rewrite lift, other evaluated LLMs, latency p50/p95, cost hint, rewriter summary, retrieval patterns, agent write policy, refresh cadence + last refresh. When end-to-end eval data is available, the block also shows answer quality scores (answer_correctness, faithfulness, answer_relevancy) with the pinned model name and version. This is the "safety net" — everything on the card plus a few extras, visible without scrolling. |
| **Full description** (markdown-rendered) | Long-form description from the source owner. Can include sections, lists, links, images. Like a HuggingFace model card's main body. |
| **Intended use** | Structured display of `intended_use.primary_use` as a headline, `intended_use.secondary_uses` as a secondary list, and `intended_use.out_of_scope_uses` as a prominently displayed list. Replaces the previous free-text intended use and out-of-scope use fields with a structured presentation. |
| **Known limitations** | "This source does not contain X," "The embedding model has known weaknesses on Y," etc. Important for honest expectation-setting. |
| **Responsible use guidance** | A collapsible section rendering the source's structured fitness-for-use metadata. Shows `interpretation_guardrails` as a severity-colored list (red border for `error`, yellow for `warning`, blue for `info`), `supported_conclusions` with green accent, `unsupported_conclusions` with yellow accent and category badges (`scope`, `temporal`, `methodological`, `interpretive`), `population_coverage` and `excluded_populations` as a structured block, `measurement_technique` as rendered markdown, and `data_suppression_rules` as a list. Only sections with data are rendered; empty sections are omitted. The section heading shows a small completeness indicator for judgment-intensive fields. |
| **Quick Start section** | The most important copy-paste affordance: a numbered 3-step list showing (1) copy the MCP config, (2) copy the sample prompt for your LLM family, (3) ask your agent a representative question. If a developer can read this, copy two things, and have their agent answering questions in 5 minutes, retrieval-hub's value proposition is obvious. |
| **Headline figure** | One visual: a bar chart of eval scores per LLM, a pie chart of document types, a histogram of document ages, etc. Determined by family. |
| **Citation / how-to-cite** | If the owner wants downstream consumers to cite the source in agent outputs, a suggested citation format. |

### Recipe tab

| Field | Purpose |
|---|---|
| **Current recipe version** | Version number and active-since timestamp. |
| **Recipe YAML (rendered)** | The full recipe as a readable, syntax-highlighted YAML block. Parser, chunker, embedding, backend, retrieval patterns and their parameters. |
| **Recipe version history** | List of all recipe versions with timestamps, author, a one-line "what changed" summary, and a diff-vs-previous link. |
| **Diff-vs-version** tool | Pick any two recipe versions and see the diff. |
| **Tuning run history** | If AutoRAG (or similar) has been run against this source, the tuning runs with their scoreboard summaries and links to the full MLflow runs. |

### Retrieval patterns tab

| Field | Purpose |
|---|---|
| **Default pattern** | E.g. `vector_ann`. |
| **Supported patterns** | All patterns the source adapter exposes. Each with its parameters and defaults. |
| **Per-pattern parameter schema** | For each supported pattern, the typed parameter list with defaults, min/max bounds. This is what lets an advanced developer tune their query. |
| **Sample queries** | Copy-pasteable example queries for each pattern. |

### Evaluations tab

| Field | Purpose |
|---|---|
| **Eval suite** | Name, version, metric set, test case count, generation method (synthetic, hand-curated, hybrid), and a link to the MLflow dataset if applicable. |
| **Full eval run history** | Every eval run, filterable by LLM / rewrite-on-or-off / recipe version / date. Columns: LLM, recipe version, physical index, rewrite_enabled, timestamp, key metrics. |
| **Metric plots** | Recall@k over time, MRR over time, latency trend, cost trend. |
| **Per-LLM headline card** | One card per evaluated LLM with the latest scores. Shows the rewrite_lift delta explicitly. |
| **MLflow deep link** | Every eval run has a "view in MLflow" link to the full MLflow run for teams that want to drill into per-case results. |
| **Eval type filter** | A segmented control at the top of the tab: `All` / `Retrieval` / `End-to-End`. Filters the run history, metric plots, and comparison tool by eval suite type. Default is `All`. |
| **End-to-End Quality Summary** | When end-to-end eval runs exist, a summary card appears above the full run history showing all five RAGAS metrics (answer_correctness, faithfulness, answer_relevancy, context_precision, context_recall) plus retrieval metrics from the same run, the pinned model name and version, and links to MLflow and per-case results. |
| **Per-case results drill-down** | Each end-to-end eval run has a "View per-case results" link that opens a sortable/filterable table with per-test-case scores. Columns: Query, Answer Correctness, Faithfulness, Context Precision, Context Recall, Intent, Difficulty. Each row expands to show the generated answer, retrieved contexts, and reference answer side by side. |
| **Answer quality metric plots** | When end-to-end eval runs exist, new metric-over-time plots appear: answer_correctness over time and faithfulness over time, alongside the existing recall@k and MRR plots. |
| **Comparison** | Pick any two eval runs (different recipes, different LLMs, rewrite on/off) and see a side-by-side metric comparison. |

### Rewriter tab

| Field | Purpose |
|---|---|
| **Rewriter enabled status** | On or off. |
| **Shared template version** | E.g. "rh.rewriter.shared-core v7" with a link to the MLflow prompt registry entry. |
| **Override prompt** (if any) | Name + version. Most sources don't have one; the ones that do show their override template here. |
| **Vocabulary mappings** | The full list of `(lay_term, canonical_term, qualifiers)` entries. Searchable. |
| **Sample queries** | The curated `(raw_query, good_rewrites)` examples. |
| **Domain notes** | The markdown blob. |
| **Schema hints** | For tabular sources. |
| **Default LLM** | E.g. `granite-3.3-8b-instruct`. |
| **Max rewrites** | E.g. 5. |
| **LLM resolution policy** | `default` / `caller_optional` / `caller_required`. |
| **Test affordance** | Paste a raw query, see the rewrites live. The test call goes through the same rewriter the MCP tool would. |
| **Metadata version history** | Who changed what, when. |

### Sample prompts tab

| Field | Purpose |
|---|---|
| **Prompts by LLM family** | For each LLM family the owner has curated (e.g., `granite-3-*`, `llama-3.3-*`, `gpt-4o`, generic), the recommended system prompt. Copyable. |
| **Role** | Most are `system` prompts; some owners may also provide `user`-role prompts for specific flows. |
| **Copy button** per prompt | One click to clipboard. |

### Access and write policy tab

| Field | Purpose |
|---|---|
| **Visibility** | `public` or `restricted`. |
| **Allowed groups** | For restricted sources: the list of `rh_identity_groups` that can access. |
| **Agent write policy** | Is writes allowed? Which modes? Which groups? What validation schema? Recent write activity summary. |
| **Recent access** (admin only) | A log of who has accessed this source recently (aggregated, anonymized for non-admins). |

### Lineage tab

| Field | Purpose |
|---|---|
| **Origin** | Where the data came from: web crawl roots, S3 paths, git repos, database queries. The provenance. |
| **Refresh cadence** | Configured cadence, next scheduled refresh, last successful refresh. |
| **Ingestion runs** | Full history of ingestion runs with status, duration, document count, failures. Each run has a detail drill-down. |
| **Data snapshots** | For sources that keep historical snapshots, a list with timestamps and sizes. |
| **Contributors** | If the source accepts agent writes, a summary of who has contributed (by identity group). |
| **Measurement technique** | How the upstream source data was created or curated (e.g., "Expert committee consensus guidelines using GRADE methodology"). Distinct from the origin field which describes how retrieval-hub fetched the data. Rendered as markdown. |

### Audit tab (admin only)

| Field | Purpose |
|---|---|
| **State transitions** | Every lifecycle state change with who-what-when. |
| **Configuration changes** | Recipe bumps, rewriter metadata edits, access policy changes, sample prompt changes. |
| **Agent writes** | Every `append`/`upsert`/`annotate` with identity, timestamp, validated payload summary. |
| **Access decisions** | Recent allow/deny decisions, for post-hoc review. |
| **Related audit** in other systems | Deep links to MLflow for experiment runs, to Kagenti for identity audit if available. |

## Section 2b: Admin dashboard (round 1 minimal)

The admin dashboard is a **separate top-level view** from the catalog grid, accessible to users with `admin.read` scope. It is deliberately minimal in round 1 — most observability is delegated to the cluster's Prometheus + Grafana stack (see [`integrations/prometheus-grafana.md`](integrations/prometheus-grafana.md)), and most experiment data is delegated to MLflow. The admin view is the **retrieval-hub-native slice** of the full picture, plus deep links out to the specialist systems.

**Scope for round 1**: three panels on the landing page. Anomaly detection, per-identity usage breakdowns, and write activity drill-downs are round 2 features that land after we have real data to test against.

### Panel 1: Cluster health summary

A single dense panel at the top of the dashboard showing the state of the catalog as a whole. All fields read from catalog Postgres (no query log, no Prometheus scrape required).

| Field | Purpose |
|---|---|
| **Published source count** | Total sources in `Published` state. E.g. "47 published." |
| **Draft source count** | Total sources in `Draft` state. E.g. "3 drafts." |
| **Curated source count** | Total sources in `Curated` state (published pipeline not yet complete). E.g. "5 curated." |
| **Retired source count** | Total sources in `Retired` state. E.g. "1 retired." |
| **Sources with drift warnings** | Count of sources flagged as stale (last refresh > 2× cadence) or with degraded active physical index. E.g. "⚠ 2 sources flagged." Each flagged source is clickable to jump to its detail page. |
| **Most recent agent write** | Relative timestamp of the most recent audit record with an `append`/`upsert`/`annotate` action. E.g. "Last agent write: 4 hours ago." |
| **Deep link: "View observability dashboards in Grafana"** | A button that opens the cluster's Grafana retrieval-hub dashboard in a new tab. Shown only when the Grafana URL is configured; hidden otherwise. |
| **Deep link: "View experiment history in MLflow"** | A button that opens MLflow's experiments UI filtered to retrieval-hub's experiments. Shown only when MLflow is configured. |

### Panel 2: Top sources (round 1: by eval score + freshness, not query volume)

A table listing sources the admin should probably pay attention to. In round 1, this is sorted by a composite "health score" derived from catalog state — **not** by query volume, because query volume lives in Prometheus and we don't want to pull it into the catalog.

| Field | Purpose |
|---|---|
| **Source name + slug** | Click to open detail. |
| **Family** | Badge. |
| **Status** | Badge. |
| **Best eval score** | Composite best-score (same as grid card) to spot sources that have regressed. |
| **Last refresh** | Relative timestamp with color indicator (green/yellow/red). |
| **Physical index health** | `ok` / `degraded` / `failed` badge from the active physical index. |
| **Deep link: "Query metrics in Grafana"** | Per-row link that opens the Grafana dashboard pre-filtered to this source's metric labels. This is where admins go to see "how much is this being used" — retrieval-hub doesn't try to answer it. |

Default sort: problem sources first (drift warnings, degraded indexes, failed refreshes), then by recent change, then alphabetical.

### Panel 3: Recent catalog changes

The round-1 audit feed — a timeline of the most recent catalog mutations, read directly from the `audit_records` table. No aggregation, no anomaly detection, just a chronological list.

| Field | Purpose |
|---|---|
| **Timestamp** | Absolute and relative. |
| **Action** | E.g. `source.publish`, `source.recipe.bump`, `source.rewriter_metadata.edit`, `source.access.change`, `source.retire`. |
| **Actor** | Identity that made the change (human or service). Linkifiable to identity detail. |
| **Target source** | Slug with link to source detail. |
| **Diff / summary** | One-line description of what changed (e.g. "recipe v3 → v4", "access added clinical-agents"). |
| **Deep link: "View in audit log"** | Per-row link to the full audit record detail. |

Filter controls at the top: filter by action type, filter by actor, filter by source, filter by time range (last 24h, 7d, 30d, custom).

### Source-owner view (filtered admin view)

Source owners use the **same admin dashboard** with an automatic filter applied: every panel shows only sources the user owns or maintains. This is a deliberate design choice — rather than building a separate "my sources" view with its own layout, we reuse the admin dashboard and add a filter at the data layer. Benefits:

- **Less UI code** — one dashboard, two access paths.
- **Upward compatibility** — an owner who is granted admin scope sees the same panels with the filter removed.
- **Same mental model** — the admin and owner personas think about their catalog the same way, just with different scopes.

How the filter works:

| Scope held | Dashboard shows |
|---|---|
| `admin.read` (platform admin) | All sources on the cluster. |
| `admin.read` **AND** user is in a source's `owner_team` or `maintainers` | Full unfiltered view (owner inherits admin scope for their sources naturally). |
| `sources.read` only, but user is in a source's `owner_team` or `maintainers` | Filtered to only those owned/maintained sources. This is the source-owner view. |
| `sources.read` only, not an owner | Dashboard hidden; user lands on the catalog grid instead. |

The filter is implemented at the catalog layer (the `list_sources` call accepts a `scope_to_owned_by` parameter when the caller does not hold `admin.read`). The UI is unaware of which mode it's in beyond displaying a small indicator: either "Cluster view" or "My sources" at the top of the dashboard.

### Round 2 admin panels (not implemented in round 1)

These are listed here so we know where they'd slot in when we build them, but they are **deferred** and do not have data dictionary entries yet:

- **Anomaly detection panel** — threshold-based rules ("identity X has > Y 403s in Z minutes", "source X eval dropped by Y%", "source X stale for > Y × cadence"). Feeds into the cluster health summary's "flagged sources" counter in round 1, but without a dedicated UI.
- **Top consumers panel** — per-identity query volume and source affinity. Requires pulling Prometheus data into the UI, or embedding a Grafana iframe.
- **Agent write activity drill-down** — per-source write counts, per-identity write rates, validation failure rates. Some of this is already visible in the per-source Audit tab; the dashboard aggregation is the round-2 piece.
- **Abuse response actions** — "block identity" and similar mitigations. The buttons are deliberately stubbed in round 1 (UI surface exists, action is a no-op that logs and alerts rather than actually blocking). Real semantics land in round 2 or round 3 once we've decided what "block" means concretely. See [`auth.md`](auth.md) for the policy layer this would hook into.

### Deep-link-out pattern

The round-1 admin dashboard is intentionally thin because **observability belongs in Grafana, experiment history belongs in MLflow, and identity audit belongs in Kagenti/Keycloak**. Rather than duplicate any of those, the dashboard has a prominent row of deep-link buttons at the top of each panel:

- "View Grafana dashboards" → opens the cluster's retrieval-hub Grafana dashboard in a new tab. URL configured via `RETRIEVAL_HUB_GRAFANA_DASHBOARD_URL`; button hidden if unset.
- "View MLflow experiments" → opens MLflow UI filtered to retrieval-hub's experiment prefix.
- "View access audit in Keycloak" → opens Keycloak's admin UI (if accessible) filtered to recent events. Hidden if Keycloak is not reachable from the admin's browser.

This is the "consume what's there" philosophy from [`integrations/README.md`](integrations/README.md) applied to the UI layer. We don't rebuild Grafana panels; we link to them. We don't rebuild MLflow's experiment comparison view; we link to it. The retrieval-hub admin dashboard is the **entry point and catalog-specific view**, not the everything-about-retrieval-hub view.

## Section 3: Data dictionary

Formal schema for every field listed above. Columns:

- **Field name** — machine-readable name used in the catalog API, Postgres column name or JSONB key. If the field is only a UI label, this is `—`.
- **Type** — Python/JSON type: `string`, `int`, `timestamp`, `enum(...)`, `list[...]`, `object`, `markdown`, etc.
- **Source of truth** — which system holds the authoritative value. `catalog` = retrieval-hub Postgres. `mlflow` = MLflow. `llamastack` = LlamaStack. `kagenti` = Kagenti identity system. `computed` = derived in retrieval-hub code from other fields.
- **Display format** — how the UI renders the value. `as-is`, `relative time`, `markdown`, `percent`, `badge`, `iconified`, `tooltip`, etc.
- **Example** — a representative value.
- **Visibility** — who can see it and in which view. `grid` = on the card. `detail` = on the detail page. `admin` = admin-only. `owner` = owner-only.
- **Derived from** — if the field is a projection or computed, what it's derived from.

### Core identity fields

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `id` | `string` (UUID) | catalog | not displayed | `src_01HXYZ...` | — | — |
| `slug` | `string` | catalog | as-is, monospace | `va-clinical-guidelines` | grid + detail | — |
| `name` | `string` | catalog | as-is, heading | `"VA Clinical Practice Guidelines"` | grid + detail | — |
| `family` | `enum` | catalog | iconified badge | `clinical_document` | grid + detail | — |
| `status` | `enum` | catalog | badge | `published` | grid (with filter) + detail | — |
| `visibility` | `enum` | catalog | badge with icon | `public` | grid + detail | — |
| `description_short` | `string` (≤280 chars) | catalog | as-is | `"VA/DoD clinical practice guidelines..."` | grid + detail | — |
| `description_long` | `markdown` | catalog | rendered markdown | (multi-paragraph) | detail | — |
| `known_limitations` | `markdown` | catalog | rendered markdown | `"Corpus does not include..."` | detail | — |
| `domain_tags` | `list[string]` | catalog | tag pills | `["clinical", "regulated", "public"]` | grid + detail | — |
| `languages` | `list[string]` | catalog | flag pills; hidden if only `["en"]` | `["en"]`, `["en", "es"]` | grid (conditional) + detail | — |
| `citation_format` | `string` | catalog | monospace block | `"VA/DoD Clinical Practice Guideline (2023), §X.Y"` | detail | — |

### Ownership and contact

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `owner_team` | `string` | catalog | as-is | `clinical-informatics` | grid + detail | — |
| `owner_contacts` | `list[string]` (emails) | catalog | mailto links | `["alice@example.com"]` | detail | — |
| `maintainers` | `list[string]` | catalog | mailto links | `["bob@example.com"]` | detail | — |
| `created_at` | `timestamp` | catalog | relative + tooltip absolute | `"Created 6 months ago"` | detail | — |
| `created_by` | `string` (identity sub) | catalog | as-is | `user:alice` | detail (admin) | — |
| `updated_at` | `timestamp` | catalog | relative | `"Updated 2 days ago"` | detail | — |
| `updated_by` | `string` | catalog | as-is | `user:alice` | detail (admin) | — |

### Recipe and retrieval

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `recipe.version` | `int` | catalog | monospace, inline with recipe | `v3` | grid (abbreviated) + detail | — |
| `recipe.content` | `object` (JSONB) | catalog | syntax-highlighted YAML block | (full recipe) | detail | — |
| `recipe.parser.kind` | `string` | catalog | as-is | `docling` | detail | `recipe.content.parser.kind` |
| `recipe.chunker.kind` | `string` | catalog | as-is | `semantic` | detail | `recipe.content.chunker.kind` |
| `recipe.chunker.summary` | `string` | computed | e.g. "512 tok / 64 overlap" | `"512 tok / 64 overlap"` | grid + detail | computed from chunker params |
| `recipe.embedding.model` | `string` | catalog | as-is, monospace | `nomic-embed-text-v1.5` | grid + detail | `recipe.content.embedding.model` |
| `recipe.embedding.dimension` | `int` | catalog | as-is | `768` | detail | |
| `recipe.backend.kind` | `string` | catalog | as-is | `pgvector` | grid + detail | |
| `retrieval.default_pattern` | `enum` | catalog | badge | `vector_ann` | detail | |
| `retrieval.supported_patterns` | `list[enum]` | catalog | iconified list | `[vector_ann, vector_with_filters]` | grid + detail | |
| `retrieval.parameters` | `object` | catalog | typed parameter table per pattern | (see pattern-specific) | detail | |
| `recipe_version_history` | `list[object]` | catalog | timeline | (list of RecipeVersion rows) | detail | — |

### Physical indexes

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `active_physical_index.id` | `string` (UUID) | catalog | monospace, truncated | `pidx_01HXZ...` | detail | — |
| `active_physical_index.backend_kind` | `string` | catalog | as-is | `pgvector` | detail | — |
| `active_physical_index.location` | `string` | catalog | monospace | `idx_va_cpg_v3` | detail (owner) | — |
| `active_physical_index.built_at` | `timestamp` | catalog | relative + absolute | `"Built 2 hours ago"` | detail | — |
| `active_physical_index.document_count` | `int` | catalog | formatted with separators | `184,302` | grid + detail | |
| `active_physical_index.health` | `enum` | catalog | colored badge | `ok` / `degraded` / `failed` | detail | — |
| `all_physical_indexes` | `list[PhysicalIndex]` | catalog | table | (all indexes) | detail (owner) | — |

### Size summary (for the grid card)

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `size_summary` | `string` | computed | as-is | `"184,302 documents"` / `"50k symbols"` / `"2.3M rows"` | grid + detail | family-specific: `document_count`, `chunk_count`, `row_count`, or `node_count` |
| `chunk_count_total` | `int` | catalog | formatted | `1,842,010` | detail | summed across active index |

### Evaluation fields

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `headline_llms` | `list[string]` | admin config | — | `["granite-3.3-8b-instruct", "llama-3.3-70b-instruct", "gpt-4o"]` | — | cluster admin setting |
| `card_best_score` | `object` | computed | large number + LLM name | `{llm: "gpt-4o", metric: "recall_at_5", value: 0.79, rewrite_lift: 0.18}` | grid + detail at-a-glance | projection: max(recall_at_5) across all evaluated LLMs |
| `card_best_score.llm` | `string` | computed | as-is, secondary text | `gpt-4o` | grid | — |
| `card_best_score.value` | `float` | computed | 2 decimal places, large font | `0.79` | grid | max across evaluated LLMs |
| `card_best_score.rewrite_lift` | `float` | computed | signed delta, annotated | `+0.18` | grid | delta on the same LLM that produced the best score |
| `card_eval_score_count` | `int` | computed | small footnote, e.g. "3 LLMs evaluated" | `3` | grid | count of distinct LLMs in recent eval runs |
| `card_evaluated_llms` | `list[object]` | catalog | expand-on-hover tooltip showing all per-LLM scores | `[{llm: "granite-3.3-8b", recall_at_5: 0.74, rewrite_lift: 0.27}, ...]` | grid (hover) + detail | projection from latest EvalRun per LLM |
| `card_evaluated_llms[n].llm` | `string` | catalog | as-is | `granite-3.3-8b-instruct` | grid (hover) + detail | |
| `card_evaluated_llms[n].recall_at_5` | `float` | catalog | 2 decimal places | `0.74` | grid (hover) + detail | computed by retrieval-hub |
| `card_evaluated_llms[n].mrr` | `float` | catalog | 2 decimal places | `0.68` | detail | computed by retrieval-hub |
| `card_evaluated_llms[n].rewrite_lift_at_5` | `float` | catalog | signed delta | `+0.27` | grid (hover) + detail | computed from two-run delta |
| `card_evaluated_llms[n].eval_run_id` | `string` | catalog | link | `evr_...` | detail | — |
| `card_evaluated_llms[n].mlflow_run_id` | `string` (when MLflow present) | mlflow (via catalog pointer) | link to MLflow | `mlfr_...` | detail | catalog lineage pointer |
| `card_evaluated_llms[n].source_system` | `enum` | catalog | small badge | `llamastack` / `native` / `imported` | detail | where the eval was computed |
| `latency_p95_hint` | `string` | computed | e.g. `"~1.8s p95"` | `"~1.8s p95"` | grid + detail | averaged from recent eval runs |
| `cost_estimate_hint` | `string` | computed | e.g. `"~1.2k tokens/query"` | `"~1.2k tokens/query"` | detail | averaged from recent eval runs |
| `card_answer_quality` | `object` | computed | large number + LLM name | `{llm: "granite-3.3-8b", answer_correctness: 0.79, faithfulness: 0.88}` | grid + detail at-a-glance | projection from most recent end-to-end eval run |
| `card_answer_quality.llm` | `string` | computed | as-is, secondary text | `granite-3.3-8b` | grid | from `e2e_pinned_llm` on the eval run |
| `card_answer_quality.answer_correctness` | `float` | computed | 2 decimal places, large font | `0.79` | grid | from most recent end-to-end eval run scores |
| `card_answer_quality.faithfulness` | `float` | computed | 2 decimal places, smaller font | `0.88` | grid | from most recent end-to-end eval run scores |
| `card_has_e2e_eval` | `bool` | computed | controls AQ line visibility | `true` | grid | `EXISTS(end-to-end eval run for this source)` |
| `card_answer_quality.answer_relevancy` | `float` | computed | 2 decimal places | `0.83` | detail at-a-glance | from most recent end-to-end eval run scores |
| `card_answer_quality.context_precision` | `float` | computed | 2 decimal places | `0.72` | detail at-a-glance | from most recent end-to-end eval run scores |
| `card_answer_quality.context_recall` | `float` | computed | 2 decimal places | `0.81` | detail at-a-glance | from most recent end-to-end eval run scores |
| `e2e_pinned_llm` | `string` | admin config | monospace, secondary text | `granite-3.3-8b-instruct` | detail | cluster-level admin setting |
| `e2e_pinned_llm_version` | `string` | admin config | monospace, secondary text | `v2026.04` | detail | cluster-level admin setting |
| `full_eval_history` | `list[EvalRun]` | catalog (with MLflow links) | filterable table | (all eval runs) | detail | — |
| `eval_suite` | `EvalSuite` | catalog | detail card | (full suite) | detail | — |

### Rewriter fields

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `rewriter_enabled` | `bool` | catalog | badge on grid; section on detail | `true` | grid + detail | — |
| `rewriter_shared_template_pointer` | `string` | catalog | monospace | `rh.rewriter.shared-core` | detail | — |
| `rewriter_shared_template_version` | `int` | catalog | version number | `7` | detail | MLflow prompt version when present |
| `rewriter_shared_template_mlflow_link` | `string` (URL) | computed | deep link | (MLflow URL) | detail | catalog + MLFLOW_TRACKING_URI |
| `rewriter_metadata_version` | `int` | catalog | version number | `4` | detail | — |
| `rewriter_vocabulary_mappings` | `list[object]` | catalog | searchable table | 53 entries | detail | — |
| `rewriter_vocabulary_mapping_count` | `int` | computed | count on detail (not grid) | `53` | detail | len(vocabulary_mappings) |
| `rewriter_sample_queries` | `list[object]` | catalog | table with raw_query + good_rewrites | 12 entries | detail | — |
| `rewriter_domain_notes` | `markdown` | catalog | rendered markdown | (paragraph) | detail | — |
| `rewriter_schema_hints` | `object` (tabular only) | catalog | typed table | (schema) | detail | — |
| `rewriter_prompt_override_id` | `string` (nullable) | catalog | reference chip | `null` or `rh.rewriter.override.va-specific` | detail | — |
| `rewriter_default_llm` | `string` | catalog | monospace | `granite-3.3-8b-instruct` | detail | — |
| `rewriter_llm_resolution` | `enum` | catalog | badge | `default` | detail | — |
| `rewriter_max_rewrites` | `int` | catalog | as-is | `5` | detail | — |

### Sample prompts

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `sample_prompts` | `list[SamplePrompt]` | catalog | tabbed by LLM family; copy button per | (list) | detail | — |
| `sample_prompts[n].applies_to_llm_family` | `string` (pattern) | catalog | tab label | `granite-3-*` | detail | — |
| `sample_prompts[n].role` | `enum` | catalog | label | `system` | detail | — |
| `sample_prompts[n].text` | `markdown` | catalog | pre-wrapped code block with copy | (text) | detail | — |

### Freshness and lineage

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `last_refresh_at` | `timestamp` | catalog | relative + tooltip absolute | `"2 hours ago"` | grid + detail | — |
| `refresh_cadence` | `string` | catalog | as-is | `weekly` | grid + detail | — |
| `next_scheduled_refresh_at` | `timestamp` | computed | relative | `"in 5 days"` | detail | last_refresh_at + cadence |
| `lineage.origin` | `object` | catalog | origin card (kind + config) | (object) | detail | — |
| `lineage.origin.kind` | `enum` | catalog | label | `web_crawl` | detail | — |
| `lineage.origin.config` | `object` | catalog | rendered as summary | (config) | detail (owner) | — |
| `ingestion_runs` | `list[IngestionRun]` | catalog | timeline | (list) | detail | — |
| `ingestion_runs[n].status` | `enum` | catalog | colored badge | `completed` | detail | — |
| `ingestion_runs[n].started_at` | `timestamp` | catalog | absolute | `2026-04-05T12:00:00Z` | detail | — |
| `ingestion_runs[n].document_count` | `int` | catalog | formatted | `184,302` | detail | — |
| `ingestion_runs[n].triggered_by` | `string` | catalog | as-is | `user:alice` or `scheduler:refresh-cron` | detail | — |

### Responsible use metadata

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `responsible_use.measurement_technique` | `markdown` | catalog | rendered markdown | `"Expert committee consensus..."` | detail (overview + lineage) | -- |
| `responsible_use.interpretation_guardrails` | `list[object]` | catalog | severity-colored list | (list of guardrail objects) | detail | -- |
| `responsible_use.interpretation_guardrails[n].guardrail` | `string` | catalog | as-is | `"This source does not contain post-2024 guidelines"` | detail | -- |
| `responsible_use.interpretation_guardrails[n].severity` | `enum(error, warning, info)` | catalog | colored badge | `error` (red) | detail | -- |
| `responsible_use.interpretation_guardrails[n].explanation` | `string` | catalog | expandable text | `"The corpus freeze date..."` | detail | -- |
| `responsible_use.supported_conclusions` | `list[object]` | catalog | green-accented list | (list) | detail | -- |
| `responsible_use.supported_conclusions[n].conclusion` | `string` | catalog | as-is | `"Treatment recommendations for adult hypertension"` | detail | -- |
| `responsible_use.supported_conclusions[n].basis` | `string` | catalog | secondary text | `"Comprehensive VA/DoD CPG..."` | detail | -- |
| `responsible_use.unsupported_conclusions` | `list[object]` | catalog | yellow-accented list | (list) | detail | -- |
| `responsible_use.unsupported_conclusions[n].conclusion` | `string` | catalog | as-is | `"Pediatric treatment protocols"` | detail | -- |
| `responsible_use.unsupported_conclusions[n].category` | `enum(scope, temporal, methodological, interpretive)` | catalog | badge | `scope` | detail | -- |
| `responsible_use.unsupported_conclusions[n].reason` | `string` | catalog | secondary text | `"Guidelines are adult-focused..."` | detail | -- |
| `responsible_use.population_coverage` | `object` | catalog | structured block | (object) | detail | -- |
| `responsible_use.population_coverage.target_population` | `string` | catalog | as-is | `"US military veterans..."` | detail | -- |
| `responsible_use.population_coverage.sampling_frame` | `string` | catalog | as-is | `"VA/DoD clinical practice..."` | detail | -- |
| `responsible_use.population_coverage.estimated_coverage` | `string` | catalog | as-is | `"Adult populations served by VA..."` | detail | -- |
| `responsible_use.excluded_populations` | `list[string]` | catalog | bulleted list | `["Pediatric patients...", ...]` | detail | -- |
| `responsible_use.data_suppression_rules` | `list[object]` | catalog | list (shown only when present) | (list) | detail | -- |
| `responsible_use.data_suppression_rules[n].rule` | `string` | catalog | as-is | `"Patient identifiers removed"` | detail | -- |
| `responsible_use.data_suppression_rules[n].method` | `string` | catalog | secondary text | `"De-identification per HIPAA Safe Harbor"` | detail | -- |
| `responsible_use.intended_use` | `object` | catalog | structured display | (object) | detail | -- |
| `responsible_use.intended_use.primary_use` | `string` | catalog | headline text | `"RAG context for agents..."` | detail | -- |
| `responsible_use.intended_use.secondary_uses` | `list[string]` | catalog | bulleted list | `["Clinical decision support..."]` | detail | -- |
| `responsible_use.intended_use.out_of_scope_uses` | `list[string]` | catalog | prominent bulleted list | `["Direct patient-facing medical advice..."]` | detail | -- |
| `card_completeness` | `object` | computed | progress ring on grid; full breakdown on detail | `{overall: 0.82, mechanical: 0.95, judgment: 0.68}` | grid (ring) + detail + admin | computed from field population checks |
| `card_completeness.overall` | `float` | computed | percentage or ring | `0.82` | grid + admin | fraction of all recommended fields populated |
| `card_completeness.mechanical` | `float` | computed | percentage | `0.95` | detail + admin | name, version, family, recipe, lineage fields |
| `card_completeness.judgment` | `float` | computed | percentage | `0.68` | detail + admin | guardrails, limitations, intended_use, population_coverage, conclusions |
| `card_completeness.missing_fields` | `list[string]` | computed | list | `["data_suppression_rules", "supported_conclusions"]` | detail (owner) | field names not yet populated |
| `jsonld_export_url` | `string` | computed | download button | `/sources/va-clinical-guidelines/card.jsonld` | detail (action bar) | source slug + endpoint |

### Access and write policy

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `access.visibility` | `enum` | catalog | badge | `public` / `restricted` | grid + detail | — |
| `access.allowed_groups` | `list[string]` | catalog | tag pills | `["clinical-agents"]` | detail | — |
| `agent_write_policy.allowed` | `bool` | catalog | badge on grid; section on detail | `false` (default) | grid (badge if true) + detail | — |
| `agent_write_policy.scope_required` | `string` | catalog | monospace | `sources.write` | detail | — |
| `agent_write_policy.allowed_groups` | `list[string]` | catalog | tag pills | `["clinical-writers"]` | detail | — |
| `agent_write_policy.write_modes` | `list[enum]` | catalog | iconified list | `[append, annotate]` | detail | — |
| `agent_write_policy.write_validation` | `object` (nullable) | catalog | schema reference | `null` or `{schema_id: clinical_note_v1}` | detail | — |
| `recent_write_activity_summary` | `object` | catalog | small stat block | `"23 writes in last 7 days from 4 identities"` | detail | computed from audit |

### Audit fields (admin visibility)

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `audit.state_transitions` | `list[AuditRecord]` | catalog | timeline | (list) | detail (admin) | — |
| `audit.configuration_changes` | `list[AuditRecord]` | catalog | table | (list) | detail (admin + owner) | — |
| `audit.agent_writes` | `list[AuditRecord]` | catalog | searchable table | (list) | detail (admin + owner) | — |
| `audit.recent_access_decisions` | `list[AccessDecision]` | catalog | anonymized summary | (list) | detail (admin) | — |

### Capability summaries for the card (computed projections)

These fields exist specifically to render badges and icons on the grid card without requiring the UI to load the full source record.

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `card_badges.rewriter_available` | `bool` | computed | badge if true | `true` | grid | `rewriter_enabled` |
| `card_badges.agent_writable` | `bool` | computed | badge if true | `false` | grid | `agent_write_policy.allowed` |
| `card_badges.supported_patterns_summary` | `list[enum]` | computed | iconified row | `[vector_ann, graph_traverse_from_seed]` | grid | `retrieval.supported_patterns` (capped at 3 most relevant) |
| `card_badges.family` | `enum` | catalog | iconified badge | `clinical_document` | grid | `family` |
| `card_badges.visibility` | `enum` | catalog | badge with icon | `public` | grid | `access.visibility` |

### Deep links to other systems

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `mcp_config_snippet` | `string` | computed | code block with copy button | (JSON snippet) | grid (hover) + detail | cluster config + source slug |
| `mlflow_experiment_url` | `string` (URL, nullable) | computed | link if MLflow present | (URL) | detail | MLFLOW_TRACKING_URI + experiment name |
| `ai_assets_entry_url` | `string` (URL, nullable) | computed | link if AI Assets registered | (URL) | detail | AI Assets registry |
| `kagenti_toolgroup_name` | `string` (nullable) | computed | monospace | `mcp::retrieval-hub::query` | detail | naming convention |

### Playground

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| (playground inputs) | (form) | UI state | interactive form | — | detail | — |
| `playground.query_input` | `string` | UI state | text box | (user input) | detail | — |
| `playground.top_k` | `int` | UI state | number input | `10` | detail | — |
| `playground.use_rewrite` | `bool` | UI state | checkbox | `false` | detail | — |
| `playground.rewrites_used` | `list[string]` | computed (from rewrite call) | bulleted list | (rewritten queries) | detail | rewriter result |
| `playground.results` | `list[RetrievalResult]` | computed (from query call) | result card list | (hits) | detail | query result |
| `playground.result.lineage` | `object` | catalog | small footer on each result | `"pidx_... · recipe v3"` | detail | result.lineage |

### Access-required banner fields

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `access_banner.shown` | `bool` | computed | banner visibility | `true` when user lacks access | detail | `!can_access(identity, source, "query")` |
| `access_banner.your_identity_sub` | `string` | computed from JWT | as-is, truncated | `agent:spiffe://cluster.local/ns/research/sa/medical-bot` | detail | identity.sub |
| `access_banner.your_identity_kind` | `enum` | computed from JWT | badge | `agent` | detail | identity.kind |
| `access_banner.your_groups` | `list[string]` | computed from JWT | pill list | `[research-agents, general-agents]` | detail | identity.groups |
| `access_banner.required_groups` | `list[string]` | catalog | pill list, missing highlighted | `[clinical-agents, clinical-reviewers]` | detail | source.access.allowed_groups |
| `access_banner.owner_team` | `string` | catalog | as-is | `clinical-informatics` | detail | source.owner_team |
| `access_banner.owner_contacts` | `list[string]` | catalog | mailto links | `["alice@example.com"]` | detail | source.owner_contacts |
| `access_banner.mailto_subject` | `string` | computed | mailto `?subject=` param | `"Access request: va-clinical-guidelines"` | detail | source.slug + template |
| `access_banner.mailto_body` | `string` | computed | mailto `?body=` param with template | (multi-line template) | detail | source.slug + identity + required groups |
| `access_banner.suggested_email_preview` | `string` | computed | expand-on-click preview | (body text) | detail | same as mailto_body |

### Admin dashboard — cluster health panel

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `admin.cluster_health.published_count` | `int` | catalog | large number + label | `47` | admin + owner (filtered) | `COUNT(*) FROM sources WHERE status='published'` |
| `admin.cluster_health.draft_count` | `int` | catalog | number + label | `3` | admin + owner (filtered) | `COUNT(*) WHERE status='draft'` |
| `admin.cluster_health.curated_count` | `int` | catalog | number + label | `5` | admin + owner (filtered) | `COUNT(*) WHERE status='curated'` |
| `admin.cluster_health.retired_count` | `int` | catalog | number + label | `1` | admin + owner (filtered) | `COUNT(*) WHERE status='retired'` |
| `admin.cluster_health.flagged_count` | `int` | computed | warning badge with drill-down | `2` | admin + owner (filtered) | count of sources with drift or degraded index |
| `admin.cluster_health.last_agent_write_at` | `timestamp` | catalog | relative time | `"4 hours ago"` | admin + owner (filtered) | `MAX(occurred_at) FROM audit_records WHERE action LIKE 'source.write.%'` |
| `admin.cluster_health.grafana_dashboard_url` | `string` (URL, nullable) | config | deep link button | (URL) | admin + owner | `RETRIEVAL_HUB_GRAFANA_DASHBOARD_URL` env var |
| `admin.cluster_health.mlflow_experiments_url` | `string` (URL, nullable) | config | deep link button | (URL) | admin + owner | computed from `MLFLOW_TRACKING_URI` + experiment prefix |
| `admin.cluster_health.keycloak_admin_url` | `string` (URL, nullable) | config | deep link button | (URL) | admin only | config |

### Admin dashboard — top sources panel

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `admin.top_sources` | `list[object]` | catalog | sortable table | (list) | admin + owner (filtered) | projection from source records |
| `admin.top_sources[n].slug` | `string` | catalog | link | `va-clinical-guidelines` | admin + owner (filtered) | |
| `admin.top_sources[n].name` | `string` | catalog | as-is | `"VA Clinical Practice Guidelines"` | admin + owner (filtered) | |
| `admin.top_sources[n].family` | `enum` | catalog | badge | `clinical_document` | admin + owner (filtered) | |
| `admin.top_sources[n].status` | `enum` | catalog | badge | `published` | admin + owner (filtered) | |
| `admin.top_sources[n].best_score` | `float` | computed | same as grid card composite | `0.79` | admin + owner (filtered) | `card_best_score.value` |
| `admin.top_sources[n].last_refresh_at` | `timestamp` | catalog | relative + color indicator | `"2 hours ago"` (green) | admin + owner (filtered) | |
| `admin.top_sources[n].physical_index_health` | `enum` | catalog | badge | `ok` / `degraded` / `failed` | admin + owner (filtered) | active_physical_index.health |
| `admin.top_sources[n].grafana_source_dashboard_url` | `string` (URL, nullable) | computed | per-row deep link | (URL with label filter) | admin | `GRAFANA_DASHBOARD_URL` + `?var-source=<slug>` |
| `admin.top_sources[n].card_completeness_judgment` | `float` | computed | percentage with color indicator | `0.68` (yellow) | admin + owner (filtered) | `card_completeness.judgment` |

### Admin dashboard — recent catalog changes panel

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `admin.recent_changes` | `list[AuditRecord]` | catalog | timeline | (list) | admin + owner (filtered) | `audit_records` ordered by `occurred_at DESC`, limited to last N items |
| `admin.recent_changes[n].occurred_at` | `timestamp` | catalog | absolute + relative | `2026-04-08 11:40 (2h ago)` | admin + owner (filtered) | |
| `admin.recent_changes[n].action` | `string` | catalog | monospace badge | `source.recipe.bump` | admin + owner (filtered) | |
| `admin.recent_changes[n].identity_sub` | `string` | catalog | as-is, truncated | `user:alice` | admin + owner (filtered) | |
| `admin.recent_changes[n].source_slug` | `string` | catalog (join) | link to source detail | `rh-product-docs` | admin + owner (filtered) | |
| `admin.recent_changes[n].summary` | `string` | computed | one-line description | `"recipe v3 → v4"` | admin + owner (filtered) | from `details` JSON |

### Admin view scoping

| Field name | Type | Source of truth | Display format | Example | Visibility | Derived from |
|---|---|---|---|---|---|---|
| `admin_view_scope` | `enum` | computed | small indicator at top of dashboard | `"Cluster view"` or `"My sources (5)"` | admin + owner | `admin.read` scope presence + owner/maintainer lookup |
| `admin_view_scope.filter_applied` | `bool` | computed | (internal) | `false` for admin, `true` for owner | admin + owner | |
| `admin_view_scope.owned_source_ids` | `list[string]` | computed | (internal, used for filter) | `[src_01..., src_02...]` | — | query: sources where user in `owner_team` or `maintainers` |

## What's Decided

### Views and layout
- **Three top-level views**: catalog grid (with the card projection), source detail page (with tabs), admin dashboard (minimal round 1 scope). Source owners see the admin dashboard **filtered to their owned sources** — same UI, different data scope.
- **The card is a projection of the source record**, not a separate object. Nothing displayed is invented; everything traces to a catalog field or a computed derivation.
- **Three audiences**: agent developers (primary), source owners (secondary — they see the catalog as consumers AND the admin dashboard as owners), platform admins (tertiary — full admin view). Every field is tagged with visibility.
- **Balanced density** on the grid card is the default. Compact and Expanded are not round-1 features.
- **HuggingFace model card analogy**: developers should decide from the card whether to use a source, without reading external docs. Everything they need is visible (or one click away in the detail page).

### Quality signals
- **Composite best-score on the grid card**, not a full per-LLM table. The card shows the highest `recall_at_5` across evaluated LLMs with the LLM name, plus the rewrite lift on that LLM. Full per-LLM breakdown is one click away in the detail page's At-a-glance block and Evaluations tab, and one hover away via tooltip on the card.
- **End-to-end answer quality scores on the card** when available. Two headline metrics: `answer_correctness` (the AI-developer number: "does this source make my app more knowledgeable?") and `faithfulness` (the data-owner number: "does my data keep agents grounded?"). Three detail metrics (answer_relevancy, context_precision, context_recall) appear on the detail page's At-a-glance block and Evaluations tab. All end-to-end evals use a cluster-level pinned LLM so scores are comparable across sources.
- **Eval results can come from LlamaStack (primary), retrieval-hub native orchestrator (fallback), or be imported from external runs** (e.g., LlamaStack eval runs that happened outside retrieval-hub's workflow). The `source_system` field on each evaluated-LLM row shows which backend produced the result.
- **MLflow deep links** for full eval run details when MLflow is present. We do not reimplement MLflow's UI; we link into it.

### Detail page layout
- **Action bar above the tabs** — four primary actions (Test in Playground, Copy MCP Config, Copy Sample Prompt, Contact Owner) visible on every tab of the detail page.
- **At-a-glance block on the Overview tab** — dense DescriptionList at the top of Overview showing headline quality/capability facts without scrolling.
- **Quick Start section on the Overview tab** — the 3-step numbered copy-paste flow (MCP config, sample prompt, representative question) that turns "I decided to use this" into "my agent is using this" in under five minutes.

### Permission flow (round 1: simple mailto)
- **Access-required banner** on the detail page when the user lacks access to a restricted source. Shows your identity, your current groups, the required groups, and a "Contact Owner" button that opens a `mailto:` link with a pre-populated subject and body template.
- **No in-product request queue, no owner inbox, no approval workflow in round 1.** The request-and-approval workflow is a deliberate round-2 feature. Round 1's posture is "show the developer exactly what they need and who to ask."

### Admin dashboard (round 1 minimal)
- **Three panels in round 1**: Cluster health summary, Top sources (by eval health + freshness, not query volume), Recent catalog changes.
- **Observability is delegated to Prometheus + Grafana.** The admin dashboard has prominent deep-link buttons to the cluster's Grafana retrieval-hub dashboard; retrieval-hub does not maintain a native query log. See [`integrations/prometheus-grafana.md`](integrations/prometheus-grafana.md).
- **Experiment history is delegated to MLflow.** Deep links to MLflow's experiments UI for eval run drill-downs.
- **Source owners see the admin dashboard filtered to their owned sources.** Same UI, different scope. Implemented at the catalog query layer via a `scope_to_owned_by` parameter applied when the caller does not hold `admin.read`.
- **Round 2 admin panels** (anomaly detection, top consumers, agent write activity drill-down, abuse response actions) are deferred. "Block identity" button UI exists but is stubbed in round 1 — it logs and alerts rather than actually blocking. Real semantics land in round 2+.

### Responsible use and governance
- **Responsible use guidance section on the detail page** shows structured fitness-for-use metadata: interpretation guardrails (with severity coloring), supported/unsupported conclusions (with category badges), population coverage and exclusions, measurement technique, and data suppression rules. All fields are optional and owner-declared. Only populated sections are rendered.
- **Card completeness** is a computed governance metric shown as a subtle indicator on the grid card and as a column in the admin dashboard's top sources panel. It distinguishes mechanical field completion from judgment-intensive field completion, creating healthy pressure on source owners to document guardrails and limitations.
- **JSON-LD card export** is available as a "Download Card" action on the detail page and via API. Designed for AI agents and audit tooling.

### General principles
- **No invented fields for visual polish**. Every field on the card has a real use case behind it. No "featured source" stickers, no fake popularity counts.
- **Computed projections are explicit**. Anything displayed that isn't stored directly in the catalog is marked as `computed` in the data dictionary with its derivation documented.
- **Consume what's there**. The UI links out to Grafana (observability), MLflow (experiments), Keycloak (identity audit) rather than duplicating any of them. This is the `integrations/README.md` philosophy applied at the UI layer.
- **Copyable configuration**. `mcp_config_snippet` and sample prompts are prominent because "how do I connect my agent to this source" is the action a developer takes immediately after deciding to use it.

## What's Open

- **Visual hierarchy of the quality signals section** — how to weight the LLM score rows against the rewrite lift delta and the latency hint. This is a stage-2 design call, not a data-dictionary one, but it affects how card real estate is allocated.
- **Visual hierarchy when both retrieval and answer quality scores are present.** The grid card now has two quality-signal rows (retrieval R@5 + rewrite lift, and answer quality AQ + faithfulness). Stage 2 needs to design how these two rows relate visually -- whether the AQ line is the same size as the R@5 line or slightly smaller, and how to handle the case where a source has retrieval scores but no end-to-end scores yet.
- **Answer quality trend over recipe changes.** The Evaluations tab could show how end-to-end scores change across recipe versions, which would help source owners see whether a recipe change improved agent answer quality, not just retrieval metrics. Requires enough data points (multiple recipe versions with end-to-end evals) to be useful.
- **The `headline_llms` admin setting.** Round-1 default is "the three most recently evaluated LLMs on the cluster," but the admin may want to pin a specific set. UI for setting this is round 2.
- **Featured / curated / recommended sources.** HuggingFace has "trending" and "featured" model lists. We could too, but it's editorial overhead and risks the catalog becoming a popularity contest rather than a reliable reference. Deferred.
- **Community feedback mechanisms.** HuggingFace has comments, discussions, and likes. We probably don't want comments on sources (the feedback loop is owner-run curation, not community discussion), but some form of "this source worked for me" signal from consumers is worth thinking about. Round 2 or later.
- **Internationalization of card fields.** The short description, intended use, out-of-scope use, etc. are written by owners in one language (usually English). Multi-language sources may want multi-language descriptions. Out of scope for round 1.
- **The `languages` field definition.** Is it ISO 639-1 codes? ISO 639-3? Display as flags or as labels? Pin when we have a multi-language source to design against.
- **How owners declare `intended_use` / `out_of_scope_use` / `known_limitations`.** These are free-form markdown in the data model, but the UI for writing them should nudge owners toward good content. Stage-2 UI concern.
- **Latency and cost hints from past eval runs vs. live measurement.** Currently the hints are averages from recent eval runs. A live "this source is currently responding in ~X ms" indicator from health checks would be nicer. Round 2.
- **The "contact" or "ask a question" affordance.** A button that opens an email to the owner team? A link to a per-source discussion channel? Depends on the customer environment. Out of round 1.
- **Comparison view.** HuggingFace lets you compare models side by side. A "compare sources" affordance would be useful for developers deciding between two similar sources (e.g., two clinical-document sources with different chunk sizes). Stage-2 feature.
- **Search across field content.** Should the grid search hit `description_short`, `domain_tags`, `intended_use`, recipe parameters, etc.? Probably yes for name and tags, probably no for long-form text (too much noise). Needs design.
- **Whether card completeness should factor into the publish gate.** Currently publishing requires an eval run, a healthy index, and a sample prompt. Adding a minimum card completeness threshold (e.g., all judgment-intensive fields populated) would enforce documentation quality. This is a governance decision, not a technical one.
- **Interaction between interpretation guardrails and the MCP layer.** Error-level guardrails could be surfaced automatically in retrieval responses, but the design of that surface (inline warning in the response? separate guardrails field on RetrievalResult?) is open.

## Cross-references

- [`ui.md`](ui.md) — the stage-2 visual mockup document (exists but may need refreshing after stage 1 is reviewed).
- [`catalog.md`](catalog.md) — the authoritative data model. Every field in this document should trace to a catalog field or a computed projection thereof.
- [`evaluation.md`](evaluation.md) — the source of the eval scores displayed on cards.
- [`integrations/mlflow.md`](integrations/mlflow.md) — where MLflow deep links come from.
- [`integrations/llamastack.md`](integrations/llamastack.md) — what the MCP config snippet expands into when LlamaStack is the consumer.
- [`integrations/kagenti.md`](integrations/kagenti.md) — namespace-based tenant scoping that affects which sources a user sees in the grid.
- [`query-rewriter.md`](query-rewriter.md) — the rewriter fields displayed in the Rewriter tab.
- [`auth.md`](auth.md) — identity and access fields that determine what an agent developer sees vs. an owner vs. an admin.

## Stage 2 expectations (not in this document)

When stage 2 (visual mockups) starts, it should:

- Use PatternFly components and Red Hat design tokens throughout. No custom CSS that duplicates PatternFly.
- Target RHOAI dashboard integration — the SPA should feel native when embedded in the RHOAI dashboard (same fonts, same density, same navigation conventions).
- Produce responsive layouts (desktop-first but functional on a wide range of screen sizes) even though the primary audience is desktop developers.
- Include real ASCII or image-based mockups for the catalog grid and the source detail page — one mockup per major view, covering the three audiences (developer, owner, admin) with their field-visibility differences.
- Reference this document by field name when describing what's in each part of the mockup. If stage 2 adds a visual element that isn't backed by a field here, it must either (a) update this document to add the field, or (b) remove the visual element. No mockup invents data.
- Produce a PatternFly component mapping: each field → the PatternFly component that renders it (Card, DataList, DescriptionList, Label, Badge, etc.).
- Be reviewable as a static artifact (Figma link, Storybook, or committed mockup images) before any code is written.

When stage 3 (actual SPA + BFF implementation) starts, it should follow the existing [`ui.md`](ui.md) design for the peer component structure, with this document and stage-2 mockups as the authoritative field and layout references.
