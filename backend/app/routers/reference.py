from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, PageQuery, error_responses
from app.schemas.reference import (
    DriverCreate,
    DriverRead,
    SeasonCreate,
    SeasonRead,
    VehicleCreate,
    VehicleRead,
)
from app.services import reference as service

router = APIRouter()


@router.post(
    "/seasons",
    tags=["seasons"],
    status_code=status.HTTP_201_CREATED,
    summary="Create a season",
    responses=error_responses(409),
)
def create_season(data: SeasonCreate, session: SessionDep) -> SeasonRead:
    return SeasonRead.model_validate(service.create_season(session, data))


@router.get("/seasons", tags=["seasons"], summary="List seasons")
def list_seasons(session: SessionDep, page: Annotated[PageQuery, Query()]) -> Page[SeasonRead]:
    return page_of(service.list_seasons(session, page), SeasonRead)


@router.get(
    "/seasons/{season_id}", tags=["seasons"], summary="Get a season", responses=error_responses(404)
)
def get_season(season_id: IdPath, session: SessionDep) -> SeasonRead:
    return SeasonRead.model_validate(service.get_season(session, season_id))


@router.post(
    "/vehicles",
    tags=["vehicles"],
    status_code=status.HTTP_201_CREATED,
    summary="Create a vehicle",
    responses=error_responses(409),
)
def create_vehicle(data: VehicleCreate, session: SessionDep) -> VehicleRead:
    return VehicleRead.model_validate(service.create_vehicle(session, data))


@router.get("/vehicles", tags=["vehicles"], summary="List vehicles")
def list_vehicles(session: SessionDep, page: Annotated[PageQuery, Query()]) -> Page[VehicleRead]:
    return page_of(service.list_vehicles(session, page), VehicleRead)


@router.get(
    "/vehicles/{vehicle_id}",
    tags=["vehicles"],
    summary="Get a vehicle",
    responses=error_responses(404),
)
def get_vehicle(vehicle_id: IdPath, session: SessionDep) -> VehicleRead:
    return VehicleRead.model_validate(service.get_vehicle(session, vehicle_id))


@router.post(
    "/drivers",
    tags=["drivers"],
    status_code=status.HTTP_201_CREATED,
    summary="Create a driver",
    responses=error_responses(409),
)
def create_driver(data: DriverCreate, session: SessionDep) -> DriverRead:
    return DriverRead.model_validate(service.create_driver(session, data))


@router.get("/drivers", tags=["drivers"], summary="List drivers")
def list_drivers(session: SessionDep, page: Annotated[PageQuery, Query()]) -> Page[DriverRead]:
    return page_of(service.list_drivers(session, page), DriverRead)


@router.get(
    "/drivers/{driver_id}", tags=["drivers"], summary="Get a driver", responses=error_responses(404)
)
def get_driver(driver_id: IdPath, session: SessionDep) -> DriverRead:
    return DriverRead.model_validate(service.get_driver(session, driver_id))
