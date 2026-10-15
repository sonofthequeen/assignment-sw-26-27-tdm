from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, PageQuery, error_responses
from app.schemas.testing import (
    PlannedRunCreate,
    PlannedRunRead,
    RunCreate,
    RunDetail,
    RunSummary,
    TestCreate,
    TestDetail,
    TestListQuery,
    TestSummary,
)
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
def get_planned_run(planned_run_id: IdPath, session: SessionDep) -> PlannedRunRead:
    return PlannedRunRead.model_validate(service.get_planned_run(session, planned_run_id))


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
