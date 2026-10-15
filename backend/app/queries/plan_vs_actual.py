"""Test-level planned-versus-actual summary (read-only).

Reuses the per-run comparison rules (app.services.planning.build_run_comparison)
on data loaded in a fixed number of queries: plans, runs with their plans and
setups, and batched lap statistics. No query is issued per plan or per run.
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PlannedRun, PlannedRunStatus, Run, Test
from app.schemas.historical import (
    AttemptSummary,
    PlanOutcome,
    PlanVsActualCounts,
    TestPlanVsActual,
)
from app.schemas.planning import ComparisonStatus
from app.services.laps import EMPTY_LAP_SUMMARY, lap_summaries
from app.services.lookup import get_or_404
from app.services.planning import COMPARISON_LOAD_OPTIONS, build_run_comparison

DEVIATION_STATUSES = frozenset({ComparisonStatus.DIFFERENT, ComparisonStatus.TARGET_MISSED})


def _category(plan: PlannedRun, attempts: list[AttemptSummary]) -> str:
    if plan.status is PlannedRunStatus.CANCELLED:
        return "CANCELLED"
    if plan.status is PlannedRunStatus.REPLACED:
        return "REPLACED"
    return "EXECUTED" if attempts else "NOT_EXECUTED"


def summarize_test_plan(session: Session, test_id: int) -> TestPlanVsActual:
    get_or_404(session, Test, test_id, "test")
    plans = session.scalars(
        select(PlannedRun)
        .where(PlannedRun.test_id == test_id)
        .order_by(PlannedRun.sequence_number, PlannedRun.id)
    ).all()
    runs = session.scalars(
        select(Run)
        .where(Run.test_id == test_id)
        .options(*COMPARISON_LOAD_OPTIONS)
        .order_by(Run.run_number, Run.id)
    ).all()
    laps = lap_summaries(session, [run.id for run in runs])

    attempts_by_plan: dict[int | None, list[AttemptSummary]] = defaultdict(list)
    for run in runs:
        summary = laps.get(run.id, EMPTY_LAP_SUMMARY)
        comparison = build_run_comparison(run, summary)
        attempts_by_plan[run.planned_run_id].append(
            AttemptSummary(
                run_id=run.id,
                run_number=run.run_number,
                deviation_reason=run.deviation_reason,
                recorded_lap_count=summary.recorded_lap_count,
                physically_completed_lap_count=summary.physically_completed_lap_count,
                fastest_effective_time_ms=(
                    summary.fastest_lap.effective_time_ms if summary.fastest_lap else None
                ),
                differing_aspects=[
                    item.aspect for item in comparison.items if item.status in DEVIATION_STATUSES
                ],
            )
        )

    outcomes = []
    for plan in plans:
        attempts = attempts_by_plan.get(plan.id, [])
        outcomes.append(
            PlanOutcome(
                planned_run_id=plan.id,
                sequence_number=plan.sequence_number,
                status=plan.status,
                category=_category(plan, attempts),
                cancellation_reason=plan.cancellation_reason,
                replacement_reason=plan.replacement_reason,
                replaced_by_planned_run_id=plan.replaced_by_planned_run_id,
                attempt_count=len(attempts),
                repeated=len(attempts) > 1,
                attempts=attempts,
            )
        )
    unexpected = attempts_by_plan.get(None, [])
    categories = [outcome.category for outcome in outcomes]
    return TestPlanVsActual(
        test_id=test_id,
        counts=PlanVsActualCounts(
            planned_runs=len(outcomes),
            executed=categories.count("EXECUTED"),
            not_executed=categories.count("NOT_EXECUTED"),
            cancelled=categories.count("CANCELLED"),
            replaced=categories.count("REPLACED"),
            with_repeated_attempts=sum(outcome.repeated for outcome in outcomes),
            actual_runs=len(runs),
            unexpected_runs=len(unexpected),
        ),
        planned_runs=outcomes,
        unexpected_runs=unexpected,
    )
