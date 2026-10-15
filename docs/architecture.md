# Architecture

Status: **Phase 3**. The backend API foundation is implemented. Later phases extend this document.
The schema is documented in [data-model.md](data-model.md).

## Backend layout

```
backend/app/
  main.py          create_app() factory: engine, session factory, error handlers, /api/v1 router
  config.py        DATABASE_URL (default backend/var/tdm.sqlite3)
  database.py      engine factory (PRAGMA foreign_keys=ON per connection), session factory
  dependencies.py  per-request session/transaction dependency, path-id type
  exceptions.py    domain errors: NotFoundError, ConflictError, DomainValidationError
  errors.py        exception handlers and IntegrityError translation
  models/          SQLAlchemy ORM (Phase 2)
  schemas/         Pydantic request/response models, separate from the ORM
  services/        business rules and queries; no HTTP, no commits
  routers/         thin HTTP layer: parse, call one service function, convert to schema
```

Dependencies point in one direction: `routers → services → models`, with `schemas` shared by
routers and services. Services receive validated Pydantic input and return ORM objects.
Routers convert those objects to response schemas while the session is still open.

Run the API from `backend/`: `uvicorn app.main:create_app --factory --reload`. OpenAPI is
served at `/docs` and `/openapi.json`. The database must be migrated first with
`alembic upgrade head`; the app never calls `create_all`.

## Transactions

- There is **one session and one transaction per request**. `get_session` wraps
  `session_factory.begin()`: the transaction commits when the path operation returns and rolls
  back on any exception.
- Services `add`, `flush` and query, but **never commit**. A multi-entity command is therefore
  atomic. For example, `POST /tests` with an inline `planned_runs` list is all-or-nothing.
  This is tested.
- The dependency is declared with `Depends(get_session, scope="function")`. FastAPI's
  default scope (`"request"`) runs dependency exit code *after* the response has been sent,
  so a failing commit would still reach the client as a 2xx. With `scope="function"`, the
  commit finishes before the response is sent. A test injects a commit failure and checks that
  the client receives a 500 and that nothing is persisted. I also confirmed that this test fails
  when the scope is removed.
- Services `flush` after each write, so constraint violations surface inside the request and
  are translated like any other error.

## Error responses

Every error has the same shape:

```json
{"error": {"code": "run_number_taken", "message": "…", "details": [{"field": "run_number", "issue": "…"}]}}
```

| Status | When | Example codes |
|---|---|---|
| 404 | The resource in the **path** does not exist | `test_not_found`, `run_not_found`, `not_found` (unknown route) |
| 409 | Uniqueness conflict | `season_name_taken`, `planned_run_sequence_taken`, `run_number_taken`, `integrity_conflict` (fallback) |
| 422 | Request validation; domain rule; a **body** field references a missing row | `request_validation_failed`, `referenced_resource_not_found`, `track_layout_not_at_test_location`, `planned_run_not_in_test`, `setup_snapshot_vehicle_mismatch`, `constraint_violation` |
| 405 | Method not allowed | `method_not_allowed` |
| 500 | Unexpected error, with a generic message only | `internal_error` |

A missing *referenced* row, such as `season_id: 999` in a request body, is a 422 rather than
a 404, because the addressed resource (the collection) exists and it is the request content
that is invalid.

**IntegrityError translation** (`app/errors.py`):

- The database constraints remain the final integrity boundary. Translation looks up the
  violated constraint *name* in one registry (`KNOWN_CONSTRAINTS`).
- SQLite reports CHECK failures by constraint name. It reports UNIQUE and PRIMARY KEY failures
  only as `table.column` lists; these are mapped back to constraint names through the ORM
  metadata. FOREIGN KEY failures carry **no name at all**.
- Services therefore pre-check every referenced row, so the client gets a field-level message.
  The FK constraint still backs that check up, with a generic `referenced_resource_not_found`.
- Unregistered CHECK and NOT NULL failures map to a generic 422 `constraint_violation`. Any
  other failure maps to a generic 409 `integrity_conflict`.
- On PostgreSQL the same registry would be keyed by `diag.constraint_name`.
- Responses never contain SQL, table names, constraint names, paths or stack traces. The raw
  database message is logged server-side only. Tests assert this.

Uniqueness is **not** pre-checked in services. The constraint and its translation are the
single, race-free mechanism.

## Validation conventions

- Request models use `extra="forbid"`, so unknown fields and unknown query parameters are
  rejected rather than silently ignored. A mistyped filter in a historical query must not
  return unfiltered data.
- Strings are trimmed and must be non-empty, with the same maximum lengths as the columns.
  Decimals declare `max_digits` and `decimal_places` matching their `NUMERIC(p, s)` column.
  Ids and counts are bounded to 32-bit positive integers.
- Timestamps must carry an offset; naive values are rejected with a 422. Values are normalised
  to UTC on input, and responses use `Z`.
- Decimals are serialised as JSON strings (for example `"1000.000"`) to preserve precision.
- Pydantic checks row-local rules before persistence: date order, time order, and unique
  sequence numbers in an inline plan. Cross-row rules are checked in services.

## Cross-row rules (service layer)

| Rule | Error |
|---|---|
| A run's layout, and a planned run's expected layout, is at the test's track location | 422 `track_layout_not_at_test_location` |
| A run's `planned_run_id` belongs to the same test | 422 `planned_run_not_in_test` |
| A referenced setup snapshot belongs to the test's vehicle | 422 `setup_snapshot_vehicle_mismatch` |
| Season, vehicle, track location, driver, layout, planned run and snapshot exist | 422 `referenced_resource_not_found` |

A planned run may have any number of actual runs (attempts and retries). An unexpected run
has `planned_run_id = null`.

## Pagination and ordering

Offset pagination is used on every collection: `limit` defaults to 50 and must be between
1 and 100, and `offset` must be 0 or more. Invalid values are a 422. Responses contain
`items`, `limit`, `offset`, `total` (an exact COUNT, acceptable at the volume of a test-data
system) and `order_by`. Every ordering ends with the primary key, so it is deterministic.

| Collection | Order |
|---|---|
| seasons | `starts_on asc nulls last`, `id asc` |
| vehicles, drivers | `code asc`, `id asc` |
| track locations, track layouts | `name asc`, `id asc` |
| tests | `test_date desc`, `id desc` |
| planned runs of a test | `sequence_number asc`, `id asc` |
| runs of a test | `run_number asc`, `id asc` |

Offset pagination becomes slower at deep offsets and can skip or repeat rows when data
changes between page requests. Cursor pagination over the same orderings is the planned upgrade.

**Loading:** list endpoints return compact summaries containing only columns of the listed
table, so they make no relationship loads (no N+1). Detail endpoints load exactly what they
return: a test loads its season, vehicle and location with `joinedload` and its plan with
`selectinload`; a run loads its driver and layout with `joinedload`.

## Update and delete policy (Phase 3)

The API is **create and read only**. No endpoint deletes or updates tests, planned runs or
runs, so historical records cannot be destroyed through the API. Planned-run status changes
(cancel and replace) will be explicit commands in Phase 4. A planned run is always created as
`PLANNED`. Corrections to reference data, such as display names, are deferred.

## Implemented endpoints (`/api/v1`)

| Resource | Endpoints |
|---|---|
| Seasons | `POST /seasons`, `GET /seasons`, `GET /seasons/{id}` |
| Vehicles | `POST /vehicles`, `GET /vehicles`, `GET /vehicles/{id}` |
| Drivers | `POST /drivers`, `GET /drivers`, `GET /drivers/{id}` |
| Track locations | `POST /track-locations`, `GET /track-locations`, `GET /track-locations/{id}` |
| Track layouts | `POST /track-layouts`, `GET /track-layouts?track_location_id=&activity_type=`, `GET /track-layouts/{id}` |
| Tests | `POST /tests` (optional inline `planned_runs`), `GET /tests?season_id=&vehicle_id=&track_location_id=&date_from=&date_to=&status=`, `GET /tests/{id}` |
| Planned runs | `POST /tests/{id}/planned-runs`, `GET /tests/{id}/planned-runs`, `GET /planned-runs/{id}` |
| Actual runs | `POST /tests/{id}/runs`, `GET /tests/{id}/runs`, `GET /runs/{id}` |

The following do not exist yet and are not shown in OpenAPI:

- setup snapshot endpoints
- planned-run cancel and replace commands
- run conditions
- laps
- mileage and analytics
