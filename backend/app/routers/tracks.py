from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, PageQuery, error_responses
from app.schemas.tracks import (
    TrackLayoutCreate,
    TrackLayoutListQuery,
    TrackLayoutRead,
    TrackLocationCreate,
    TrackLocationRead,
)
from app.services import tracks as service

router = APIRouter(tags=["tracks"])


@router.post(
    "/track-locations",
    status_code=status.HTTP_201_CREATED,
    summary="Create a track location",
    responses=error_responses(409),
)
def create_track_location(data: TrackLocationCreate, session: SessionDep) -> TrackLocationRead:
    return TrackLocationRead.model_validate(service.create_track_location(session, data))


@router.get("/track-locations", summary="List track locations")
def list_track_locations(
    session: SessionDep, page: Annotated[PageQuery, Query()]
) -> Page[TrackLocationRead]:
    return page_of(service.list_track_locations(session, page), TrackLocationRead)


@router.get(
    "/track-locations/{location_id}",
    summary="Get a track location",
    responses=error_responses(404),
)
def get_track_location(location_id: IdPath, session: SessionDep) -> TrackLocationRead:
    return TrackLocationRead.model_validate(service.get_track_location(session, location_id))


@router.post(
    "/track-layouts",
    status_code=status.HTTP_201_CREATED,
    summary="Create a track layout with a verified lap length",
    responses=error_responses(409),
)
def create_track_layout(data: TrackLayoutCreate, session: SessionDep) -> TrackLayoutRead:
    return TrackLayoutRead.model_validate(service.create_track_layout(session, data))


@router.get("/track-layouts", summary="List track layouts (filter by location / activity type)")
def list_track_layouts(
    session: SessionDep, query: Annotated[TrackLayoutListQuery, Query()]
) -> Page[TrackLayoutRead]:
    return page_of(service.list_track_layouts(session, query), TrackLayoutRead)


@router.get(
    "/track-layouts/{layout_id}", summary="Get a track layout", responses=error_responses(404)
)
def get_track_layout(layout_id: IdPath, session: SessionDep) -> TrackLayoutRead:
    return TrackLayoutRead.model_validate(service.get_track_layout(session, layout_id))
