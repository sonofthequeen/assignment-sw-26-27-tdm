# Architecture

Status: **final**. The backend is complete for the assignment. Packaging (Docker, Compose,
CI) and run commands are in the [README](../README.md); the reasoning is in
[ToughtProcess.md](ToughtProcess.md).
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
                   (reference, tracks, testing, planning, setup, conditions, laps,
                    mileage, lookup, pagination)
  queries/         read-only compositions: historical run search, fastest-lap ranking,
                   test plan-vs-actual summary
  policies.py      validation policy: temperature ranges, implied-speed caps, batch size
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
| A run's planned run is not CANCELLED or REPLACED | 409 `planned_run_state_conflict` |
| A replacement plan is valid in the original plan's test (layout, setup, driver) | 422, as above, on `replacement.*` |
| Season, vehicle, track location, driver, layout, planned run and snapshot exist | 422 `referenced_resource_not_found` |

A planned run may have any number of actual runs (attempts and retries). An unexpected run
has `planned_run_id = null`. Runs on a COMPLETED plan are still allowed, as further attempts.

## Planned-run lifecycle (`app/services/planning.py`)

There is no generic workflow engine. Each transition is a named command with its own rule:

| Command | Allowed from | Result | Requires |
|---|---|---|---|
| `POST /planned-runs/{id}/cancel` | PLANNED, MODIFIED | CANCELLED | non-blank `cancellation_reason` |
| `POST /planned-runs/{id}/replace` | PLANNED, MODIFIED | REPLACED, plus a new PLANNED plan in the same test | non-blank `replacement_reason`; `replacement.sequence_number` unused in the test |
| `POST /planned-runs/{id}/complete` | PLANNED, MODIFIED | COMPLETED | at least one recorded actual run |

- **Terminal states.** CANCELLED, REPLACED and COMPLETED are terminal. A command on a
  terminal plan is a 409 with `planned_run_already_cancelled`, `planned_run_already_replaced`
  or `planned_run_already_completed`, and `details[0].field = "status"`. Completing a plan
  that has no run is a 409 `planned_run_not_executed`.
- **Nothing is deleted or overwritten.** Cancel changes only `status` and
  `cancellation_reason`. Replace changes only the original's `status`,
  `replaced_by_planned_run_id` and `replacement_reason`; every planned value stays as it was.
  The replacement is a new row, and its `replaces` list links back to the original.
- **Replace is atomic.** It creates the new plan, flushes it (sequence-number uniqueness is
  checked here), then updates the original, all in the request transaction. A failure at any
  step, including the commit, leaves both plans as they were. This is tested.
- **MODIFIED is deferred.** No command sets it. There are two ways a plan can be "modified",
  and neither needs a stored status:
  - Before execution, a change to a plan is a *replacement*. Editing in place would destroy
    the original intent.
  - During execution, deviations are *derived* by comparing the run with the plan.

  MODIFIED stays in the schema and is accepted as a source state, for example for imported
  spreadsheet history.
- **Completion is explicit, not inferred.** The run model records no outcome, so the
  existence of a run does not prove that the plan was achieved. An engineer marks the plan
  complete.

## Planned versus actual (`GET /runs/{id}/plan-comparison`)

The endpoint returns one item per aspect, each with `expected`, `actual`, a `status` and an
optional `note`. Missing actual values are never invented; the `status` says why a
comparison is not possible.

| Status | Meaning |
|---|---|
| `MATCH` / `DIFFERENT` | Both values are known and were compared |
| `NO_PLAN` | Unexpected run; there is no plan to compare against |
| `NOT_PLANNED` | The plan set no expectation for this aspect |
| `ACTUAL_NOT_RECORDED` | An expectation exists, but no actual value is recorded |
| `NOT_YET_SUPPORTED` | The actual value is not modelled at all (energy) |
| `TARGET_MET` / `TARGET_MISSED` | Fastest eligible effective lap ≤ / > the target time |

How each aspect is compared:

- **Driver and track layout** are compared by id.
- **Setup snapshot.** Different snapshot ids are then compared by *value*. Identical
  engineering values count as `MATCH`, with a note. If the values differ, the note links to
  the snapshot diff.
- **Control map.** The actual value comes from the run's setup snapshot.
- **Energy limit.** `NOT_YET_SUPPORTED` when planned, because actual energy use is not modelled.
  Phase 4 returned `ACTUAL_NOT_RECORDED` here. Phase 5 changed it deliberately, because
  "not recorded" wrongly suggested that a value could exist.
- **Lap count.** The expected count is compared with **physically completed** laps. It is
  never inferred from lap numbering. The note gives both the recorded and the completed
  count, and the response carries `recorded_lap_count` and `physically_completed_lap_count`.
  A run with no lap records yet is `ACTUAL_NOT_RECORDED`, not "0 laps".
- **Target lap time.** The target is compared with the **fastest eligible** effective lap
  (penalty included), giving `TARGET_MET` or `TARGET_MISSED` and a signed delta in the note.
  Invalid, untimed, incomplete, IN_LAP, OUT_LAP and ABORTED laps are never used. With no
  eligible lap the status is `ACTUAL_NOT_RECORDED`. The response also gives
  `fastest_eligible_lap_id`.
- **Unexpected runs** report the actual lap values with status `NO_PLAN`.

## Setup snapshots (`app/services/setup.py`)

**Root snapshot** (`POST /setup-snapshots`):
- Takes the vehicle, an optional name, the vehicle-level values, and zero to four corner entries.
- A root cannot set `based_on_snapshot_id` or `change_reason`. Unknown fields are rejected.
- Values are bounded: power, RPM and spring rate must be positive; camber is limited to
  ±10° and toe to ±5° as application plausibility policy; decimals match the column precision.

**Derive** (`POST /setup-snapshots/{id}/derive`): records a change as a new snapshot on the
source's vehicle, with `based_on_snapshot_id` pointing to the source and a required
`change_reason`.
- A vehicle-level field that is omitted is copied from the source. A field that is present
  overrides it; an explicit `null` clears it.
- `corners` changes only the listed fields of the listed corners. A listed corner that the
  source lacks is added.
- `remove_corners` drops corners.
- `name` is a label and is not inherited.
- A derive that changes nothing is rejected with 422 `setup_derivation_without_changes`.
  This includes re-sending the same values.
- The new snapshot and all its corner rows are created in one transaction.

**Immutability:**
- There is no PATCH, PUT or DELETE route anywhere in the API (tested through OpenAPI and with
  405 responses).
- No service function updates a snapshot.
- The ORM `before_flush` guard rejects mutation of persisted snapshots and corner rows in any
  session with 409 `setup_snapshot_immutable`. Raw SQL is not guarded (no triggers).

**Diff** (`GET /setup-snapshots/{id}/diff[?against_snapshot_id=]`):
- The diff is computed from the two snapshots and never stored.
- The baseline is `against_snapshot_id` (`EXPLICIT`), otherwise the source snapshot
  (`BASED_ON`). A root with no explicit target returns an empty diff with baseline `NONE`.
- Results list vehicle-field changes (in field order), then corner-field changes (FL, FR,
  RL, RR, then field order), then `corners_added` and `corners_removed`.
- Metadata is not compared: `id`, `name`, `created_at`, `based_on_snapshot_id` and
  `change_reason`. Decimals are compared numerically, so `80` equals `80.00`.
- Comparing snapshots of different vehicles is rejected with 422, because parameters are
  only meaningful within one vehicle generation.

Comparing a run's setup with that vehicle's previous run builds on this diff. It belongs with
historical queries in Phase 6.

## Run conditions (`app/services/conditions.py`)

- **Create-once.** `POST /runs/{id}/conditions` returns 201. A second write is a 409
  `run_condition_already_exists`, enforced by a service pre-check and backed by the
  `pk_run_condition` primary key. Silently overwriting measured conditions would destroy
  history. Corrections are deferred to explicit correction records. `GET` returns 404
  `run_not_found` or `run_condition_not_found`.
- **Missing values.** Any value can be omitted and is then stored as NULL (unavailable),
  never guessed. A temperature requires `conditions_source` (MEASURED or ESTIMATED). Pydantic
  checks this, and so does the database.
- **Precision and ranges.** Decimals use one decimal place (`NUMERIC(4,1)`). Plausibility
  ranges are validation policy in `app/policies.py`, not database constraints: ambient
  −30.0 to 60.0 °C and asphalt −30.0 to 90.0 °C, inclusive. Out-of-range values are a 422
  `invalid_condition_value`.

## Laps (`app/services/laps.py`, `app/models/laps.py`)

### Ingestion

- **Endpoints.** `POST /runs/{id}/laps` takes one lap. `POST /runs/{id}/laps/bulk` takes a
  batch of 1 to 500 laps. The limit is in `app/policies.py`; an empty batch is 422
  `empty_lap_batch` and a larger one is 422 `lap_batch_too_large`. Laps are append-only:
  there is no PATCH, PUT or DELETE, and corrections are deferred.
- **Bulk is all or nothing.** The service checks, in order:
  1. lap numbers unique within the batch (422 `duplicate_lap_number_in_batch`, one detail per
     offending index);
  2. each lap's rules;
  3. collisions with existing laps (409 `lap_number_taken`, field `laps.{i}.lap_number`).

  It then inserts the batch in lap-number order in the request transaction. Any failure
  persists nothing: a validation error, a UNIQUE violation reached during the flush, or a
  failing commit. Each case is tested.
- **Input is never repaired.** Contradictory input is a 422 `invalid_lap_state`:
  - a timing-valid lap without `raw_time_ms`;
  - a timing-valid lap with an invalidation reason;
  - a timing-invalid lap without a reason.

  `timing_valid` and `physically_completed` are strict booleans and are required.

### Implied-speed plausibility

A lap is rejected with 422 `impossible_lap_time` when
`verified_length_m / (raw_time_ms / 1000)` exceeds the per-activity cap:

| Activity | Cap |
|---|---|
| SKIDPAD | 25 m/s |
| ACCELERATION | 45 m/s |
| AUTOCROSS | 40 m/s |
| ENDURANCE | 40 m/s |
| GENERIC_TESTING | 50 m/s |

- The caps are validation policy, set well above any real Formula Student average speed.
  They are not physical constants.
- The check uses raw time (a penalty is not traversal time) and exact Decimal arithmetic.
- It applies only to timed, physically completed laps. An incomplete lap did not cover the
  verified length, so its speed is unknown.
- There is no minimum time and no global maximum: slow laps are real data.

### Derived values (never stored)

These are SQLAlchemy `hybrid_property`s on `Lap`. Each is defined once and evaluates the
same way on instances and in SQL; a test checks this for every combination of the four
inputs.

| Value | Definition |
|---|---|
| `effective_time_ms` | `raw_time_ms + penalty_duration_ms`; NULL for an untimed lap, both in Python and in SQL (`NULL + n`). Integers only. |
| `fastest_lap_eligible` | `timing_valid AND raw_time_ms IS NOT NULL AND physically_completed AND classification = FLYING`. A penalised lap stays eligible. IN_LAP, OUT_LAP and ABORTED laps, untimed laps, timing-invalid laps and incomplete laps are excluded. |
| `counts_toward_mileage` | `physically_completed`, regardless of timing validity, penalty or classification |

All three are returned on every lap, so the ranking is transparent.

### Fastest lap

`GET /runs/{id}/fastest-lap` returns 200 with `lap: null` when nothing is eligible. The run
exists; it simply has no eligible lap. The response also gives `recorded_lap_count`,
`eligible_lap_count` and the policy text. Tie-breaking is fixed: `effective_time_ms`, then
`raw_time_ms`, then `lap_number`, then `id`, all ascending (`FASTEST_LAP_ORDER`).

## Mileage (`app/services/mileage.py`)

`GET /{runs|tests|seasons|vehicles|drivers}/{id}/mileage` returns:
- `counted_lap_count`;
- `contributing_run_count`;
- `distance_m`, exact to the millimetre and serialised as a decimal string;
- `distance_km`;
- the policy text.

A missing resource is a 404 (`season_not_found` and so on). A resource with no laps returns zero.

**Policy:**
- Each physically completed lap counts **one full verified layout length**. This includes
  timing-invalid, penalised, untimed, IN_LAP and OUT_LAP laps, and ABORTED records that are
  explicitly marked as having completed the loop.
- Incomplete laps count zero. Partial distance is not modelled, so it is never invented.
- Penalties never change distance.
- Only actual runs' laps are counted. Planned runs contribute nothing; unexpected runs and
  repeated attempts count like any run.

`distance_m` is a decimal, not integer metres, because verified layout lengths carry
millimetre precision (for example a skidpad circle of 56.549 m). Integer metres would be lossy.

**Query strategy.** One grouped query per request: `lap → run → track_layout`, plus `test`
for the season and vehicle scopes. It is filtered by the scope and `counts_toward_mileage`,
and returns the counted laps per layout. Python then sums `Decimal(length) × count`. SQLite
stores NUMERIC with REAL affinity, so `SUM(length)` in SQL would accumulate binary floating
point. The number of rows returned equals the number of distinct layouts, not the number of
laps.

**Indexes used** (no new index needed):

| Query | Index |
|---|---|
| Run laps | `uq_lap_run_id_lap_number` prefix |
| Test | `uq_run_test_id_run_number` prefix |
| Driver | `ix_run_driver_id` |
| Season, vehicle | `ix_test_season_id_test_date` and `ix_test_vehicle_id_test_date` |
| Layout join | primary key |

`physically_completed` has low selectivity and is evaluated as a residual filter. An index on
the effective-time expression is not justified at this scale; a run has tens of laps.

## Historical run search (`GET /api/v1/runs`, `app/queries/historical_runs.py`)

This endpoint covers the README's paramount requirement: multi-filter queries across tests.

**Filters.** Every supplied filter is combined with **AND**; there is no OR. Unknown
parameters are rejected with 422 `request_validation_failed`, never ignored, because a
mistyped filter must not return unfiltered history.

| Parameter | Matches |
|---|---|
| `season_id`, `vehicle_id`, `track_location_id` | the run's test |
| `driver_id`, `track_layout_id` | the run |
| `activity_type` | the run's layout |
| `date_from`, `date_to` | `test.test_date`, inclusive. The test day is the authoritative historical date. |
| `ambient_temperature_min_c` / `_max_c`, `asphalt_temperature_min_c` / `_max_c` | the run's conditions, inclusive, one decimal place |
| `planned_run_id` | every actual attempt of that plan |
| `tire_compound_id` | runs with **at least one** fitted tyre of that compound (correlated EXISTS, so a run with four matching corners appears once); runs without recorded fitment are excluded only when this filter is used |
| `has_plan` | `true` for planned runs, `false` for unexpected runs |
| `test_status` | the test's status |

**Validation.** An inverted range is a 422: `invalid_date_range`,
`invalid_ambient_temperature_range` or `invalid_asphalt_temperature_range`. Ranges are
never swapped. `has_plan=false` together with `planned_run_id` is a 422
`conflicting_plan_filters`. Ids must be positive. An id that matches nothing returns 200
with no items, not a 404.

**Missing conditions.** Conditions are optional. When a temperature filter is supplied,
runs with no conditions row, or with a NULL value for that temperature, are excluded. When
no temperature filter is supplied, they are included. Missing conditions are never invented.

**Ordering and pagination.** The order is fixed: `test_date desc`, `run_number asc`,
`id asc`. Client-chosen ordering is deliberately not offered. Pagination follows the
standard contract (limit 1–100, default 50). `total` is computed with the same joins and
filters as the page.

**Each item** contains:
- the run and its test (date, status);
- season, vehicle, driver, track location and layout references;
- `planned_run_id` and `unexpected`;
- `setup_snapshot_id`;
- a conditions summary;
- `recorded_lap_count` and `physically_completed_lap_count`;
- `fastest_lap` (eligible laps only, Phase 5 ranking, null if none);
- `distance_m` (completed laps × verified length, as an exact decimal).

Lap lists and setup corner values are left out; they have their own endpoints. Tests check
that the derived values equal the `/fastest-lap` and `/mileage` endpoints for every run.

**Query strategy.** The join is `run JOIN test JOIN track_layout LEFT JOIN run_condition`.
Every join is to-one, so a run can never be duplicated and the total is never inflated;
laps are not joined into the filter. A page costs **four statements regardless of its
size**: the count, the page itself with references loaded through `contains_eager` and
`joinedload`, the lap counts grouped by run, and the fastest lap per run through
`ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY FASTEST_LAP_ORDER)`. This is asserted by
a statement-count test. The batched lap statistics (`services.laps.lap_summaries`) also
serve `/fastest-lap` and the plan comparisons, so the ranking is defined in exactly one place.

**Index review** (EXPLAIN QUERY PLAN on the implemented queries):

| Query | Plan |
|---|---|
| Driver filter | `ix_run_driver_id` |
| Vehicle and dates | covering `ix_test_vehicle_id_test_date` range |
| Lap analytics by layout | `ix_run_track_layout_id`, then `uq_lap` prefix |
| Lap counts | covering `uq_lap` |
| Run to test, layout and condition | primary keys |

**No index was added.** Filtering by `planned_run_id` scans `run`. A plan has only a few
attempts, and the run table holds thousands of rows at most, so the scan is cheap.
`Run(planned_run_id)` is the first index to add if volume grows. Filtering by
`activity_type` also scans `run`, which is the right plan for a low-selectivity value.
Temperature indexes would have poor selectivity and are not justified. The temporary
B-tree used for ORDER BY works on the filtered rows, which is acceptable at this scale.

**Decimal bounds.** Temperature bounds are parsed as Decimal. SQLite stores and binds
NUMERIC as REAL, but a one-decimal bound and a one-decimal stored value convert to the same
double, so inclusive comparisons are exact. This is tested at the boundaries.

## Analytics

### `GET /analytics/fastest-laps`

Eligible laps across runs, ranked with the Phase 5 policy: effective time, then raw time,
then lap number, then lap id.

- **Filters.** The same AND filters as run search. `track_layout_id` or `activity_type` is
  **required** (otherwise 422 `invalid_search_filter`), because lap times on different
  layouts are not comparable and an unbounded global ranking is never returned.
- **Paging.** Results are paginated. `rank` is the position in the full ranking, so it
  continues across pages.
- **Each lap** carries its run, test, season, vehicle, driver, layout, conditions and setup
  snapshot id.

### `GET /tests/{id}/plan-vs-actual`

A test's whole run plan, classified.

- **Each plan** is one of `EXECUTED`, `NOT_EXECUTED`, `CANCELLED` or `REPLACED`, with its
  reasons and replacement link, its attempts, and a `repeated` flag.
- **Unexpected runs** are listed separately.
- **Counts** are given for each category.
- **Each attempt** gives its lap counts, its fastest effective time, and
  `differing_aspects`: the aspects that `/runs/{id}/plan-comparison` reports as DIFFERENT or
  TARGET_MISSED.
- **The comparison rules are not duplicated.** The per-run comparison was refactored into a
  pure `build_run_comparison(run, laps)`, which both endpoints call. Plans, runs with
  comparison data, and batched lap statistics are loaded in a fixed number of queries; a
  test checks this for 1, 3 and 11 runs.

### Pending (MVP-Complete, not implemented)

- **Setup-performance statistics** (best, median and standard deviation per setup, with
  sample-size warnings).
- **Run-to-previous-run setup history.**

These were deferred so that the MVP-Core search could be completed and verified before the
deadline. Tyres and the `tire_compound_id` filter were added in Phase 6.5. The filter
is shared by run search and `/analytics/fastest-laps`.

## Tyres, fitment and measurements (`app/services/tyres.py`)

Naming: code and paths use `tire`; a Tire is one physical tyre. The schema and invariants
are described in `docs/data-model.md` §3a.

**Inventory** (`/tire-compounds`, `/tire-sets`, `/tires`):
- Create, list and get.
- `POST /tire-sets` can create the set's tyres in the same transaction. A taken serial
  number rolls back the whole set.
- Filters: sets by `compound_id`; tyres by `tire_set_id`, `compound_id` and an exact
  `serial_number`.
- A standalone tyre needs `compound_id` (422 `tire_compound_required`). A tyre in a set takes
  the set's compound (422 `tire_compound_mismatch` if contradicted).

**Fitment** (`POST /runs/{id}/tire-assignments`):
- One to four corners per request, **all or nothing**.
- In-request duplicates are a 422: `duplicate_tire_corner` or `duplicate_tire_assignment`.
- A tyre id that doesn't exist is 422 `referenced_resource_not_found` on `assignments.{i}.tire_id`.
- A corner that already has a tyre, or a tyre already fitted to this run, is a 409
  `tire_assignment_conflict`. The service checks first, and the primary key and UNIQUE
  constraint are the backstop; both paths are tested.
- Fitment is create-once: no PATCH, PUT or DELETE.
- `GET` returns the fitment in FL, FR, RL, RR order, with each tyre and its compound, in two
  statements.

**Measurements** (`/runs/{id}/tire-measurements`, `/runs/{id}/alignment-measurements`):
- Batches of up to 8 (4 corners × 2 phases), all or nothing, create-once per (corner, phase).
- A tyre measurement needs a fitted tyre at that corner (422 `tire_assignment_not_found`;
  the composite FK is the backstop).
- Out-of-policy or empty values are a 422: `invalid_tire_measurement` or
  `invalid_alignment_measurement`. Precision violations are `request_validation_failed`.
- Repeated keys are 422 `duplicate_measurement_in_batch`. Existing keys are 409
  `tire_measurement_conflict` or `alignment_measurement_conflict`.
- Lists are ordered PRE_RUN then POST_RUN, then FL, FR, RL, RR, then id. `case()` expressions
  are used because alphabetical order would put POST_RUN first.
- Alignment measurements never change setup snapshots.

## Objectives and file index (`app/services/objectives.py`, `app/services/files.py`)

**Objectives:**
- `POST`/`GET /seasons/{id}/objectives` lists objectives CRITICAL first, then by id.
- `GET /objectives/{id}` returns derived progress: `linked_test_count`, `linked_run_count`
  and `remaining_repetitions`.
- `POST`/`GET /tests/{id}/objectives` and `/runs/{id}/objectives` link objectives:
  - `{"objective_ids": [...]}`, 1 to 50 ids, all or nothing;
  - an objective of another season is 422 `objective_season_mismatch`;
  - an existing link is 409 `objective_link_conflict`;
  - an unknown id is 422 `referenced_resource_not_found`.

**Files** (metadata only):
- `POST /tests/{id}/files` and `GET /tests/{id}/files?run_id=&file_type=` (newest first),
  and `GET /files/{id}`.
- A run of another test is 422 `run_not_in_test`. A known checksum is 409
  `file_checksum_taken`. An invalid checksum, size, name, URI or metadata is 422.

## Seed data (`backend/scripts/seed.py`)

Run with `python -m scripts.seed [--database-url …]`, after `alembic upgrade head`.

- The dataset is deterministic and synthetic: 152 rows across every table.
- It is built **through the same services and schemas as the API**, so it obeys every rule;
  a seed that broke a rule would fail.
- **One transaction.** The marker season `DEMO 2025/26` makes a repeat run report "already
  present" and write nothing. A failure part-way rolls everything back, so the dataset is
  always either fully present or absent. Both cases are tested.
- **What it demonstrates:**
  - Two seasons, two vehicles, three drivers, two locations, and four layouts (autocross,
    endurance, skidpad, acceleration).
  - Four objectives with links.
  - A plan with every outcome: completed; cancelled; replaced, then executed twice (an
    aborted attempt and a retry); never executed. Plus an unexpected run.
  - Root and derived setup snapshots.
  - Varied conditions.
  - Every lap kind: valid, penalised, timing-invalid but completed, untimed, IN and OUT
    laps, and ABORTED laps both completed and not.
  - Three compounds, three sets, a spare tyre, and mixed-compound fitment.
  - PRE and POST tyre and alignment measurements.
  - Four indexed files.
- The README query (season + driver + compound + asphalt 30–40 °C) returns runs 1, 3 and 4
  of the autocross day. This is tested.

## CSV import

See [import-strategy.md](import-strategy.md): the canonical format, normalisation, the
duplicate policy, whole-file atomicity, and dry run (the default).


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
| setup snapshots | `created_at desc`, `id desc` |
| laps of a run | `lap_number asc`, `id asc` |
| run search | `test_date desc`, `run_number asc`, `id asc` |
| fastest-lap ranking | `effective_time_ms`, `raw_time_ms`, `lap_number`, `lap_id` (all asc) |
| tyre compounds | `manufacturer asc`, `name asc`, `id asc` |
| tyre sets, tyres | `set_code asc` / `serial_number asc`, then `id asc` |
| season objectives | priority (CRITICAL, HIGH, MEDIUM, LOW), then `id asc` |
| files of a test | `imported_at desc`, `id desc` |

Offset pagination becomes slower at deep offsets and can skip or repeat rows when data
changes between page requests. Cursor pagination over the same orderings is the planned upgrade.

**Loading:** list endpoints return compact summaries containing only columns of the listed
table, so they make no relationship loads (no N+1). Detail endpoints load exactly what they
return: a test loads its season, vehicle and location with `joinedload` and its plan with
`selectinload`; a run loads its driver and layout with `joinedload`. A planned-run detail
`selectinload`s its runs and the plans it replaces. A snapshot detail `joinedload`s its
vehicle and source and `selectinload`s its corners. The plan comparison loads the plan, both
setup snapshots and their corners in a fixed number of queries.

## Update and delete policy

The API has **no PATCH, PUT or DELETE operations**. Historical records (tests, planned runs,
runs, setup snapshots, run conditions and laps) cannot be destroyed or overwritten through it. The only state
changes are the named planned-run commands above. A planned run is always created as
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
| Planned-run commands | `POST /planned-runs/{id}/cancel`, `POST /planned-runs/{id}/replace`, `POST /planned-runs/{id}/complete` |
| Actual runs | `POST /tests/{id}/runs`, `GET /tests/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/plan-comparison` |
| Setup snapshots | `POST /setup-snapshots`, `GET /setup-snapshots?vehicle_id=&based_on_snapshot_id=`, `GET /setup-snapshots/{id}`, `POST /setup-snapshots/{id}/derive`, `GET /setup-snapshots/{id}/diff?against_snapshot_id=` |
| Run conditions | `POST /runs/{id}/conditions` (write-once), `GET /runs/{id}/conditions` |
| Laps | `POST /runs/{id}/laps`, `POST /runs/{id}/laps/bulk`, `GET /runs/{id}/laps`, `GET /laps/{id}`, `GET /runs/{id}/fastest-lap` |
| Mileage | `GET /runs/{id}/mileage`, `GET /tests/{id}/mileage`, `GET /seasons/{id}/mileage`, `GET /vehicles/{id}/mileage`, `GET /drivers/{id}/mileage` |
| Historical search | `GET /runs?season_id=&vehicle_id=&driver_id=&track_location_id=&track_layout_id=&activity_type=&date_from=&date_to=&ambient_temperature_min_c=&ambient_temperature_max_c=&asphalt_temperature_min_c=&asphalt_temperature_max_c=&tire_compound_id=&planned_run_id=&has_plan=&test_status=` |
| Analytics | `GET /analytics/fastest-laps?track_layout_id=|activity_type=&…`, `GET /tests/{id}/plan-vs-actual` |
| Tyre inventory | `POST`/`GET /tire-compounds`, `GET /tire-compounds/{id}`, `POST`/`GET /tire-sets`, `GET /tire-sets/{id}`, `POST`/`GET /tires`, `GET /tires/{id}` |
| Fitment and measurements | `POST`/`GET /runs/{id}/tire-assignments`, `POST`/`GET /runs/{id}/tire-measurements`, `POST`/`GET /runs/{id}/alignment-measurements` |
| Objectives | `POST`/`GET /seasons/{id}/objectives`, `GET /objectives/{id}`, `POST`/`GET /tests/{id}/objectives`, `POST`/`GET /runs/{id}/objectives` |
| File index | `POST`/`GET /tests/{id}/files`, `GET /files/{id}` |

The following do not exist yet and are not shown in OpenAPI:

- setup-performance statistics
- run-to-previous-run setup history
- test-day stations (Extended)
- binary file upload or download (by design)
