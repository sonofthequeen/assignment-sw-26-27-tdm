"""Tests, planned runs and actual (on-track) runs.

Cross-row rules enforced here (the schema cannot express them without
denormalising or triggers):
- a run's / planned run's track layout must be at the test's track location;
- a referenced setup snapshot must belong to the test's vehicle;
- a run's planned run must belong to the same test.

Planned-run status transitions (cancel/replace) are not part of this module yet.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.exceptions import DomainValidationError, NotFoundError
from app.models import (
    Driver,
    PlannedRun,
    Run,
    Season,
    SetupSnapshot,
    Test,
    TrackLayout,
    TrackLocation,
    Vehicle,
)
from app.schemas.common import PageQuery
from app.schemas.testing import PlannedRunCreate, RunCreate, TestCreate, TestListQuery
from app.services.lookup import get_or_404, get_referenced
from app.services.pagination import Ordering, PageResult, paginate

TEST_ORDER = (
    Ordering("test_date desc", Test.test_date.desc()),
    Ordering("id desc", Test.id.desc()),
)
PLANNED_RUN_ORDER = (
    Ordering("sequence_number asc", PlannedRun.sequence_number.asc()),
    Ordering("id asc", PlannedRun.id.asc()),
)
RUN_ORDER = (Ordering("run_number asc", Run.run_number.asc()), Ordering("id asc", Run.id.asc()))


# --- Cross-row validation -----------------------------------------------------


def _layout_at_test_location(session: Session, test: Test, layout_id: int, field: str) -> None:
    layout = get_referenced(session, TrackLayout, layout_id, "track_layout", field)
    if layout.track_location_id != test.track_location_id:
        raise DomainValidationError.for_field(
            "track_layout_not_at_test_location",
            field,
            f"Track layout {layout_id} is not at the test's track location.",
        )


def _setup_for_test_vehicle(session: Session, test: Test, snapshot_id: int, field: str) -> None:
    snapshot = get_referenced(session, SetupSnapshot, snapshot_id, "setup_snapshot", field)
    if snapshot.vehicle_id != test.vehicle_id:
        raise DomainValidationError.for_field(
            "setup_snapshot_vehicle_mismatch",
            field,
            f"Setup snapshot {snapshot_id} belongs to a different vehicle than the test.",
        )


def _validate_planned_run_references(
    session: Session, test: Test, data: PlannedRunCreate, prefix: str = ""
) -> None:
    if data.expected_driver_id is not None:
        get_referenced(
            session, Driver, data.expected_driver_id, "driver", f"{prefix}expected_driver_id"
        )
    if data.expected_track_layout_id is not None:
        _layout_at_test_location(
            session, test, data.expected_track_layout_id, f"{prefix}expected_track_layout_id"
        )
    if data.expected_setup_snapshot_id is not None:
        _setup_for_test_vehicle(
            session, test, data.expected_setup_snapshot_id, f"{prefix}expected_setup_snapshot_id"
        )


# --- Tests ----------------------------------------------------------------------


def create_test(session: Session, data: TestCreate) -> Test:
    """Creates the test and its optional run plan in the caller's transaction."""
    get_referenced(session, Season, data.season_id, "season", "season_id")
    get_referenced(session, Vehicle, data.vehicle_id, "vehicle", "vehicle_id")
    get_referenced(
        session, TrackLocation, data.track_location_id, "track_location", "track_location_id"
    )
    test = Test(**data.model_dump(exclude={"planned_runs"}))
    session.add(test)
    session.flush()

    for index, planned in enumerate(data.planned_runs):
        _validate_planned_run_references(session, test, planned, prefix=f"planned_runs.{index}.")
        session.add(PlannedRun(test_id=test.id, **planned.model_dump()))
    session.flush()
    return get_test(session, test.id)


def get_test(session: Session, test_id: int) -> Test:
    test = session.scalar(
        select(Test)
        .where(Test.id == test_id)
        .options(
            joinedload(Test.season),
            joinedload(Test.vehicle),
            joinedload(Test.track_location),
            selectinload(Test.planned_runs),
        )
        .execution_options(populate_existing=True)
    )
    if test is None:
        raise NotFoundError("test", test_id)
    return test


def list_tests(session: Session, query: TestListQuery) -> PageResult:
    statement = select(Test)
    filters = {
        Test.season_id: query.season_id,
        Test.vehicle_id: query.vehicle_id,
        Test.track_location_id: query.track_location_id,
        Test.status: query.status,
    }
    for column, value in filters.items():
        if value is not None:
            statement = statement.where(column == value)
    if query.date_from is not None:
        statement = statement.where(Test.test_date >= query.date_from)
    if query.date_to is not None:
        statement = statement.where(Test.test_date <= query.date_to)
    return paginate(session, statement, query, TEST_ORDER)


# --- Planned runs ---------------------------------------------------------------


def create_planned_run(session: Session, test_id: int, data: PlannedRunCreate) -> PlannedRun:
    test = get_or_404(session, Test, test_id, "test")
    _validate_planned_run_references(session, test, data)
    planned_run = PlannedRun(test_id=test.id, **data.model_dump())
    session.add(planned_run)
    session.flush()
    return planned_run


def get_planned_run(session: Session, planned_run_id: int) -> PlannedRun:
    return get_or_404(session, PlannedRun, planned_run_id, "planned_run")


def list_planned_runs(session: Session, test_id: int, page: PageQuery) -> PageResult:
    get_or_404(session, Test, test_id, "test")
    statement = select(PlannedRun).where(PlannedRun.test_id == test_id)
    return paginate(session, statement, page, PLANNED_RUN_ORDER)


# --- Actual runs ----------------------------------------------------------------


def create_run(session: Session, test_id: int, data: RunCreate) -> Run:
    test = get_or_404(session, Test, test_id, "test")
    if data.planned_run_id is not None:
        planned_run = get_referenced(
            session, PlannedRun, data.planned_run_id, "planned_run", "planned_run_id"
        )
        if planned_run.test_id != test.id:
            raise DomainValidationError.for_field(
                "planned_run_not_in_test",
                "planned_run_id",
                f"Planned run {data.planned_run_id} belongs to a different test.",
            )
    get_referenced(session, Driver, data.driver_id, "driver", "driver_id")
    _layout_at_test_location(session, test, data.track_layout_id, "track_layout_id")
    if data.setup_snapshot_id is not None:
        _setup_for_test_vehicle(session, test, data.setup_snapshot_id, "setup_snapshot_id")

    run = Run(test_id=test.id, **data.model_dump())
    session.add(run)
    session.flush()
    return get_run(session, run.id)


def get_run(session: Session, run_id: int) -> Run:
    run = session.scalar(
        select(Run)
        .where(Run.id == run_id)
        .options(joinedload(Run.driver), joinedload(Run.track_layout))
    )
    if run is None:
        raise NotFoundError("run", run_id)
    return run


def list_runs(session: Session, test_id: int, page: PageQuery) -> PageResult:
    get_or_404(session, Test, test_id, "test")
    statement = select(Run).where(Run.test_id == test_id)
    return paginate(session, statement, page, RUN_ORDER)
