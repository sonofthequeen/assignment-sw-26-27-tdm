"""Seasons, vehicles and drivers.

Create and read only. Uniqueness is left to the database constraints (translated
to 409 by app.errors) rather than duplicated as racy pre-checks.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Driver, Season, Vehicle
from app.schemas.common import PageQuery
from app.schemas.reference import DriverCreate, SeasonCreate, VehicleCreate
from app.services.lookup import get_or_404
from app.services.pagination import Ordering, PageResult, paginate

SEASON_ORDER = (
    Ordering("starts_on asc nulls last", Season.starts_on.asc().nulls_last()),
    Ordering("id asc", Season.id.asc()),
)
VEHICLE_ORDER = (Ordering("code asc", Vehicle.code.asc()), Ordering("id asc", Vehicle.id.asc()))
DRIVER_ORDER = (Ordering("code asc", Driver.code.asc()), Ordering("id asc", Driver.id.asc()))


def create_season(session: Session, data: SeasonCreate) -> Season:
    season = Season(**data.model_dump())
    session.add(season)
    session.flush()
    return season


def get_season(session: Session, season_id: int) -> Season:
    return get_or_404(session, Season, season_id, "season")


def list_seasons(session: Session, page: PageQuery) -> PageResult:
    return paginate(session, select(Season), page, SEASON_ORDER)


def create_vehicle(session: Session, data: VehicleCreate) -> Vehicle:
    vehicle = Vehicle(**data.model_dump())
    session.add(vehicle)
    session.flush()
    return vehicle


def get_vehicle(session: Session, vehicle_id: int) -> Vehicle:
    return get_or_404(session, Vehicle, vehicle_id, "vehicle")


def list_vehicles(session: Session, page: PageQuery) -> PageResult:
    return paginate(session, select(Vehicle), page, VEHICLE_ORDER)


def create_driver(session: Session, data: DriverCreate) -> Driver:
    driver = Driver(**data.model_dump())
    session.add(driver)
    session.flush()
    return driver


def get_driver(session: Session, driver_id: int) -> Driver:
    return get_or_404(session, Driver, driver_id, "driver")


def list_drivers(session: Session, page: PageQuery) -> PageResult:
    return paginate(session, select(Driver), page, DRIVER_ORDER)
