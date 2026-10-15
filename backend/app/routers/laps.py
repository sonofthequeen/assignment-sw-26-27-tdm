"""Run conditions, laps and fastest lap. No PATCH/PUT/DELETE: lap history is append-only."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, PageQuery, error_responses
from app.schemas.conditions import RunConditionCreate, RunConditionRead
from app.schemas.laps import FastestLapResult, LapBatchResult, LapBulkCreate, LapCreate, LapRead
from app.services import conditions as condition_service
from app.services import laps as lap_service

router = APIRouter()


@router.post(
    "/runs/{run_id}/conditions",
    tags=["run conditions"],
    status_code=status.HTTP_201_CREATED,
    summary="Record a run's conditions (write-once)",
    responses=error_responses(404, 409),
)
def create_run_condition(
    run_id: IdPath, data: RunConditionCreate, session: SessionDep
) -> RunConditionRead:
    condition = condition_service.create_run_condition(session, run_id, data)
    return RunConditionRead.model_validate(condition)


@router.get(
    "/runs/{run_id}/conditions",
    tags=["run conditions"],
    summary="Get a run's conditions",
    responses=error_responses(404),
)
def get_run_condition(run_id: IdPath, session: SessionDep) -> RunConditionRead:
    return RunConditionRead.model_validate(condition_service.get_run_condition(session, run_id))


@router.post(
    "/runs/{run_id}/laps",
    tags=["laps"],
    status_code=status.HTTP_201_CREATED,
    summary="Record one lap",
    responses=error_responses(404, 409),
)
def create_lap(run_id: IdPath, data: LapCreate, session: SessionDep) -> LapRead:
    return LapRead.model_validate(lap_service.create_lap(session, run_id, data))


@router.post(
    "/runs/{run_id}/laps/bulk",
    tags=["laps"],
    status_code=status.HTTP_201_CREATED,
    summary="Record up to 500 laps atomically (all or nothing)",
    responses=error_responses(404, 409),
)
def create_laps(run_id: IdPath, data: LapBulkCreate, session: SessionDep) -> LapBatchResult:
    laps = lap_service.create_laps(session, run_id, data)
    return LapBatchResult(
        run_id=run_id,
        created_count=len(laps),
        laps=[LapRead.model_validate(lap) for lap in laps],
    )


@router.get(
    "/runs/{run_id}/laps",
    tags=["laps"],
    summary="List a run's laps in lap-number order",
    responses=error_responses(404),
)
def list_laps(
    run_id: IdPath, session: SessionDep, page: Annotated[PageQuery, Query()]
) -> Page[LapRead]:
    return page_of(lap_service.list_laps(session, run_id, page), LapRead)


@router.get("/laps/{lap_id}", tags=["laps"], summary="Get a lap", responses=error_responses(404))
def get_lap(lap_id: IdPath, session: SessionDep) -> LapRead:
    return LapRead.model_validate(lap_service.get_lap(session, lap_id))


@router.get(
    "/runs/{run_id}/fastest-lap",
    tags=["laps"],
    summary="Fastest eligible lap of a run (lap is null if none is eligible)",
    responses=error_responses(404),
)
def get_fastest_lap(run_id: IdPath, session: SessionDep) -> FastestLapResult:
    summary = lap_service.get_fastest_lap(session, run_id)
    return FastestLapResult(
        run_id=run_id,
        recorded_lap_count=summary.recorded_lap_count,
        eligible_lap_count=summary.eligible_lap_count,
        lap=LapRead.model_validate(summary.fastest_lap) if summary.fastest_lap else None,
    )
