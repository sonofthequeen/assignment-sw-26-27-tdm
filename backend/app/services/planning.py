"""Planned-run lifecycle and planned-versus-actual comparison.

Transition policy (explicit commands only; no generic workflow engine):

    PLANNED / MODIFIED --cancel-->   CANCELLED   (reason required)
    PLANNED / MODIFIED --replace-->  REPLACED    (reason required; a new PLANNED plan is
                                                  created in the same test and linked)
    PLANNED / MODIFIED --complete--> COMPLETED   (requires >= 1 recorded actual run)

CANCELLED, REPLACED and COMPLETED are terminal. MODIFIED is accepted as a source
state (e.g. for imported history) but no command sets it: changing a plan before
execution is a replacement (the original stays intact), and deviations during
execution are derived by comparing runs with the plan, not stored as a status.

Completion is an explicit engineering decision because the run model records no
outcome: the existence of a run does not prove the plan was achieved.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.exceptions import ConflictError, ErrorDetail, NotFoundError
from app.models import PlannedRun, PlannedRunStatus, Run, SetupSnapshot
from app.schemas.planning import (
    ComparisonAspect,
    ComparisonStatus,
    PlanComparisonItem,
    RunPlanComparison,
)
from app.schemas.testing import PlannedRunCancel, PlannedRunReplace
from app.services.laps import RunLapSummary, summarize_run_laps
from app.services.setup import SetupValues, compare_setups
from app.services.testing import validate_planned_run_references

OPEN_STATUSES = frozenset({PlannedRunStatus.PLANNED, PlannedRunStatus.MODIFIED})

_TERMINAL_CODES = {
    PlannedRunStatus.CANCELLED: "planned_run_already_cancelled",
    PlannedRunStatus.REPLACED: "planned_run_already_replaced",
    PlannedRunStatus.COMPLETED: "planned_run_already_completed",
}


def _require_open(plan: PlannedRun, action: str) -> None:
    if plan.status not in OPEN_STATUSES:
        raise ConflictError(
            code=_TERMINAL_CODES.get(plan.status, "planned_run_state_conflict"),
            message=f"Planned run {plan.id} is {plan.status} and cannot be {action}.",
            details=[ErrorDetail("status", f"Current status is {plan.status}.")],
        )


def get_planned_run_detail(session: Session, planned_run_id: int) -> PlannedRun:
    plan = session.scalar(
        select(PlannedRun)
        .where(PlannedRun.id == planned_run_id)
        .options(selectinload(PlannedRun.runs), selectinload(PlannedRun.replaces))
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise NotFoundError("planned_run", planned_run_id)
    return plan


def cancel_planned_run(session: Session, planned_run_id: int, data: PlannedRunCancel) -> PlannedRun:
    plan = get_planned_run_detail(session, planned_run_id)
    _require_open(plan, "cancelled")
    plan.status = PlannedRunStatus.CANCELLED
    plan.cancellation_reason = data.cancellation_reason
    session.flush()
    return get_planned_run_detail(session, plan.id)


def replace_planned_run(
    session: Session, planned_run_id: int, data: PlannedRunReplace
) -> tuple[PlannedRun, PlannedRun]:
    """Atomic within the request transaction: new plan + status/link on the original."""
    original = get_planned_run_detail(session, planned_run_id)
    _require_open(original, "replaced")
    validate_planned_run_references(session, original.test, data.replacement, "replacement.")

    replacement = PlannedRun(test_id=original.test_id, **data.replacement.model_dump())
    session.add(replacement)
    session.flush()  # sequence-number uniqueness is checked here

    original.status = PlannedRunStatus.REPLACED
    original.replaced_by_planned_run_id = replacement.id
    original.replacement_reason = data.replacement_reason
    session.flush()
    return get_planned_run_detail(session, original.id), get_planned_run_detail(
        session, replacement.id
    )


def complete_planned_run(session: Session, planned_run_id: int) -> PlannedRun:
    plan = get_planned_run_detail(session, planned_run_id)
    _require_open(plan, "completed")
    if not plan.runs:
        raise ConflictError(
            code="planned_run_not_executed",
            message=f"Planned run {plan.id} has no recorded actual run and cannot be completed.",
        )
    plan.status = PlannedRunStatus.COMPLETED
    session.flush()
    return get_planned_run_detail(session, plan.id)


# --- Planned versus actual ------------------------------------------------------------


def _compare(expected, actual) -> ComparisonStatus:
    if expected is None:
        return ComparisonStatus.NOT_PLANNED
    if actual is None:
        return ComparisonStatus.ACTUAL_NOT_RECORDED
    return ComparisonStatus.MATCH if expected == actual else ComparisonStatus.DIFFERENT


def compare_run_with_plan(session: Session, run_id: int) -> RunPlanComparison:
    run = session.scalar(
        select(Run)
        .where(Run.id == run_id)
        .options(
            joinedload(Run.planned_run)
            .joinedload(PlannedRun.expected_setup_snapshot)
            .selectinload(SetupSnapshot.corners),
            joinedload(Run.setup_snapshot).selectinload(SetupSnapshot.corners),
        )
    )
    if run is None:
        raise NotFoundError("run", run_id)

    plan = run.planned_run
    actual_control_map = run.setup_snapshot.control_map if run.setup_snapshot else None
    laps = summarize_run_laps(session, run.id)
    fastest_ms = laps.fastest_lap.effective_time_ms if laps.fastest_lap else None

    if plan is None:
        actual_values = {
            ComparisonAspect.DRIVER: run.driver_id,
            ComparisonAspect.TRACK_LAYOUT: run.track_layout_id,
            ComparisonAspect.SETUP_SNAPSHOT: run.setup_snapshot_id,
            ComparisonAspect.CONTROL_MAP: actual_control_map,
            ComparisonAspect.LAP_COUNT: (
                laps.physically_completed_lap_count if laps.recorded_lap_count else None
            ),
            ComparisonAspect.TARGET_LAP_TIME: fastest_ms,
        }
        items = [
            PlanComparisonItem(
                aspect=aspect, expected=None, actual=value, status=ComparisonStatus.NO_PLAN
            )
            for aspect, value in actual_values.items()
        ]
    else:
        items = [
            PlanComparisonItem(
                aspect=ComparisonAspect.DRIVER,
                expected=plan.expected_driver_id,
                actual=run.driver_id,
                status=_compare(plan.expected_driver_id, run.driver_id),
            ),
            PlanComparisonItem(
                aspect=ComparisonAspect.TRACK_LAYOUT,
                expected=plan.expected_track_layout_id,
                actual=run.track_layout_id,
                status=_compare(plan.expected_track_layout_id, run.track_layout_id),
            ),
            _setup_item(plan, run),
            PlanComparisonItem(
                aspect=ComparisonAspect.CONTROL_MAP,
                expected=plan.expected_control_map,
                actual=actual_control_map,
                status=_compare(plan.expected_control_map, actual_control_map),
                note=None if run.setup_snapshot else "The run has no setup snapshot.",
            ),
            PlanComparisonItem(
                aspect=ComparisonAspect.ENERGY_LIMIT,
                expected=plan.expected_energy_limit_kwh,
                actual=None,
                status=(
                    ComparisonStatus.NOT_PLANNED
                    if plan.expected_energy_limit_kwh is None
                    else ComparisonStatus.NOT_YET_SUPPORTED
                ),
                note="Actual energy use is not modelled for runs.",
            ),
            _lap_count_item(plan, laps),
            _target_time_item(plan, laps, fastest_ms),
        ]

    return RunPlanComparison(
        run_id=run.id,
        test_id=run.test_id,
        planned_run_id=run.planned_run_id,
        planned_run_status=plan.status if plan else None,
        unexpected=plan is None,
        deviation_reason=run.deviation_reason,
        recorded_lap_count=laps.recorded_lap_count,
        physically_completed_lap_count=laps.physically_completed_lap_count,
        fastest_eligible_lap_id=laps.fastest_lap.id if laps.fastest_lap else None,
        items=items,
    )


def _lap_count_item(plan: PlannedRun, laps: RunLapSummary) -> PlanComparisonItem:
    """Expected lap count vs physically completed laps (not inferred from numbering)."""
    note = (
        f"{laps.recorded_lap_count} lap(s) recorded, "
        f"{laps.physically_completed_lap_count} physically completed."
    )
    if plan.expected_lap_count is None:
        status = ComparisonStatus.NOT_PLANNED
    elif laps.recorded_lap_count == 0:
        # No lap data yet: absence of records is not evidence of zero completed laps.
        status = ComparisonStatus.ACTUAL_NOT_RECORDED
    elif plan.expected_lap_count == laps.physically_completed_lap_count:
        status = ComparisonStatus.MATCH
    else:
        status = ComparisonStatus.DIFFERENT
    return PlanComparisonItem(
        aspect=ComparisonAspect.LAP_COUNT,
        expected=plan.expected_lap_count,
        actual=laps.physically_completed_lap_count if laps.recorded_lap_count else None,
        status=status,
        note=note,
    )


def _target_time_item(
    plan: PlannedRun, laps: RunLapSummary, fastest_ms: int | None
) -> PlanComparisonItem:
    """Target lap time vs the fastest *eligible* effective lap time (penalties included)."""
    target = plan.target_lap_time_ms
    note = None
    if target is None:
        status = ComparisonStatus.NOT_PLANNED
    elif fastest_ms is None:
        status = ComparisonStatus.ACTUAL_NOT_RECORDED
        note = "No eligible lap (timed, timing-valid, completed FLYING lap) is recorded."
    else:
        status = (
            ComparisonStatus.TARGET_MET if fastest_ms <= target else ComparisonStatus.TARGET_MISSED
        )
        note = f"Fastest eligible lap {laps.fastest_lap.lap_number}: {fastest_ms - target:+d} ms."
    return PlanComparisonItem(
        aspect=ComparisonAspect.TARGET_LAP_TIME,
        expected=target,
        actual=fastest_ms,
        status=status,
        note=note,
    )


def _setup_item(plan: PlannedRun, run: Run) -> PlanComparisonItem:
    expected, actual = plan.expected_setup_snapshot, run.setup_snapshot
    status = _compare(plan.expected_setup_snapshot_id, run.setup_snapshot_id)
    note = None
    if status is ComparisonStatus.DIFFERENT:
        comparison = compare_setups(SetupValues.of(expected), SetupValues.of(actual))
        if comparison.is_empty:
            # Different snapshot rows, identical engineering values.
            status = ComparisonStatus.MATCH
            note = "Different snapshot with identical setup values."
        else:
            note = (
                f"Setup differs; see /api/v1/setup-snapshots/{actual.id}/diff"
                f"?against_snapshot_id={expected.id}"
            )
    return PlanComparisonItem(
        aspect=ComparisonAspect.SETUP_SNAPSHOT,
        expected=plan.expected_setup_snapshot_id,
        actual=run.setup_snapshot_id,
        status=status,
        note=note,
    )
