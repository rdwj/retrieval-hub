# retrieval-hub UI — stage-2 mockup

This directory is a **stage-2 visual mockup** of the retrieval-hub catalog UI.
It is a single-page Vite + React + TypeScript app wired up with PatternFly 5
that renders against **local mock data**. There is no backend, no real auth,
no real retrieval, and no real clipboard-configured MCP server. The entire
point is to have something clickable so we can iterate on the layout and
interactions before writing the real thing.

This is throwaway-ish code. It will be replaced in stage 3 by the real SPA +
BFF under `retrieval-hub-ui/frontend/` and `retrieval-hub-ui/backend/`
following `docs/PLATFORM_COMPONENT_PATTERN.md`.

The authoritative field list and data dictionary is
[`docs/ui-card-data.md`](../../docs/ui-card-data.md) at the repo root. Every
visible piece of data on a card traces back to a field in that doc.

## Quick start

```bash
cd retrieval-hub-ui/frontend
npm install
npm run dev
```

Then open <http://localhost:5173/>.

Other scripts:

- `npm run build` — type-check with `tsc --noEmit` and produce a production
  build under `dist/`
- `npm run lint` — ESLint with `--max-warnings 0`
- `npm run preview` — serve the production build

## Personas and "View as..."

The mockup has four personas available from the "View as..." dropdown in the
header. There is no real authentication — switching personas just changes the
access-check logic locally. A page refresh resets to Platform Admin.

1. **Platform Admin** (default) — holds `admin.read`. Sees every source, has
   the Admin nav link, sees the full cluster admin dashboard.
2. **Source Owner (clinical-informatics)** — owns the clinical sources. Sees
   the catalog and sees the admin dashboard filtered to owned sources ("My
   sources (3)" indicator).
3. **Agent Developer (research-agents)** — identity groups include
   `research-agents`. Sees the catalog. Has query access to public sources
   and to sources where `research-agents` intersects `allowed_groups`.
4. **Agent Developer (no access)** — identity group is only `agents`. Sees
   the catalog but hits the access-required banner on restricted sources.

## Testing the access-required banner

1. Set the persona to **Agent Developer (no access)** via the header dropdown.
2. Open the catalog and click **Clinical Notes Staging** or **Internal
   Research Database**.
3. The detail page shows a warning banner at the top with your identity, your
   current groups, the required groups (with the missing ones highlighted),
   the owner contact, and a "Contact Owner" button that opens a `mailto:`
   link. Expanding the "Show email preview" section previews the email body.

## Stack

- **Vite 5.x** build tool + dev server
- **React 18** with TypeScript strict mode
- **PatternFly 5** (`@patternfly/react-core`, `@patternfly/react-icons`,
  `@patternfly/react-table`). PatternFly 6 is early preview and is **not**
  used.
- **React Router 6** for routing
- No backend, no data fetching library, no state management library beyond
  React Context.

## Layout

```
src/
├── main.tsx                    # React root + PatternFly CSS + router
├── App.tsx                     # Page shell + routes
├── types/source.ts             # TypeScript shapes for Source, Persona, etc.
├── data/mockSources.ts         # 8 mock sources + 4 personas + audit feed
├── context/PersonaContext.tsx  # "View as..." persona state
├── components/
│   ├── Header.tsx              # Masthead + nav + persona dropdown + theme toggle
│   ├── SourceCard.tsx          # Catalog grid card
│   ├── BestScoreDisplay.tsx    # Composite best-score + popover drill-down
│   ├── CapabilityIcons.tsx     # Rewriter / write / retrieval pattern icons
│   ├── FamilyIcon.tsx          # family → icon mapping
│   ├── DomainTags.tsx          # LabelGroup wrapper
│   ├── ActionBar.tsx           # 4-button action bar on source detail
│   └── AccessRequiredBanner.tsx
├── pages/
│   ├── CatalogPage.tsx
│   ├── SourceDetailPage.tsx    # 7-tab detail view
│   ├── AdminPage.tsx           # 3-panel admin dashboard
│   ├── PlaygroundPage.tsx
│   └── NotFoundPage.tsx
└── utils/
    ├── formatters.ts           # relative time, numbers, score formatting
    └── accessCheck.ts          # canAccess / canWrite / bestScore helpers
```

## Mock data

`src/data/mockSources.ts` contains 8 sources covering all round-1 source
families, including one `draft` source that is hidden from the default catalog
grid but visible in admin views:

1. Red Hat Product Documentation (`document`, public, rewriter light)
2. VA Clinical Practice Guidelines (`clinical_document`, public, hero
   rewriter example with 53 vocabulary mappings and a dramatic rewrite lift)
3. Wikipedia AI Subset (`document`, public, rewriter disabled)
4. Red Hat AI Americas Code (`code`, public, degraded index health flag)
5. Clinical Notes Staging (`clinical_document`, **restricted**,
   **agent-writable** to `clinical-writers`)
6. Internal Research Database (`tabular`, restricted, text-to-SQL retrieval)
7. OpenShift Knowledge Graph (`graph`, public, graph-traversal retrieval)
8. Clinical Trials Index (`clinical_document`, **draft**, no physical index —
   admin-only visibility)

## Dark mode

Click the sun/moon icon in the header to toggle. Uses PatternFly 5's built-in
`pf-v5-theme-dark` class on the `<html>` element. Not persisted — a refresh
resets to light.

## Known limitations

- **No backend.** Everything is in-memory mock data loaded from
  `src/data/mockSources.ts`.
- **No real auth.** Persona switching is purely client-side.
- **No real search.** Catalog search/filter is a local substring match over
  the mock records.
- **Playground is UI-only.** Clicking "Run query" shows fake results after a
  500ms artificial delay. No real retrieval is happening.
- **Clipboard snippets are hardcoded.** "Copy MCP Config" always produces the
  same template URL (`mcp.retrieval-hub.example.com`) regardless of cluster
  config.
- **"View in Grafana" / "View in MLflow" / "View in Keycloak" buttons are
  stubbed** to `alert(...)`. They do not open real dashboards.
- **No tests.** This is a visual prototype; the quality bar is `npm run lint`
  and `npm run build` passing.
- **No internationalization.** English hardcoded strings.
- **No persistence.** Refreshing the page resets persona, dark-mode, and any
  form state.
- **Rewriter "Test rewrite" is a simplistic substitution.** It does not
  actually call an LLM or the shared rewriter template.

## What's authoritative vs. what's mocked

Authoritative references:

- **Field list & data dictionary**: `docs/ui-card-data.md`
- **Data model**: `docs/catalog.md`
- **Peer component structure**: `docs/PLATFORM_COMPONENT_PATTERN.md`

Mocked in this directory:

- All source data
- Persona identities & access checks
- MCP config snippet template
- Rewriter test affordance
- Playground results
- Ingestion run history
- Audit/recent-changes feed
- MLflow / Grafana / Keycloak deep links
