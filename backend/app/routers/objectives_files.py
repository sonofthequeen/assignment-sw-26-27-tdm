"""Objective traceability and the telemetry/log file index. Create and read only."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, PageQuery, error_responses
from app.schemas.files import TelemetryFileCreate, TelemetryFileListQuery, TelemetryFileRead
from app.schemas.objectives import (
    ObjectiveLinkCreate,
    SeasonObjectiveCreate,
    SeasonObjectiveDetail,
    SeasonObjectiveRead,
)
from app.services import files as file_service
from app.services import objectives as objective_service

router = APIRouter()
CREATED = {"status_code": status.HTTP_201_CREATED, "responses": error_responses(404, 409)}


def _reads(objectives) -> list[SeasonObjectiveRead]:
    return [SeasonObjectiveRead.model_validate(o) for o in objectives]


@router.post(
    "/seasons/{season_id}/objectives",
    tags=["objectives"],
    summary="Create a season objective",
    **CREATED,
)
def create_objective(
    season_id: IdPath, data: SeasonObjectiveCreate, session: SessionDep
) -> SeasonObjectiveRead:
    objective = objective_service.create_objective(session, season_id, data)
    return SeasonObjectiveRead.model_validate(objective)


@router.get(
    "/seasons/{season_id}/objectives",
    tags=["objectives"],
    summary="List a season's objectives (CRITICAL first)",
    responses=error_responses(404),
)
def list_objectives(
    season_id: IdPath, session: SessionDep, page: Annotated[PageQuery, Query()]
) -> Page[SeasonObjectiveRead]:
    return page_of(objective_service.list_objectives(session, season_id, page), SeasonObjectiveRead)


@router.get(
    "/objectives/{objective_id}",
    tags=["objectives"],
    summary="Get an objective with derived progress",
    responses=error_responses(404),
)
def get_objective(objective_id: IdPath, session: SessionDep) -> SeasonObjectiveDetail:
    return objective_service.get_objective_detail(session, objective_id)


@router.post(
    "/tests/{test_id}/objectives",
    tags=["objectives"],
    summary="Link objectives of the test's season to the test (atomic)",
    **CREATED,
)
def link_test_objectives(
    test_id: IdPath, data: ObjectiveLinkCreate, session: SessionDep
) -> list[SeasonObjectiveRead]:
    return _reads(objective_service.link_test_objectives(session, test_id, data))


@router.get(
    "/tests/{test_id}/objectives",
    tags=["objectives"],
    summary="Objectives addressed by a test",
    responses=error_responses(404),
)
def list_test_objectives(test_id: IdPath, session: SessionDep) -> list[SeasonObjectiveRead]:
    return _reads(objective_service.list_test_objectives(session, test_id))


@router.post(
    "/runs/{run_id}/objectives",
    tags=["objectives"],
    summary="Link objectives of the run's season to an actual run (atomic)",
    **CREATED,
)
def link_run_objectives(
    run_id: IdPath, data: ObjectiveLinkCreate, session: SessionDep
) -> list[SeasonObjectiveRead]:
    return _reads(objective_service.link_run_objectives(session, run_id, data))


@router.get(
    "/runs/{run_id}/objectives",
    tags=["objectives"],
    summary="Objectives addressed by a run",
    responses=error_responses(404),
)
def list_run_objectives(run_id: IdPath, session: SessionDep) -> list[SeasonObjectiveRead]:
    return _reads(objective_service.list_run_objectives(session, run_id))


@router.post(
    "/tests/{test_id}/files",
    tags=["files"],
    summary="Index a telemetry/log file stored elsewhere (metadata only)",
    **CREATED,
)
def register_file(
    test_id: IdPath, data: TelemetryFileCreate, session: SessionDep
) -> TelemetryFileRead:
    return TelemetryFileRead.model_validate(file_service.register_file(session, test_id, data))


@router.get(
    "/tests/{test_id}/files",
    tags=["files"],
    summary="List a test's indexed files (newest first)",
    responses=error_responses(404),
)
def list_files(
    test_id: IdPath, session: SessionDep, query: Annotated[TelemetryFileListQuery, Query()]
) -> Page[TelemetryFileRead]:
    return page_of(file_service.list_files(session, test_id, query), TelemetryFileRead)


@router.get(
    "/files/{file_id}",
    tags=["files"],
    summary="Get an indexed file",
    responses=error_responses(404),
)
def get_file(file_id: IdPath, session: SessionDep) -> TelemetryFileRead:
    return TelemetryFileRead.model_validate(file_service.get_file(session, file_id))
