from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, PageQuery, error_responses
from app.schemas.planning import RunPlanComparison
from app.schemas.testing import (
    PlannedRunCancel,
    PlannedRunCreate,
    PlannedRunDetail,
    PlannedRunRead,
    PlannedRunReplace,
    PlannedRunReplacement,
    RunCreate,
    RunDetail,
    RunSummary,
    TestCreate,
    TestDetail,
    TestListQuery,
    TestSummary,
)
from app.services import planning
from app.services import testing as service

router = APIRouter()


@router.post(
    "/tests",
    tags=["tests"],
    status_code=status.HTTP_201_CREATED,
    summary="Create a test, optionally with its run plan (atomic)",
    responses=error_responses(409),
)
def create_test(data: TestCreate, session: SessionDep) -> TestDetail:
    return TestDetail.model_validate(service.create_test(session, data))


@router.get("/tests", tags=["tests"], summary="List tests (newest first) with filters")
def list_tests(session: SessionDep, query: Annotated[TestListQuery, Query()]) -> Page[TestSummary]:
    return page_of(service.list_tests(session, query), TestSummary)


@router.get(
    "/tests/{test_id}",
    tags=["tests"],
    summary="Get a test with its references and run plan",
    responses=error_responses(404),
)
def get_test(test_id: IdPath, session: SessionDep) -> TestDetail:
    return TestDetail.model_validate(service.get_test(session, test_id))


@router.post(
    "/tests/{test_id}/planned-runs",
    tags=["planned runs"],
    status_code=status.HTTP_201_CREATED,
    summary="Add a planned run to a test",
    responses=error_responses(404, 409),
)
def create_planned_run(
    test_id: IdPath, data: PlannedRunCreate, session: SessionDep
) -> PlannedRunRead:
    return PlannedRunRead.model_validate(service.create_planned_run(session, test_id, data))


@router.get(
    "/tests/{test_id}/planned-runs",
    tags=["planned runs"],
    summary="List a test's planned runs in sequence order",
    responses=error_responses(404),
)
def list_planned_runs(
    test_id: IdPath, session: SessionDep, page: Annotated[PageQuery, Query()]
) -> Page[PlannedRunRead]:
    return page_of(service.list_planned_runs(session, test_id, page), PlannedRunRead)


@router.get(
    "/planned-runs/{planned_run_id}",
    tags=["planned runs"],
    summary="Get a planned run",
    responses=error_responses(404),
)
def get_planned_run(planned_run_id: IdPath, session: SessionDep) -> PlannedRunDetail:
    return PlannedRunDetail.model_validate(planning.get_planned_run_detail(session, planned_run_id))


@router.post(
    "/planned-runs/{planned_run_id}/cancel",
    tags=["planned runs"],
    summary="Cancel a planned run (kept for history, with its reason)",
    responses=error_responses(404, 409),
)
def cancel_planned_run(
    planned_run_id: IdPath, data: PlannedRunCancel, session: SessionDep
) -> PlannedRunDetail:
    plan = planning.cancel_planned_run(session, planned_run_id, data)
    return PlannedRunDetail.model_validate(plan)


@router.post(
    "/planned-runs/{planned_run_id}/replace",
    tags=["planned runs"],
    status_code=status.HTTP_201_CREATED,
    summary="Replace a planned run with a new plan in the same test (atomic)",
    responses=error_responses(404, 409),
)
def replace_planned_run(
    planned_run_id: IdPath, data: PlannedRunReplace, session: SessionDep
) -> PlannedRunReplacement:
    replaced, replacement = planning.replace_planned_run(session, planned_run_id, data)
    return PlannedRunReplacement(
        replaced=PlannedRunDetail.model_validate(replaced),
        replacement=PlannedRunDetail.model_validate(replacement),
    )


@router.post(
    "/planned-runs/{planned_run_id}/complete",
    tags=["planned runs"],
    summary="Mark a planned run as completed (requires at least one recorded actual run)",
    responses=error_responses(404, 409),
)
def complete_planned_run(planned_run_id: IdPath, session: SessionDep) -> PlannedRunDetail:
    return PlannedRunDetail.model_validate(planning.complete_planned_run(session, planned_run_id))


@router.post(
    "/tests/{test_id}/runs",
    tags=["runs"],
    status_code=status.HTTP_201_CREATED,
    summary="Record an actual run (planned_run_id = null for an unexpected run)",
    responses=error_responses(404, 409),
)
def create_run(test_id: IdPath, data: RunCreate, session: SessionDep) -> RunDetail:
    return RunDetail.model_validate(service.create_run(session, test_id, data))


@router.get(
    "/tests/{test_id}/runs",
    tags=["runs"],
    summary="List a test's actual runs in run-number order",
    responses=error_responses(404),
)
def list_runs(
    test_id: IdPath, session: SessionDep, page: Annotated[PageQuery, Query()]
) -> Page[RunSummary]:
    return page_of(service.list_runs(session, test_id, page), RunSummary)


@router.get(
    "/runs/{run_id}", tags=["runs"], summary="Get an actual run", responses=error_responses(404)
)
def get_run(run_id: IdPath, session: SessionDep) -> RunDetail:
    return RunDetail.model_validate(service.get_run(session, run_id))


@router.get(
    "/runs/{run_id}/plan-comparison",
    tags=["runs"],
    summary="Compare an actual run with its planned run",
    responses=error_responses(404),
)
def compare_run_with_plan(run_id: IdPath, session: SessionDep) -> RunPlanComparison:
    return planning.compare_run_with_plan(session, run_id)
