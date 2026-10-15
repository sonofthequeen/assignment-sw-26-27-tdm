"""Import of historical lap spreadsheets in the canonical CSV format.

One CSV row = one lap. Run-level and test-level columns repeat on every lap row
of that run/test and must agree. The format is documented in
docs/import-strategy.md; the summary of guarantees:

- Whole-file atomicity: any error anywhere means nothing is written.
- Dry run (the default) executes the complete write path through the domain
  services and then rolls back, so it reports exactly what a commit would do.
- Reference data (season, vehicle, driver, location, layout, plan, setup,
  tyres) is looked up by exact natural key and never created; a layout's
  verified length cannot come from a spreadsheet.
- Tests, runs, conditions, laps and tyre fitment are created through the same
  services as the API; equal existing rows are reused/skipped, different ones are
  rejected as conflicting duplicates. No value is ever invented.
"""

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.exceptions import DomainError
from app.models import (
    Driver,
    Lap,
    PlannedRun,
    Run,
    RunCondition,
    RunTireAssignment,
    Season,
    SetupSnapshot,
    Test,
    Tire,
    TrackLayout,
    TrackLocation,
    Vehicle,
)
from app.schemas.conditions import RunConditionCreate
from app.schemas.laps import LapBulkCreate, LapCreate
from app.schemas.testing import RunCreate, TestCreate
from app.schemas.tyres import RunTireAssignmentBatchCreate
from app.services import conditions as condition_service
from app.services import laps as lap_service
from app.services import testing as testing_service
from app.services import tyres as tyre_service

REQUIRED_COLUMNS = (
    "season_name",
    "vehicle_code",
    "driver_code",
    "test_date",
    "test_status",
    "track_location",
    "track_layout",
    "run_number",
    "lap_number",
    "lap_classification",
    "raw_time_ms",
    "timing_valid",
    "physically_completed",
)
OPTIONAL_COLUMNS = (
    "penalty_duration_ms",
    "invalidation_reason",
    "planned_run_sequence",
    "setup_name",
    "ambient_temperature_c",
    "asphalt_temperature_c",
    "conditions_source",
    "weather",
    "track_state",
    "tire_fl",
    "tire_fr",
    "tire_rl",
    "tire_rr",
)
CORNER_COLUMNS = {"FL": "tire_fl", "FR": "tire_fr", "RL": "tire_rl", "RR": "tire_rr"}
TEST_FIELDS = ("test_status",)
RUN_FIELDS = (
    "driver_code",
    "track_layout",
    "planned_run_sequence",
    "setup_name",
    "ambient_temperature_c",
    "asphalt_temperature_c",
    "conditions_source",
    "weather",
    "track_state",
    *CORNER_COLUMNS.values(),
)
LAP_FIELDS = (
    "lap_classification",
    "raw_time_ms",
    "penalty_duration_ms",
    "timing_valid",
    "physically_completed",
    "invalidation_reason",
)
CONDITION_FIELDS = (
    "ambient_temperature_c",
    "asphalt_temperature_c",
    "conditions_source",
    "weather",
    "track_state",
)
ENUM_COLUMNS = (
    "test_status",
    "lap_classification",
    "conditions_source",
    "weather",
    "track_state",
)
INTEGER_COLUMNS = (
    "run_number",
    "lap_number",
    "raw_time_ms",
    "penalty_duration_ms",
    "planned_run_sequence",
)
DECIMAL_COLUMNS = ("ambient_temperature_c", "asphalt_temperature_c")
BOOLEAN_COLUMNS = ("timing_valid", "physically_completed")
TRUE_VALUES = {"true", "yes", "y", "1"}
FALSE_VALUES = {"false", "no", "n", "0"}
INTEGER = re.compile(r"^[0-9]+$")
DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


# --- Result ---------------------------------------------------------------------------


@dataclass
class ImportIssue:
    row: int | None
    field: str | None
    code: str
    message: str


@dataclass
class ImportResult:
    file: str
    dry_run: bool
    committed: bool = False
    total_rows: int = 0
    invalid_row_numbers: set[int] = field(default_factory=set)
    created: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reused: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: list[ImportIssue] = field(default_factory=list)

    def error(self, row, field_name, code, message) -> None:
        self.errors.append(ImportIssue(row, field_name, code, message))
        if row is not None:
            self.invalid_row_numbers.add(row)

    def to_dict(self) -> dict:
        invalid = len(self.invalid_row_numbers)
        file_level = any(e.row is None for e in self.errors)
        return {
            "file": self.file,
            "dry_run": self.dry_run,
            "committed": self.committed,
            "total_rows": self.total_rows,
            "valid_rows": 0 if file_level else self.total_rows - invalid,
            "invalid_rows": invalid,
            "created": _nonzero(self.created),
            "reused": _nonzero(self.reused),
            "skipped": _nonzero(self.skipped),
            "errors": [e.__dict__ for e in self.errors],
        }


def _nonzero(counts: dict) -> dict:
    return {name: count for name, count in sorted(counts.items()) if count}


class _Abort(Exception):
    """Stops the write pass; the caller rolls the whole file back."""


# --- Parsing and normalisation ---------------------------------------------------------


@dataclass
class ParsedRow:
    line: int
    values: dict

    @property
    def test_key(self) -> tuple:
        v = self.values
        return (v["season_name"], v["vehicle_code"], v["track_location"], v["test_date"])

    @property
    def run_key(self) -> tuple:
        return (*self.test_key, self.values["run_number"])


def _normalise(column: str, raw: str | None):
    value = (raw or "").strip()
    if value == "":
        return None
    if column in ENUM_COLUMNS:
        return re.sub(r"[\s-]+", "_", value).upper()
    if column in BOOLEAN_COLUMNS:
        lowered = value.lower()
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
        raise ValueError("invalid_boolean", f"{value!r} is not a boolean (true/false/yes/no/1/0)")
    if column in INTEGER_COLUMNS:
        if not INTEGER.match(value):
            raise ValueError("invalid_integer", f"{value!r} is not a whole number (no separators)")
        return int(value)
    if column in DECIMAL_COLUMNS:
        if not DECIMAL.match(value):
            raise ValueError("invalid_decimal", f"{value!r} is not a decimal ('.' separator)")
        return Decimal(value)
    if column == "test_date":
        try:
            if not DATE.match(value):
                raise ValueError
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError("invalid_date", f"{value!r} is not an ISO date (YYYY-MM-DD)") from None
    return value


def _parse(path: Path, result: ImportResult) -> list[ParsedRow]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = [h.strip() for h in (reader.fieldnames or [])]
        if not header:
            result.error(None, None, "empty_file", "The file has no header row.")
            return []
        reader.fieldnames = header
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        unknown = [c for c in header if c not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS]
        for column in missing:
            result.error(None, column, "missing_column", f"Required column {column!r} is missing.")
        for column in unknown:
            result.error(None, column, "unknown_column", f"Column {column!r} is not supported.")
        if missing or unknown:
            return []

        rows = []
        for line, record in enumerate(reader, start=2):
            result.total_rows += 1
            values, ok = {}, True
            for column in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
                try:
                    values[column] = _normalise(column, record.get(column))
                except ValueError as exc:
                    code, message = exc.args
                    result.error(line, column, code, message)
                    values[column], ok = None, False
                    continue
                # raw_time_ms may be blank: an untimed lap (it must then be timing-invalid).
                if (
                    column in REQUIRED_COLUMNS
                    and column != "raw_time_ms"
                    and values[column] is None
                ):
                    result.error(line, column, "missing_value", f"{column} is required.")
                    ok = False
            if values.get("penalty_duration_ms") is None:
                values["penalty_duration_ms"] = 0
            if ok:
                rows.append(ParsedRow(line, values))
        if result.total_rows == 0:
            result.error(None, None, "empty_file", "The file contains no data rows.")
        return rows


# --- Validation pass (no writes) ---------------------------------------------------------


def _pydantic_errors(result, line, exc: ValidationError) -> None:
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or None
        result.error(line, location, "invalid_value", error["msg"])


def _consistent(result, rows: list[ParsedRow], fields, level) -> bool:
    first = rows[0]
    ok = True
    for row in rows[1:]:
        for name in fields:
            if row.values[name] != first.values[name]:
                result.error(
                    row.line,
                    name,
                    "inconsistent_value",
                    f"{name} differs from row {first.line} of the same {level}.",
                )
                ok = False
    return ok


@dataclass
class _Resolved:
    season: Season
    vehicle: Vehicle
    location: TrackLocation
    test: Test | None  # None: will be created
    status: str
    runs: dict = field(default_factory=dict)


def _one(session, statement, result, line, column, label):
    matches = session.scalars(statement.limit(2)).all()
    if not matches:
        result.error(line, column, "unknown_entity", f"No {label} matches; it must exist first.")
        return None
    if len(matches) > 1:
        result.error(line, column, "ambiguous_entity", f"More than one {label} matches.")
        return None
    return matches[0]


def _lap_create(values) -> LapCreate:
    return LapCreate(lap_number=values["lap_number"], **{f: values[f] for f in LAP_FIELDS})


def _condition_create(values) -> RunConditionCreate | None:
    data = {f: values[f] for f in CONDITION_FIELDS}
    if all(v is None for v in data.values()):
        return None
    return RunConditionCreate(**data)


def _same_lap(existing: Lap, lap: LapCreate) -> bool:
    return all(getattr(existing, f) == getattr(lap, f) for f in LAP_FIELDS)


def _validate(session: Session, rows: list[ParsedRow], result: ImportResult) -> dict:
    """Resolves entities and validates every row; collects all errors, writes nothing."""
    tests: dict[tuple, list[ParsedRow]] = defaultdict(list)
    for row in rows:
        tests[row.test_key].append(row)

    plan = {}
    for test_key, test_rows in tests.items():
        _consistent(result, test_rows, TEST_FIELDS, "test")
        first = test_rows[0]
        season_name, vehicle_code, location_name, test_date = test_key
        season = _one(
            session,
            select(Season).where(Season.name == season_name),
            result,
            first.line,
            "season_name",
            "season",
        )
        vehicle = _one(
            session,
            select(Vehicle).where(Vehicle.code == vehicle_code),
            result,
            first.line,
            "vehicle_code",
            "vehicle",
        )
        location = _one(
            session,
            select(TrackLocation).where(TrackLocation.name == location_name),
            result,
            first.line,
            "track_location",
            "track location",
        )
        if not (season and vehicle and location):
            continue
        existing_tests = session.scalars(
            select(Test).where(
                Test.season_id == season.id,
                Test.vehicle_id == vehicle.id,
                Test.track_location_id == location.id,
                Test.test_date == test_date,
            )
        ).all()
        if len(existing_tests) > 1:
            result.error(
                first.line, "test_date", "ambiguous_entity", "More than one test matches this day."
            )
            continue
        test = existing_tests[0] if existing_tests else None
        if test and test.status != first.values["test_status"]:
            result.error(
                first.line,
                "test_status",
                "conflicting_duplicate",
                f"Existing test has status {test.status}.",
            )
        try:
            TestCreate(
                season_id=season.id,
                vehicle_id=vehicle.id,
                track_location_id=location.id,
                test_date=test_date,
                status=first.values["test_status"],
            )
        except ValidationError as exc:
            _pydantic_errors(result, first.line, exc)
            continue
        resolved = _Resolved(season, vehicle, location, test, first.values["test_status"])
        plan[test_key] = resolved

        runs: dict[int, list[ParsedRow]] = defaultdict(list)
        for row in test_rows:
            runs[row.values["run_number"]].append(row)
        for run_number, run_rows in runs.items():
            resolved.runs[run_number] = _validate_run(
                session, resolved, run_number, run_rows, result
            )
    return plan


def _validate_run(session, resolved: _Resolved, run_number, run_rows, result) -> dict:
    first = run_rows[0]
    values = first.values
    _consistent(result, run_rows, RUN_FIELDS, "run")
    driver = _one(
        session,
        select(Driver).where(Driver.code == values["driver_code"]),
        result,
        first.line,
        "driver_code",
        "driver",
    )
    layout = _one(
        session,
        select(TrackLayout).where(
            TrackLayout.track_location_id == resolved.location.id,
            TrackLayout.name == values["track_layout"],
        ),
        result,
        first.line,
        "track_layout",
        "track layout at this location",
    )
    setup_snapshot = None
    if values["setup_name"] is not None:
        setup_snapshot = _one(
            session,
            select(SetupSnapshot).where(
                SetupSnapshot.vehicle_id == resolved.vehicle.id,
                SetupSnapshot.name == values["setup_name"],
            ),
            result,
            first.line,
            "setup_name",
            "setup snapshot with this name for the vehicle",
        )
    planned_run = None
    if values["planned_run_sequence"] is not None:
        if resolved.test is None:
            result.error(
                first.line,
                "planned_run_sequence",
                "unknown_entity",
                "A new test has no planned runs.",
            )
        else:
            planned_run = _one(
                session,
                select(PlannedRun).where(
                    PlannedRun.test_id == resolved.test.id,
                    PlannedRun.sequence_number == values["planned_run_sequence"],
                ),
                result,
                first.line,
                "planned_run_sequence",
                "planned run with this sequence number",
            )
    tires = {}
    for corner, column in CORNER_COLUMNS.items():
        if values[column] is not None:
            tire = _one(
                session,
                select(Tire).where(Tire.serial_number == values[column]),
                result,
                first.line,
                column,
                "tyre with this serial number",
            )
            if tire:
                tires[corner] = tire
    condition = None
    try:
        condition = _condition_create(values)
        if condition:
            condition_service.validate_condition_ranges(condition)
    except ValidationError as exc:
        _pydantic_errors(result, first.line, exc)
    except DomainError as exc:
        for detail in exc.details:
            result.error(first.line, detail.field, exc.code, exc.message)

    run = None
    if resolved.test is not None:
        run = session.scalar(
            select(Run).where(Run.test_id == resolved.test.id, Run.run_number == run_number)
        )
    if run is not None and driver and layout:
        expected = {
            "driver": driver.id,
            "track_layout": layout.id,
            "planned_run_sequence": planned_run.id if planned_run else None,
            "setup_name": setup_snapshot.id if setup_snapshot else None,
        }
        actual = {
            "driver": run.driver_id,
            "track_layout": run.track_layout_id,
            "planned_run_sequence": run.planned_run_id,
            "setup_name": run.setup_snapshot_id,
        }
        for name in expected:
            if expected[name] != actual[name]:
                result.error(
                    first.line,
                    name if name != "driver" else "driver_code",
                    "conflicting_duplicate",
                    f"Run {run_number} already exists with a different {name}.",
                )

    laps: list[tuple[ParsedRow, LapCreate]] = []
    seen: dict[int, ParsedRow] = {}
    for row in run_rows:
        number = row.values["lap_number"]
        if number in seen:
            if row.values == seen[number].values:
                result.skipped["duplicate_rows_in_file"] += 1
            else:
                result.error(
                    row.line,
                    "lap_number",
                    "conflicting_duplicate",
                    f"Lap {number} also appears on row {seen[number].line} with different values.",
                )
            continue
        seen[number] = row
        try:
            lap = _lap_create(row.values)
        except ValidationError as exc:
            _pydantic_errors(result, row.line, exc)
            continue
        if layout is not None:
            try:
                lap_service.validate_lap(lap, SimpleNamespace(track_layout=layout))
            except DomainError as exc:
                field_name = exc.details[0].field if exc.details else None
                result.error(row.line, field_name, exc.code, exc.message)
                continue
        if run is not None:
            existing = session.scalar(
                select(Lap).where(Lap.run_id == run.id, Lap.lap_number == number)
            )
            if existing is not None:
                if _same_lap(existing, lap):
                    result.skipped["existing_laps"] += 1
                else:
                    result.error(
                        row.line,
                        "lap_number",
                        "conflicting_duplicate",
                        f"Lap {number} already exists with different values.",
                    )
                continue
        laps.append((row, lap))

    if run is not None and condition is not None:
        existing = session.get(RunCondition, run.id)
        if existing is not None:
            same = all(getattr(existing, f) == getattr(condition, f) for f in CONDITION_FIELDS)
            if not same:
                result.error(
                    first.line,
                    "asphalt_temperature_c",
                    "conflicting_duplicate",
                    "The run already has different conditions.",
                )
    if run is not None:
        fitted = {
            a.corner: a.tire_id
            for a in session.scalars(
                select(RunTireAssignment).where(RunTireAssignment.run_id == run.id)
            )
        }
        for corner, tire in tires.items():
            if corner in fitted and fitted[corner] != tire.id:
                result.error(
                    first.line,
                    CORNER_COLUMNS[corner],
                    "conflicting_duplicate",
                    f"{corner} already has a different tyre.",
                )
    return {
        "first_line": first.line,
        "driver": driver,
        "layout": layout,
        "setup": setup_snapshot,
        "planned_run": planned_run,
        "tires": tires,
        "condition": condition,
        "run": run,
        "laps": laps,
    }


# --- Write pass (domain services, inside the caller's transaction) ------------------------


def _write(session: Session, plan: dict, result: ImportResult) -> None:
    for (_, _, _, test_date), resolved in plan.items():
        test = resolved.test
        if test is None:
            test = testing_service.create_test(
                session,
                TestCreate(
                    season_id=resolved.season.id,
                    vehicle_id=resolved.vehicle.id,
                    track_location_id=resolved.location.id,
                    test_date=test_date,
                    status=resolved.status,
                ),
            )
            result.created["tests"] += 1
        else:
            result.reused["tests"] += 1
        for run_number, item in resolved.runs.items():
            line = item["first_line"]
            try:
                _write_run(session, test, run_number, item, result)
            except DomainError as exc:
                field_name = exc.details[0].field if exc.details else None
                result.error(line, field_name, exc.code, exc.message)
                raise _Abort from exc


def _write_run(session, test, run_number, item, result) -> None:
    run = item["run"]
    if run is None:
        run = testing_service.create_run(
            session,
            test.id,
            RunCreate(
                run_number=run_number,
                planned_run_id=item["planned_run"].id if item["planned_run"] else None,
                driver_id=item["driver"].id,
                track_layout_id=item["layout"].id,
                setup_snapshot_id=item["setup"].id if item["setup"] else None,
            ),
        )
        result.created["runs"] += 1
    else:
        result.reused["runs"] += 1

    if item["condition"] is not None:
        if session.get(RunCondition, run.id) is None:
            condition_service.create_run_condition(session, run.id, item["condition"])
            result.created["run_conditions"] += 1
        else:
            result.reused["run_conditions"] += 1

    if item["laps"]:
        lap_service.create_laps(
            session, run.id, LapBulkCreate(laps=[lap for _, lap in item["laps"]])
        )
        result.created["laps"] += len(item["laps"])

    fitted = {
        a.corner
        for a in session.scalars(
            select(RunTireAssignment).where(RunTireAssignment.run_id == run.id)
        )
    }
    new = [{"corner": c, "tire_id": t.id} for c, t in item["tires"].items() if c not in fitted]
    result.reused["tire_assignments"] += len(item["tires"]) - len(new)
    if new:
        tyre_service.assign_tires(session, run.id, RunTireAssignmentBatchCreate(assignments=new))
        result.created["tire_assignments"] += len(new)


# --- Entry point ------------------------------------------------------------------------


def import_csv(session_factory: sessionmaker, path: Path, commit: bool) -> ImportResult:
    """Validates, then writes through the services; commits only if commit=True and no error."""
    result = ImportResult(file=path.name, dry_run=not commit)
    rows = _parse(path, result)
    with session_factory() as session:
        try:
            plan = _validate(session, rows, result) if rows else {}
            if not result.errors:
                _write(session, plan, result)
        except _Abort:
            pass
        except Exception:
            session.rollback()
            raise
        if result.errors or not commit:
            session.rollback()
            if result.errors:
                # Nothing was written: report what *would* have been created as zero.
                result.created.clear()
                result.reused.clear()
        else:
            session.commit()
            result.committed = True
    return result
