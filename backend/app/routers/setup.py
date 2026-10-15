"""Setup snapshot endpoints. Deliberately no PATCH/PUT/DELETE: snapshots are append-only."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, error_responses
from app.schemas.setup import (
    SetupDiff,
    SetupDiffQuery,
    SetupSnapshotCreate,
    SetupSnapshotDerive,
    SetupSnapshotDetail,
    SetupSnapshotListQuery,
    SetupSnapshotSummary,
)
from app.services import setup as service

router = APIRouter(prefix="/setup-snapshots", tags=["setup snapshots"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a root setup snapshot",
)
def create_setup_snapshot(data: SetupSnapshotCreate, session: SessionDep) -> SetupSnapshotDetail:
    return SetupSnapshotDetail.model_validate(service.create_setup_snapshot(session, data))


@router.get("", summary="List setup snapshots (newest first)")
def list_setup_snapshots(
    session: SessionDep, query: Annotated[SetupSnapshotListQuery, Query()]
) -> Page[SetupSnapshotSummary]:
    return page_of(service.list_setup_snapshots(session, query), SetupSnapshotSummary)


@router.get(
    "/{setup_snapshot_id}",
    summary="Get a setup snapshot with its corner values",
    responses=error_responses(404),
)
def get_setup_snapshot(setup_snapshot_id: IdPath, session: SessionDep) -> SetupSnapshotDetail:
    return SetupSnapshotDetail.model_validate(
        service.get_setup_snapshot(session, setup_snapshot_id)
    )


@router.post(
    "/{setup_snapshot_id}/derive",
    status_code=status.HTTP_201_CREATED,
    summary="Record a setup change as a new snapshot derived from this one",
    responses=error_responses(404),
)
def derive_setup_snapshot(
    setup_snapshot_id: IdPath, data: SetupSnapshotDerive, session: SessionDep
) -> SetupSnapshotDetail:
    derived = service.derive_setup_snapshot(session, setup_snapshot_id, data)
    return SetupSnapshotDetail.model_validate(derived)


@router.get(
    "/{setup_snapshot_id}/diff",
    summary="Compare a snapshot with its source or with another snapshot of the same vehicle",
    responses=error_responses(404),
)
def diff_setup_snapshot(
    setup_snapshot_id: IdPath, session: SessionDep, query: Annotated[SetupDiffQuery, Query()]
) -> SetupDiff:
    return service.diff_setup_snapshot(session, setup_snapshot_id, query.against_snapshot_id)
