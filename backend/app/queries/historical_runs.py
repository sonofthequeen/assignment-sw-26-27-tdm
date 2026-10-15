"""Historical run search and fastest-lap ranking (read-only).

Join strategy (identical for the count and the page, so totals always match):

    run JOIN test JOIN track_layout LEFT JOIN run_condition

Every join is to-one, so no run can appear twice. Laps are never joined into the
filter; lap statistics are fetched afterwards for the page's run ids only. A page
therefore costs a constant four statements (count, page with references, lap
counts, fastest lap), whatever its size.

A temperature bound compared with a LEFT-JOINed NULL is not true, so a run without
conditions (or without that temperature) is excluded exactly when that temperature
is filtered, and kept otherwise.
"""

from decimal import Decimal

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.exceptions import DomainValidationError, ErrorDetail
from app.models import Lap, Run, RunCondition, RunTireAssignment, Test, Tire, TrackLayout
from app.models.laps import FASTEST_LAP_ORDER
from app.schemas.historical import (
    ConditionsSummary,
    FastestLapQuery,
    FastestLapSummary,
    HistoricalRunSummary,
    RankedLap,
    RunFilters,
    RunSearchQuery,
    TestRef,
)
from app.schemas.testing import (
    DriverRef,
    SeasonRef,
    TrackLayoutRef,
    TrackLocationRef,
    VehicleRef,
)
from app.services.laps import EMPTY_LAP_SUMMARY, lap_summaries
from app.services.pagination import Ordering, PageResult

RUN_SEARCH_ORDER = (
    Ordering("test_date desc", Test.test_date.desc()),
    Ordering("run_number asc", Run.run_number.asc()),
    Ordering("id asc", Run.id.asc()),
)
FASTEST_LAP_LABELS = ["effective_time_ms asc", "raw_time_ms asc", "lap_number asc", "lap_id asc"]


# --- Validation -------------------------------------------------------------------


def _range_error(code: str, low_field: str, high_field: str) -> DomainValidationError:
    return DomainValidationError(
        code=code,
        message=f"{high_field} must not be lower than {low_field}.",
        details=[ErrorDetail(high_field, f"Must be greater than or equal to {low_field}.")],
    )


def validate_run_filters(filters: RunFilters) -> None:
    """Rejects inverted ranges instead of silently swapping or ignoring them."""
    ranges = (
        ("invalid_date_range", "date_from", "date_to"),
        (
            "invalid_ambient_temperature_range",
            "ambient_temperature_min_c",
            "ambient_temperature_max_c",
        ),
        (
            "invalid_asphalt_temperature_range",
            "asphalt_temperature_min_c",
            "asphalt_temperature_max_c",
        ),
    )
    for code, low_field, high_field in ranges:
        low, high = getattr(filters, low_field), getattr(filters, high_field)
        if low is not None and high is not None and high < low:
            raise _range_error(code, low_field, high_field)


def _filter_clauses(filters: RunFilters) -> list[ColumnElement]:
    equal = {
        Test.season_id: filters.season_id,
        Test.vehicle_id: filters.vehicle_id,
        Run.driver_id: filters.driver_id,
        Test.track_location_id: filters.track_location_id,
        Run.track_layout_id: filters.track_layout_id,
        TrackLayout.activity_type: filters.activity_type,
    }
    clauses = [column == value for column, value in equal.items() if value is not None]
    ambient, asphalt = RunCondition.ambient_temperature_c, RunCondition.asphalt_temperature_c
    bounds = (
        (Test.test_date, filters.date_from, filters.date_to),
        (ambient, filters.ambient_temperature_min_c, filters.ambient_temperature_max_c),
        (asphalt, filters.asphalt_temperature_min_c, filters.asphalt_temperature_max_c),
    )
    for column, low, high in bounds:
        if low is not None:
            clauses.append(column >= low)
        if high is not None:
            clauses.append(column <= high)
    if filters.tire_compound_id is not None:
        # Correlated EXISTS, not a join: four matching corners must not yield four rows.
        clauses.append(
            select(RunTireAssignment.run_id)
            .join(Tire, RunTireAssignment.tire_id == Tire.id)
            .where(
                RunTireAssignment.run_id == Run.id,
                Tire.compound_id == filters.tire_compound_id,
            )
            .exists()
        )
    return clauses


def _joined(statement: Select) -> Select:
    return (
        statement.join(Test, Run.test_id == Test.id)
        .join(TrackLayout, Run.track_layout_id == TrackLayout.id)
        .outerjoin(RunCondition, RunCondition.run_id == Run.id)
    )


# --- Run search ---------------------------------------------------------------------


def _search_clauses(query: RunSearchQuery) -> list[ColumnElement]:
    validate_run_filters(query)
    if query.has_plan is False and query.planned_run_id is not None:
        raise DomainValidationError(
            code="conflicting_plan_filters",
            message="has_plan=false (unexpected runs) cannot be combined with planned_run_id.",
            details=[ErrorDetail("planned_run_id", "Conflicts with has_plan=false.")],
        )
    clauses = _filter_clauses(query)
    if query.planned_run_id is not None:
        clauses.append(Run.planned_run_id == query.planned_run_id)
    if query.has_plan is True:
        clauses.append(Run.planned_run_id.is_not(None))
    elif query.has_plan is False:
        clauses.append(Run.planned_run_id.is_(None))
    if query.test_status is not None:
        clauses.append(Test.status == query.test_status)
    return clauses


def _conditions(condition: RunCondition | None) -> ConditionsSummary | None:
    if condition is None:
        return None
    return ConditionsSummary(
        ambient_temperature_c=condition.ambient_temperature_c,
        asphalt_temperature_c=condition.asphalt_temperature_c,
        conditions_source=condition.conditions_source,
        weather=condition.weather,
        track_state=condition.track_state,
    )


def search_runs(session: Session, query: RunSearchQuery) -> PageResult:
    clauses = _search_clauses(query)
    total = session.scalar(
        select(func.count()).select_from(_joined(select(Run.id)).where(*clauses).subquery())
    )
    runs = session.scalars(
        _joined(select(Run))
        .where(*clauses)
        .options(
            contains_eager(Run.test).joinedload(Test.season),
            contains_eager(Run.test).joinedload(Test.vehicle),
            contains_eager(Run.test).joinedload(Test.track_location),
            contains_eager(Run.track_layout),
            contains_eager(Run.condition),
            joinedload(Run.driver),
        )
        .order_by(*(o.clause for o in RUN_SEARCH_ORDER))
        .limit(query.limit)
        .offset(query.offset)
    ).all()
    summaries = lap_summaries(session, [run.id for run in runs])

    items = []
    for run in runs:
        laps = summaries.get(run.id, EMPTY_LAP_SUMMARY)
        fastest = laps.fastest_lap
        items.append(
            HistoricalRunSummary(
                id=run.id,
                run_number=run.run_number,
                test=TestRef.model_validate(run.test, from_attributes=True),
                season=SeasonRef.model_validate(run.test.season),
                vehicle=VehicleRef.model_validate(run.test.vehicle),
                driver=DriverRef.model_validate(run.driver),
                track_location=TrackLocationRef.model_validate(run.test.track_location),
                track_layout=TrackLayoutRef.model_validate(run.track_layout),
                planned_run_id=run.planned_run_id,
                unexpected=run.planned_run_id is None,
                setup_snapshot_id=run.setup_snapshot_id,
                started_at=run.started_at,
                conditions=_conditions(run.condition),
                recorded_lap_count=laps.recorded_lap_count,
                physically_completed_lap_count=laps.physically_completed_lap_count,
                fastest_lap=FastestLapSummary(
                    lap_id=fastest.id,
                    lap_number=fastest.lap_number,
                    raw_time_ms=fastest.raw_time_ms,
                    penalty_duration_ms=fastest.penalty_duration_ms,
                    effective_time_ms=fastest.effective_time_ms,
                )
                if fastest
                else None,
                # A run uses one layout, so its mileage is exact Decimal arithmetic.
                distance_m=(
                    Decimal(run.track_layout.verified_length_m)
                    * laps.physically_completed_lap_count
                ).quantize(Decimal("0.001")),
            )
        )
    return PageResult(
        items=items,
        total=total or 0,
        limit=query.limit,
        offset=query.offset,
        order_by=[o.label for o in RUN_SEARCH_ORDER],
    )


# --- Fastest-lap analytics ------------------------------------------------------------


def rank_fastest_laps(session: Session, query: FastestLapQuery) -> PageResult:
    """Eligible laps across runs, ranked with the Phase 5 policy (FASTEST_LAP_ORDER).

    A layout filter is required because times on different layouts are not
    comparable; activity_type alone is accepted for e.g. all skidpad layouts.
    """
    validate_run_filters(query)
    if query.track_layout_id is None and query.activity_type is None:
        raise DomainValidationError(
            code="invalid_search_filter",
            message="Fastest-lap rankings need track_layout_id or activity_type.",
            details=[ErrorDetail("track_layout_id", "Required unless activity_type is given.")],
        )
    clauses = [Lap.fastest_lap_eligible, *_filter_clauses(query)]
    laps_in_scope = _joined(select(Lap).join(Run, Lap.run_id == Run.id)).where(*clauses)
    total = session.scalar(select(func.count()).select_from(laps_in_scope.subquery()))
    laps = session.scalars(
        laps_in_scope.options(
            contains_eager(Lap.run).contains_eager(Run.test).joinedload(Test.season),
            contains_eager(Lap.run).contains_eager(Run.test).joinedload(Test.vehicle),
            contains_eager(Lap.run).contains_eager(Run.track_layout),
            contains_eager(Lap.run).contains_eager(Run.condition),
            contains_eager(Lap.run).joinedload(Run.driver),
        )
        .order_by(*FASTEST_LAP_ORDER)
        .limit(query.limit)
        .offset(query.offset)
    ).all()
    items = [
        RankedLap(
            rank=query.offset + position,
            lap_id=lap.id,
            lap_number=lap.lap_number,
            raw_time_ms=lap.raw_time_ms,
            penalty_duration_ms=lap.penalty_duration_ms,
            effective_time_ms=lap.effective_time_ms,
            run_id=lap.run.id,
            run_number=lap.run.run_number,
            test=TestRef.model_validate(lap.run.test, from_attributes=True),
            season=SeasonRef.model_validate(lap.run.test.season),
            vehicle=VehicleRef.model_validate(lap.run.test.vehicle),
            driver=DriverRef.model_validate(lap.run.driver),
            track_layout=TrackLayoutRef.model_validate(lap.run.track_layout),
            conditions=_conditions(lap.run.condition),
            setup_snapshot_id=lap.run.setup_snapshot_id,
        )
        for position, lap in enumerate(laps, start=1)
    ]
    return PageResult(
        items=items,
        total=total or 0,
        limit=query.limit,
        offset=query.offset,
        order_by=FASTEST_LAP_LABELS,
    )
