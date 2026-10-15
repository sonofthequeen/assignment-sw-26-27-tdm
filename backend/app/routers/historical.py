"""Read-only historical queries: run search, fastest-lap ranking, test plan-vs-actual."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import IdPath, SessionDep
from app.queries import historical_runs, plan_vs_actual
from app.schemas.common import Page, error_responses
from app.schemas.historical import (
    FastestLapQuery,
    HistoricalRunSummary,
    RankedLap,
    RunSearchQuery,
    TestPlanVsActual,
)

router = APIRouter()


def _page(result) -> dict:
    return {
        "items": result.items,
        "limit": result.limit,
        "offset": result.offset,
        "total": result.total,
        "order_by": result.order_by,
    }


@router.get(
    "/runs",
    tags=["runs"],
    summary="Historical run search (all filters combined with AND)",
)
def search_runs(
    session: SessionDep, query: Annotated[RunSearchQuery, Query()]
) -> Page[HistoricalRunSummary]:
    return Page[HistoricalRunSummary](**_page(historical_runs.search_runs(session, query)))


@router.get(
    "/analytics/fastest-laps",
    tags=["analytics"],
    summary="Fastest eligible laps for a layout or activity, ranked by effective time",
)
def fastest_laps(
    session: SessionDep, query: Annotated[FastestLapQuery, Query()]
) -> Page[RankedLap]:
    return Page[RankedLap](**_page(historical_runs.rank_fastest_laps(session, query)))


@router.get(
    "/tests/{test_id}/plan-vs-actual",
    tags=["tests"],
    summary="How a test's run plan was executed: attempts, cancellations, unexpected runs",
    responses=error_responses(404),
)
def test_plan_vs_actual(test_id: IdPath, session: SessionDep) -> TestPlanVsActual:
    return plan_vs_actual.summarize_test_plan(session, test_id)
