# Historical data import strategy

Status: **implemented** (Phase 7). The code is in `backend/app/services/csv_import.py`, the
command line is `backend/scripts/import_csv.py`, and a sample file is at
`backend/sample-data/historical_runs.csv`.

## Goal and scope

The team's history lives in hand-maintained spreadsheets. Rather than guess at every
spreadsheet layout, the importer accepts **one canonical CSV format**. Existing sheets are
exported or reshaped into it once, for example with a spreadsheet formula or a short
script. The importer then:
- normalises cosmetic differences such as whitespace, case and boolean spellings;
- validates every value with the same rules as the API;
- refuses anything that is ambiguous, unknown or contradictory.

**It never invents a value.**

## Commands

```bash
cd backend
alembic upgrade head
python -m scripts.seed                                              # reference data for the sample
python -m scripts.import_csv sample-data/historical_runs.csv        # dry run (default)
python -m scripts.import_csv sample-data/historical_runs.csv --commit
python -m scripts.import_csv path.csv --database-url sqlite:///other.sqlite3
```

The summary is printed as JSON:

```json
{
  "file": "historical_runs.csv", "dry_run": true, "committed": false,
  "total_rows": 10, "valid_rows": 10, "invalid_rows": 0,
  "created": {"tests": 1, "runs": 2, "run_conditions": 2, "laps": 9, "tire_assignments": 4},
  "reused": {}, "skipped": {"duplicate_rows_in_file": 1},
  "errors": []
}
```

Each error has the form `{"row": 7, "field": "raw_time_ms", "code": "impossible_lap_time",
"message": "…"}`. Rows are numbered as in a spreadsheet: the header is row 1, so the first
data row is row 2. File-level errors have `row: null`.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Validation errors; nothing was written |
| 2 | Unreadable file or unexpected failure; nothing was written |

## Canonical format

The file is UTF-8 (an Excel BOM is accepted), comma-separated, with a header row.
**One row is one lap.** Run-level and test-level columns repeat on every lap row of that run
or test, and **must agree**; otherwise the row gets `inconsistent_value`. Unknown columns
reject the file (`unknown_column`), so data is never dropped silently. Optional columns may
be omitted from the header.

| Column | Level | Required | Type | Mapping |
|---|---|---|---|---|
| `season_name` | test | yes | text | **looked up** by exact name |
| `vehicle_code` | test | yes | text | **looked up** by exact code |
| `track_location` | test | yes | text | **looked up** by exact name |
| `test_date` | test | yes | ISO `YYYY-MM-DD` | test natural key, with season, vehicle and location |
| `test_status` | test | yes | enum | PLANNED, IN_PROGRESS, COMPLETED or CANCELLED |
| `run_number` | run | yes | integer | run natural key within the test |
| `driver_code` | run | yes | text | **looked up** by exact code |
| `track_layout` | run | yes | text | **looked up** by name at `track_location` |
| `planned_run_sequence` | run | no | integer | **looked up** in an existing test; blank means an unexpected run |
| `setup_name` | run | no | text | **looked up**: the single snapshot with that name for the vehicle |
| `ambient_temperature_c`, `asphalt_temperature_c` | run | no | decimal, `.` separator | run conditions |
| `conditions_source` | run | if a temperature is given | enum | MEASURED or ESTIMATED |
| `weather`, `track_state` | run | no | enum | as in the API |
| `tire_fl`, `tire_fr`, `tire_rl`, `tire_rr` | run | no | text | **looked up** tyre serial numbers, then fitted to the run |
| `lap_number` | lap | yes | integer | lap natural key within the run |
| `lap_classification` | lap | yes | enum | FLYING, IN_LAP, OUT_LAP or ABORTED |
| `raw_time_ms` | lap | yes (may be blank) | integer ms | blank means an untimed lap, which must be timing-invalid |
| `penalty_duration_ms` | lap | no | integer ms | blank means 0 |
| `timing_valid`, `physically_completed` | lap | yes | boolean | |
| `invalidation_reason` | lap | if timing-invalid | text | |

### What is created and what must already exist

| Kind | Entities | Policy |
|---|---|---|
| **Created** | tests, runs, run conditions, laps, tyre fitment | Always through the domain services (`create_test`, `create_run`, `create_run_condition`, `create_laps`, `assign_tires`), so every API rule applies: layout at the test's location, plan in the test and not cancelled or replaced, setup of the test's vehicle, lap validity and implied speed, temperature ranges, fitment uniqueness. |
| **Looked up only** | season, vehicle, driver, track location, layout, planned run, setup snapshot, tyres | A missing entity is `unknown_entity`; more than one match is `ambiguous_entity`. **There is no fuzzy matching and nothing is created implicitly.** Layouts in particular need a *verified* length, which a spreadsheet cannot provide. |

## Normalisation

| Input | Rule |
|---|---|
| Any cell | Leading and trailing whitespace is removed. An empty cell means "no value". |
| Enums | Spaces and hyphens become underscores, then the value is upper-cased: `in lap` and `In-Lap` both become `IN_LAP`. |
| Booleans | `true`/`yes`/`y`/`1` and `false`/`no`/`n`/`0`, case-insensitive. Anything else is `invalid_boolean`. |
| Integers | Digits only. `64,000`, `64000.0` and `1e3` are `invalid_integer`. Locale-specific thousands separators are deliberately not guessed. |
| Decimals | An optional minus sign, digits, and an optional `.` fraction. `21,5` is `invalid_decimal`. Precision is then checked by the API schema. |
| Dates | ISO `YYYY-MM-DD` only. `06/12/2025` is `invalid_date`, because day and month order cannot be safely guessed. |
| Identifiers | Exact match after trimming. Case is significant, as in the API. |

## Duplicate detection

| Situation | Result |
|---|---|
| The same lap appears twice in the file with identical values | skipped (`duplicate_rows_in_file`) |
| The same lap appears twice in the file with different values | error `conflicting_duplicate` |
| The test day already exists (season, vehicle, location, date) | **reused**; a different status is `conflicting_duplicate`; two matching tests are `ambiguous_entity` |
| The run already exists (test, run number) with the same driver, layout, plan and setup | **reused**; any difference is `conflicting_duplicate` |
| The lap already exists with the same values | skipped (`existing_laps`); different values are `conflicting_duplicate` |
| Conditions or fitment already exist with the same values | reused; different values are `conflicting_duplicate` |

Re-importing the same file is therefore harmless: nothing is created, and everything is
reported as reused or skipped. This is tested. Existing equivalent data is **never counted
as a new insert**.

## Transactions

- **The whole file is atomic.** One error anywhere means nothing is written, whether it is a
  parse error, a failed lookup, a duplicate conflict, a domain rule violated in the write
  pass, a database constraint, or a failed commit. A partially imported spreadsheet would be
  worse than none: the team could no longer tell which rows had been loaded.
- **There are two passes.**
  1. A validation pass parses every row, resolves every entity and validates every lap. It
     reports **all** problems with row and field, and writes nothing.
  2. The write pass then calls the domain services in file order. If a service rejects
     something here, for example a cross-row rule, the first such error is reported with
     its row, and the transaction is rolled back.
- **Dry run is the default.** A dry run executes *both* passes, including the real service
  calls, and then rolls back. Its summary therefore describes exactly what `--commit` would
  write.
- **Retrying is safe.** After fixing the file it can simply be run again. Nothing from an
  earlier failed attempt persists, and data from an earlier successful import is reused or
  skipped.

## Limitations

- **Format.** Only the canonical format is accepted. Converting arbitrary spreadsheets into
  it is a manual mapping step.
- **What the CSV cannot carry:**
  - reference data, which must be loaded first via the API or the seed;
  - setup values (only an existing snapshot can be referenced, by name);
  - tyre and alignment measurements;
  - objectives and files.
- **Validation is per file.** A 10 000-row file is validated and written in one transaction
  in memory, which is fine at spreadsheet scale. There is no streaming.
- **Errors in the write pass** are reported one at a time (the first failure). Errors in the
  validation pass are all reported together.
- **Provenance is not stored.** There is no import-batch table recording which file created
  which rows. Re-import detection relies on natural keys instead.
