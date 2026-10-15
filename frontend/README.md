# Race UP TDM — frontend

A lightweight engineering dashboard for the Test Data Manager API. It is built with React 19,
TypeScript (strict), Vite, Tailwind CSS v4 and React Router. It reads and writes only through
the backend's `/api/v1` endpoints.

## Prerequisites

- Node.js 24 and npm 11. These were used to build and test the frontend.
- The backend running on `http://127.0.0.1:8000`, migrated and preferably seeded. From `backend/`:

  ```bash
  alembic upgrade head
  python -m scripts.seed
  uvicorn app.main:create_app --factory --reload --port 8000
  ```

## Commands

Run these from `frontend/`:

| Command | Purpose |
|---|---|
| `npm ci` | Install the exact versions from `package-lock.json` |
| `npm run dev` | Development server on http://localhost:5173 |
| `npm run typecheck` | TypeScript check (`tsc --noEmit`, strict) |
| `npm test` | Vitest and Testing Library (jsdom; `fetch` is mocked, so no backend is needed) |
| `npm run build` | Type check, then production build into `dist/` |

## Backend connection

- **Development proxy.** The browser calls relative URLs under `/api/v1`. The Vite dev server
  proxies `/api` to the backend, so the backend needs no CORS configuration.
- **Proxy target.** Defaults to `http://127.0.0.1:8000`. Override it with
  `TDM_BACKEND_URL=http://host:port npm run dev`.
- **API base URL.** The client uses `/api/v1` by default. Set `VITE_API_BASE_URL` at build time
  to point it elsewhere.
- **Production.** Serving `dist/` with a reverse proxy for `/api` is part of the deployment
  setup and is not configured here.

## Routes

| Route | Shows |
|---|---|
| `/` | Dashboard: recent tests and runs, plan versus actual for the latest test, the fastest eligible laps on the latest run's layout, and season distance. Each card states its exact scope. |
| `/runs` | Historical run search over `GET /runs`, with backend filters combined with AND: season, vehicle, driver, layout, activity, tyre compound, planned or unexpected, date range and asphalt range. Location and ambient range are under *Advanced*. Filters are synced to the URL, validated before sending, and the backend paginates (25 per page). |
| `/tests/:id` | Test context, plan versus actual (executed, not executed, cancelled and replaced plans, repeated attempts, deviations), unexpected runs and objectives |
| `/runs/:id` | Run context, conditions, fastest lap, mileage, the plan comparison, laps (every category marked), tyres by corner FL, FR, RL, RR with pre- and post-run measurements, observed alignment, objectives and indexed files. Sections load in parallel and fail independently. |
| `/setups/:id` | Intended setup (read-only and append-only), vehicle and corner values, missing corners, and the diff against the source snapshot |
| `/tests/new` | Create a test, optionally with its first planned run. The form validates on the client, and the backend's field errors are shown on the matching fields. |

## Conventions

- **Units are never converted.** Times are stored in milliseconds and shown as `m:ss.mmm`,
  with the exact milliseconds in a tooltip. Distances are decimal strings from the API, shown
  in metres with grouped thousands. Temperatures and pressures keep their API units.
- **Errors** use the backend's `error.code`, `message` and `details`. Network failures are
  reported separately from backend errors. Raw internals are never rendered.
- **Status is always written out.** Badges carry text, and colour only reinforces it.
  Interactive elements have visible focus outlines. Tables have captions and scroll
  horizontally on narrow screens.

## Not implemented (deferred)

The frontend has no editing, correction or deletion flows. The backend does not offer them
either: its history is append-only. The following are also not implemented:

- logging runs, laps, conditions, tyres or measurements from the UI (these use the API or the
  CSV importer);
- CSV import;
- file upload;
- authentication;
- charts;
- real-time telemetry.
