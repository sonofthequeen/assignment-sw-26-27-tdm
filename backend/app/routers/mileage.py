from fastapi import APIRouter

from app.dependencies import IdPath, SessionDep
from app.schemas.common import error_responses
from app.schemas.mileage import MileageResult, MileageScope
from app.services.mileage import get_mileage

router = APIRouter(tags=["mileage"], responses=error_responses(404))


@router.get("/runs/{run_id}/mileage", summary="Distance covered in a run")
def run_mileage(run_id: IdPath, session: SessionDep) -> MileageResult:
    return get_mileage(session, MileageScope.RUN, run_id)


@router.get("/tests/{test_id}/mileage", summary="Distance covered across a test's runs")
def test_mileage(test_id: IdPath, session: SessionDep) -> MileageResult:
    return get_mileage(session, MileageScope.TEST, test_id)


@router.get("/seasons/{season_id}/mileage", summary="Distance covered in a season")
def season_mileage(season_id: IdPath, session: SessionDep) -> MileageResult:
    return get_mileage(session, MileageScope.SEASON, season_id)


@router.get("/vehicles/{vehicle_id}/mileage", summary="Lifetime distance of a vehicle")
def vehicle_mileage(vehicle_id: IdPath, session: SessionDep) -> MileageResult:
    return get_mileage(session, MileageScope.VEHICLE, vehicle_id)


@router.get("/drivers/{driver_id}/mileage", summary="Lifetime distance of a driver")
def driver_mileage(driver_id: IdPath, session: SessionDep) -> MileageResult:
    return get_mileage(session, MileageScope.DRIVER, driver_id)
