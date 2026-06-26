# Insight Engine — Web UI

React front-end for the Insight Engine enrichment pipeline. Implements the
multi-file flow: **Upload → Confirm → Processing → Batch Results → Result
Explorer → History**.

Built **mock-first**: every screen talks to a typed `ApiClient` seam. Today a
in-memory `mockApi` backs it (with a simulated job runner + fake SSE progress);
when the FastAPI backend exists, drop in an `HttpApiClient` with the same
interface and **no screen changes are needed**.

## Stack

- Vite + React 18 + TypeScript
- Tailwind CSS
- React Router (routing)
- TanStack Query (data fetching / caching)

## Run

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Other scripts: `npm run build`, `npm run preview`, `npm run typecheck`.

## How the demo flows

1. **Upload** — drag or browse files (`.xml/.pdf/.doc/.docx`). XML auto-detects
   domain (KA/KCL from filename); PDF/DOC are flagged "Needs domain".
   *Tip: name a mock file with "KCL" to see it routed to Competition Law.*
2. **Confirm** — assign KA/KCL to each PDF/DOC; XML rows are locked.
3. **Processing** — watch per-file phases advance live (fake SSE), overall bar + ETA.
4. **Batch Results** — summary stats + table; click a row to open a document.
5. **Result** — Explorer (L1→L4 tree with anchored/expanded provenance badges),
   Entities, Before/After, Overview tabs + a file pager across the batch.
6. **History** — past taxonomies grouped by date, searchable/filterable.

## Project structure

```
src/
  lib/
    types.ts        # domain types — mirror API_REQUIREMENTS.md
    api.ts          # ApiClient interface + React context/useApi()
    mockApi.ts      # in-memory implementation: job runner + fake SSE
    hooks.ts        # TanStack Query hooks + useBatchEvents (live progress)
    format.ts       # bytes/date/percent helpers
    queryClient.ts
  mocks/seed.ts     # canned KA/KCL taxonomy results + seeded history
  components/        # AppShell, Stepper, ui primitives (Button, Chip, badges…)
  screens/           # the 6 screens
  App.tsx / main.tsx
```

## Swapping in the real API

1. Implement `ApiClient` (see `src/lib/api.ts`) as `HttpApiClient` using `fetch`
   against the FastAPI endpoints in `../API_REQUIREMENTS.md`.
2. Replace `subscribeBatch` with a real `EventSource` on
   `GET /api/batches/{id}/events`.
3. In `src/main.tsx`, swap `mockApi` for `new HttpApiClient(baseUrl)`.

That's the only change — screens and hooks are backend-agnostic.

## Notes / mock limitations

- State is in-memory: a hard refresh on the Processing/Results screen loses the
  in-flight batch (the History seed data persists per session).
- The taxonomy tree, entities, and before/after are canned per domain
  (KA = arbitration / DJP v. DJO; KCL = competition / Merger Control) to mirror
  the Figma content.
