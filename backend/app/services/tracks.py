from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TrackLayout, TrackLocation
from app.schemas.common import PageQuery
from app.schemas.tracks import TrackLayoutCreate, TrackLayoutListQuery, TrackLocationCreate
from app.services.lookup import get_or_404, get_referenced
from app.services.pagination import Ordering, PageResult, paginate

LOCATION_ORDER = (
    Ordering("name asc", TrackLocation.name.asc()),
    Ordering("id asc", TrackLocation.id.asc()),
)
LAYOUT_ORDER = (
    Ordering("name asc", TrackLayout.name.asc()),
    Ordering("id asc", TrackLayout.id.asc()),
)


def create_track_location(session: Session, data: TrackLocationCreate) -> TrackLocation:
    location = TrackLocation(**data.model_dump())
    session.add(location)
    session.flush()
    return location


def get_track_location(session: Session, location_id: int) -> TrackLocation:
    return get_or_404(session, TrackLocation, location_id, "track_location")


def list_track_locations(session: Session, page: PageQuery) -> PageResult:
    return paginate(session, select(TrackLocation), page, LOCATION_ORDER)


def create_track_layout(session: Session, data: TrackLayoutCreate) -> TrackLayout:
    get_referenced(
        session, TrackLocation, data.track_location_id, "track_location", "track_location_id"
    )
    layout = TrackLayout(**data.model_dump())
    session.add(layout)
    session.flush()
    return layout


def get_track_layout(session: Session, layout_id: int) -> TrackLayout:
    return get_or_404(session, TrackLayout, layout_id, "track_layout")


def list_track_layouts(session: Session, query: TrackLayoutListQuery) -> PageResult:
    statement = select(TrackLayout)
    if query.track_location_id is not None:
        statement = statement.where(TrackLayout.track_location_id == query.track_location_id)
    if query.activity_type is not None:
        statement = statement.where(TrackLayout.activity_type == query.activity_type)
    return paginate(session, statement, query, LAYOUT_ORDER)
