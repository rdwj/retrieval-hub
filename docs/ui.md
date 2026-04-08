# Admin UI (`retrieval-hub-ui`)

The admin UI is the human face of retrieval-hub. Agents go through MCP; humans go through the UI. Three personas use it, in roughly this order of weight:

- **Source owners** are the heaviest users. They create sources, configure recipes, author and test rewrite prompts, run evals, publish, retire. The UI exists primarily for them.
- **Agent developers** are the second-heaviest. They browse the catalog, read recipes and evals, copy sample system prompts, and (sometimes) ad-hoc test a retrieval against a source before pointing their agent at it. They are not allowed to mutate anything.
- **Platform admins** are infrequent but high-stakes. They oversee the catalog as a whole, review audit trails, manage access policy, and step in when something is wrong.

The UI is **not the agent's interface**. Anything an agent needs at runtime goes through MCP. If the UI grows a feature that an agent would also want, that's a smell — the feature should be exposed through MCP and the UI should call it through the same path agents do.

## Where it sits in the platform pattern

`retrieval-hub-ui/` is a peer top-level component in the repo, with two subdirectories:

- **`frontend/`** — the SPA. PatternFly + React, to match Red Hat product look and feel and to make it feel native inside the OpenShift AI experience.
- **`backend/`** — a thin Backend-for-Frontend (BFF) in FastAPI. The BFF is the OAuth client for interactive human users (delegates to the IdP backend through `retrieval-hub-auth`), exchanges that for retrieval-hub JWTs, and proxies catalog operations into the core library on the user's behalf. The BFF is what holds the human session; the SPA never holds raw retrieval-hub tokens.

The BFF pattern is deliberate. Reasons:

- **The SPA never needs to be FIPS-aware.** All crypto is on the BFF side.
- **Human session management stays in one place.** Cookies, CSRF, idle timeout, all on the BFF.
- **The SPA talks to its own backend over a same-origin API.** No CORS dance, no token-in-localStorage anti-pattern.
- **Swapping the IdP backend** doesn't require touching the SPA.

Per the pattern doc, the UI's BFF imports the core library directly. It does **not** call retrieval-hub-mcp over the network. This is the one place that's allowed to bypass MCP, because the UI is part of the same deployable system and the cost of going through MCP for every catalog browse would be silly.

## Personas and their journeys

Three personas, three primary journeys. Everything in this doc rolls up to one of them.

### Source owner: "publish a new source"

This is the journey the UI is most optimized for. From "I have a corpus" to "agents can use it" should feel like a managed workflow, not a scavenger hunt.

```
Step 1: Create draft        →  /sources/new
Step 2: Choose family       →  document | clinical_document | code | tabular | external
Step 3: Configure recipe    →  parser, chunker, embedding model, backend
Step 4: Trigger ingestion   →  produces a Curated source with one physical index
Step 5: Run baseline eval   →  scores per LLM
Step 6: (Optional) Author rewrite prompt and run prompt test suite
Step 7: Author sample agent system prompts
Step 8: Publish             →  visible to agents, registered with AI Assets
```

The UI walks the owner through this in order, but it does *not* hide the underlying state. At any step the owner can see exactly what state the source is in (`Draft → Curated → Published`), what the most recent action was, what the current physical index health is, and what's blocking the next step. Publish is gated on (a) at least one healthy physical index, (b) at least one eval run with results, (c) at least one sample prompt — and the UI shows those gates as a checklist with green/red indicators rather than failing silently.

### Agent developer: "find a source and use it"

The agent developer doesn't write to the catalog. They browse, evaluate, and copy.

```
Step 1: Browse catalog              →  /sources
Step 2: Filter by family / domain   →  /sources?family=clinical_document
Step 3: Open source detail          →  /sources/va-clinical-guidelines
Step 4: Read recipe + eval scores
Step 5: Copy sample system prompt for their LLM family
Step 6: Test a query in the playground
Step 7: Configure their agent runtime to use retrieval-hub MCP + this source
```

Step 6 — the **playground** — is the affordance that turns "how do I know if this source is right for me" into a 30-second answer. It is a simple form: paste a query, optionally enable rewrite, see what comes back, see the rewrites if rewriting was used. Behind the scenes it makes the same MCP calls an agent would make.

### Platform admin: "audit a source's lineage and access"

The admin journey is reactive — driven by an incident, a compliance check, or an access review.

```
Step 1: Find the source                           →  /sources/<id>
Step 2: Review lineage tab                         →  origin, ingestion runs, refresh history
Step 3: Review access tab                          →  visibility, allowed groups, recent access
Step 4: Review audit trail                         →  state transitions, who-did-what-when
Step 5: (If needed) restrict, retire, or reassign
```

The audit trail is its own first-class view, not buried in a sidebar. It is read-only from the UI; mutation goes through specific actions with their own confirmation flows.

## The catalog grid (browse view)

The default landing view, modeled on the OpenShift AI model catalog. Cards in a grid, faceted filters on the left, search at the top.

```
+-----------------------------------------------------------------------------+
|  retrieval-hub                                                  [user] [?] |
+-----------------------------------------------------------------------------+
|  [Sources]  Prompts  Evals  Audit                          + New Source   |
+--------------+--------------------------------------------------------------+
| Family       |  Search: [_______________________]  Sort: [Updated v]      |
|  [x] document|                                                              |
|  [ ] clinical|  +----------------------+  +----------------------+         |
|  [ ] code    |  | Red Hat Product Docs |  | VA Clinical Practice  |         |
|  [ ] tabular |  | document             |  | clinical_document     |         |
|              |  | published            |  | published             |         |
| Status       |  |                      |  |                       |         |
|  [x] published|  | nomic-embed-text     |  | nomic-embed-text      |         |
|  [ ] curated |  | 512 tok / 64 ovl     |  | 512 tok / 64 ovl      |         |
|  [ ] draft   |  | pgvector             |  | pgvector              |         |
|  [ ] retired |  |                      |  |                       |         |
|              |  | granite-3 R@5: 0.81  |  | granite-3 R@5: 0.74   |         |
| Owner        |  | gpt-4o    R@5: 0.86  |  | gpt-4o    R@5: 0.79   |         |
|  platform-... |  |                      |  |                       |         |
|  clinical-...|  |     [rewrite avail]  |  |  [rewrite avail]      |         |
|              |  | Refreshed 2h ago     |  | Refreshed 1d ago      |         |
| Has rewrite  |  +----------------------+  +----------------------+         |
|  [ ] yes     |                                                              |
|              |  +----------------------+  +----------------------+         |
|              |  | Wikipedia / AI       |  | redhat-ai-americas    |         |
|              |  | document             |  | code                  |         |
|              |  | published            |  | curated               |         |
|              |  | ...                  |  | ...                   |         |
|              |  +----------------------+  +----------------------+         |
+--------------+--------------------------------------------------------------+
```

A few things this view enforces:

- **The four headline recipe facts** (embedding model, chunk/overlap, backend) are on every card. No drilling required to compare recipes at a glance.
- **The eval scores are on the card** for the most-cared-about LLMs (configurable per cluster via a "headline LLMs" admin setting). One row per LLM.
- **The "rewrite available" badge** is prominent because it's the differentiating capability and we want agent devs to know which sources have it without opening the detail view.
- **Refresh recency** is on the card because for a Wikipedia-style source, "fresh enough to use" is part of the buying decision.
- **Retired sources are filterable in but off by default.** Lineage-driven views can still find them.

## The source detail view

One click into a source. This is where the bulk of the design pressure lives, because it has to serve the source owner (full edit + control), the agent developer (read + copy + test), and the platform admin (lineage + audit) without becoming a wall of tabs.

```
+-----------------------------------------------------------------------------+
|  Sources / VA Clinical Practice Guidelines                                 |
|  clinical_document  ·  published  ·  owned by clinical-informatics         |
+-----------------------------------------------------------------------------+
| [Overview] [Recipe] [Rewrite] [Evals] [Sample Prompts] [Lineage] [Access]  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Description                                                                |
|  -----------                                                                |
|  Public VA/DoD clinical practice guidelines, structure-preserving          |
|  parsing, embedded for clinical-vocabulary semantic retrieval.              |
|                                                                             |
|  At a glance                                                                |
|  ------------                                                               |
|    Embedding model:      nomic-embed-text-v1.5 (768d)                       |
|    Chunking:             semantic, 512 tok / 64 overlap                     |
|    Backend:              pgvector  (idx_va_cpg_v2)                          |
|    Documents:            18,402                                             |
|    Last refresh:         2026-04-05  (cadence: weekly)                      |
|    Rewrite:              ENABLED  (prompt: va-clinical-rewriter v4)         |
|                                                                             |
|  Headline evals                                                             |
|  --------------                                                             |
|    granite-3-8b-instruct   R@5: 0.74    MRR: 0.68    (rewrite +0.27 R@5)    |
|    llama-3.3-70b-instruct  R@5: 0.78    MRR: 0.71    (rewrite +0.22 R@5)    |
|    gpt-4o                  R@5: 0.79    MRR: 0.74    (rewrite +0.18 R@5)    |
|                                                                             |
|  [ Test in Playground ]    [ Copy MCP config ]    [ Open AI Assets entry ] |
|                                                                             |
+-----------------------------------------------------------------------------+
```

A few notes:

- **The "rewrite +X.XX" delta on eval scores is the headline finding** — it's the proof, on the card, that the rewriter is earning its keep on this source. If the rewrite delta is small or negative, it shows up just as honestly.
- **"Copy MCP config"** produces the snippet an agent developer pastes into their agent runtime to point at retrieval-hub for this specific source. We minimize the steps between "I want to use this" and "my agent is using it."
- **The tabs across the top** are not deep navigation; each one is a panel within this same page. The browser's back button never lands you on a stale view.

The **Recipe** tab shows the full recipe with version history and a diff view between versions. The **Rewrite** tab shows the rewrite prompt template, its test cases, the results of the most recent test run, and (for owners) an editor. The **Evals** tab shows the full eval result history, all LLMs, all suites. The **Lineage** tab shows origin, refresh history, ingestion run log. The **Access** tab shows visibility, allowed groups, and recent access decisions.

## The rewrite prompt editor

This is the screen the rewriter differentiator lives or dies on. It needs to make authoring and testing a rewrite prompt feel **fast** — paste a query, see what comes back, iterate.

```
+-----------------------------------------------------------------------------+
|  Sources / VA Clinical Practice Guidelines / Rewrite                        |
|  prompt: va-clinical-rewriter   v4 (current)   v3 v2 v1                    |
+--------------------------------------------+--------------------------------+
| TEMPLATE                                    | TEST                           |
|  +----------------------------------------+ |  Raw query:                    |
|  | You are a clinical query reformulator  | |  +--------------------------+  |
|  | for the VA Clinical Practice Guideline | |  | what should I do for     |  |
|  | retrieval surface. You will receive    | |  | someone with high blood  |  |
|  | a user's question in lay language...   | |  | sugar after a meal       |  |
|  |                                        | |  +--------------------------+  |
|  | Vocabulary notes:                      | |  Context: (none)               |
|  |   - "high blood sugar" → ...           | |  LLM:    granite-3-8b ▼       |
|  |   - "blood pressure" → ...             | |                                |
|  |                                        | |  [ Run Test ]                  |
|  | Each rewrite must include an intent    | |                                |
|  | annotation and rationale.              | |  RESULT  (824 ms)              |
|  |                                        | |  +--------------------------+  |
|  | USER QUESTION:                         | |  | 1. VA/DoD clinical pra...|  |
|  | {raw_query}                            | |  |    intent: guideline_ref |  |
|  |                                        | |  |    rationale: ...        |  |
|  | CONTEXT (may be empty):                | |  | 2. type 2 diabetes me... |  |
|  | {context}                              | |  | 3. insulin therapy po... |  |
|  +----------------------------------------+ |  +--------------------------+  |
|  Constraints:                               |                                |
|    max_rewrites: [5]                        |  TEST SUITE                    |
|    output schema: rewrite_v1                |    27 cases · last run 4h ago  |
|                                             |    25 / 27 pass                |
|  [ Save as new version ]                    |    [ Run suite ]   [ Diff vs v3 ]
+--------------------------------------------+--------------------------------+
```

The **diff vs v3** affordance is critical. Editing a rewrite prompt is editing a piece of production behavior; the owner has to be able to see "which test cases improved, which regressed" before promoting v5. Promotion is a separate explicit action, not a side effect of saving.

The same screen, in read-only mode, is what an agent developer sees when they click into the Rewrite tab on a source they don't own. They can run the test affordance (which calls the MCP rewrite tool), but they can't edit the template or save versions.

## The playground

The playground is a single-purpose form that exists on every source detail page (and as a top-level `/playground` view). It is the "is this source right for me" answer.

```
+-----------------------------------------------------------------------------+
|  Playground / VA Clinical Practice Guidelines                              |
+-----------------------------------------------------------------------------+
|  Query:                                                                     |
|  +-----------------------------------------------------------------------+  |
|  | what should I do for someone with high blood sugar after a meal       |  |
|  +-----------------------------------------------------------------------+  |
|                                                                             |
|  [x] Use rewrite      Top K: [10]      LLM for rerank: (none) ▼            |
|                                                                             |
|  [ Retrieve ]                                                               |
|                                                                             |
|  REWRITES USED                                                              |
|    1. VA/DoD clinical practice guideline postprandial hyperglycemia ...    |
|    2. type 2 diabetes mellitus postprandial glucose treatment ...           |
|    3. insulin therapy postprandial glucose elevation                        |
|                                                                             |
|  RESULTS  (deduplicated across rewrites, 12 hits)                           |
|  +-----------------------------------------------------------------------+  |
|  | 1.  VA/DoD CPG: Management of Type 2 Diabetes Mellitus (2023)         |  |
|  |     Section 4.2 Postprandial Glucose Targets                          |  |
|  |     "Postprandial glucose levels should be targeted at..."            |  |
|  |     [physical_index: idx_va_cpg_v2 · recipe v2 · score 0.91]          |  |
|  +-----------------------------------------------------------------------+  |
|  | 2.  ...                                                               |  |
|  +-----------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------+
```

Every result item shows the **physical index id and recipe version** it came from, because that's the lineage handle from the catalog model and the playground is a great place to make it visible. If the index is unhealthy or the recipe version is stale, the playground shows a banner.

## What the BFF actually does

The BFF is intentionally thin. Its job is:

1. Handle the human OAuth flow: redirect the browser to the IdP, receive the callback, establish a session cookie, exchange for a retrieval-hub JWT.
2. Hold the JWT in a server-side session keyed by the cookie. The SPA never sees the JWT.
3. Expose a small JSON API mirroring the catalog operations the SPA needs (`GET /api/sources`, `GET /api/sources/:id`, `POST /api/sources`, etc.). Each endpoint validates the session, loads the JWT from the session, and calls into the core library with the resolved identity.
4. Proxy the playground retrieval and rewrite calls through the core library (not through MCP). Same code path, same access checks.
5. Implement CSRF protection on all mutating endpoints.
6. Handle session lifetime: idle timeout, absolute timeout, explicit logout.

The BFF does **not** implement business logic. Every domain operation is a call into the core library. If the BFF starts to grow a "service layer," that logic belongs in the core library and the BFF should call it.

## What's Decided

- **`retrieval-hub-ui/` is one peer component with `frontend/` and `backend/` subdirs.** PatternFly + React on the front, FastAPI BFF on the back.
- **The BFF imports the core library directly, not over MCP.** It is allowed to because it is part of the same deployable.
- **Three personas: source owner, agent developer, platform admin.** Source owner is the heaviest user.
- **Catalog grid puts headline recipe + headline eval + rewrite badge + refresh recency on every card.**
- **Source detail uses tabs within one page** (Overview, Recipe, Rewrite, Evals, Sample Prompts, Lineage, Access). Not nested deep navigation.
- **The rewrite prompt editor has a diff-vs-previous-version view** and promotion is a separate explicit action from saving.
- **The playground exists on every source page** and shows physical index + recipe version on every result item.
- **The SPA never holds retrieval-hub JWTs.** Sessions are server-side on the BFF.
- **Every mutating BFF endpoint is CSRF-protected.**

## What's Open

- **Whether the SPA framework is React or Vue or something else.** PatternFly's React story is more mature, and Red Hat product UIs are React, so React is the working assumption — but it's not yet committed.
- **The "headline LLMs" admin setting** that controls which LLMs' eval scores show on the card surface. The set will differ by cluster and by customer; round 1 says "make it admin-configurable, default to the three most-recently-evaluated LLMs."
- **Mobile / small-screen layouts.** Out of round 1. The UI is desktop-first because the personas are desktop personas.
- **Internationalization.** Out of round 1. PatternFly supports it; we'll want it eventually.
- **Whether the playground supports cross-source queries** (query against multiple sources at once). Probably yes once cross-source MCP tools exist; round 1 is single-source.
- **Whether agent developers can save "test snippets"** they've tried in the playground for later reference. Tempting but probably scope creep for round 1.
- **The visual treatment of `clinical_document` vs `document`** in the catalog grid. Subtle badge? Different card border color? Defer to a real designer; the round-1 mockups treat them as a family-name string and stop there.
