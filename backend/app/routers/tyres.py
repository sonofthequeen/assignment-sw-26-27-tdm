"""Tyres, fitment and measurements. No PATCH/PUT/DELETE: history is append-only."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.dependencies import IdPath, SessionDep
from app.routers.pages import page_of
from app.schemas.common import Page, PageQuery, error_responses
from app.schemas.tyres import (
    AlignmentMeasurementBatchCreate,
    AlignmentMeasurementRead,
    RunTireAssignmentBatchCreate,
    RunTireAssignmentRead,
    TireCompoundCreate,
    TireCompoundRead,
    TireCreate,
    TireListQuery,
    TireMeasurementBatchCreate,
    TireMeasurementRead,
    TireRead,
    TireSetCreate,
    TireSetDetail,
    TireSetListQuery,
    TireSetRead,
)
from app.services import tyres as service

router = APIRouter()
CREATED = {"status_code": status.HTTP_201_CREATED, "responses": error_responses(404, 409)}


@router.post("/tire-compounds", tags=["tyres"], summary="Create a tyre compound", **CREATED)
def create_compound(data: TireCompoundCreate, session: SessionDep) -> TireCompoundRead:
    return TireCompoundRead.model_validate(service.create_compound(session, data))


@router.get("/tire-compounds", tags=["tyres"], summary="List tyre compounds")
def list_compounds(
    session: SessionDep, page: Annotated[PageQuery, Query()]
) -> Page[TireCompoundRead]:
    return page_of(service.list_compounds(session, page), TireCompoundRead)


@router.get(
    "/tire-compounds/{compound_id}",
    tags=["tyres"],
    summary="Get a tyre compound",
    responses=error_responses(404),
)
def get_compound(compound_id: IdPath, session: SessionDep) -> TireCompoundRead:
    return TireCompoundRead.model_validate(service.get_compound(session, compound_id))


@router.post(
    "/tire-sets", tags=["tyres"], summary="Create a tyre set (optionally with its tyres)", **CREATED
)
def create_tire_set(data: TireSetCreate, session: SessionDep) -> TireSetDetail:
    return TireSetDetail.model_validate(service.create_tire_set(session, data))


@router.get("/tire-sets", tags=["tyres"], summary="List tyre sets (filter by compound)")
def list_tire_sets(
    session: SessionDep, query: Annotated[TireSetListQuery, Query()]
) -> Page[TireSetRead]:
    return page_of(service.list_tire_sets(session, query), TireSetRead)


@router.get(
    "/tire-sets/{tire_set_id}",
    tags=["tyres"],
    summary="Get a tyre set with its compound and tyres",
    responses=error_responses(404),
)
def get_tire_set(tire_set_id: IdPath, session: SessionDep) -> TireSetDetail:
    return TireSetDetail.model_validate(service.get_tire_set(session, tire_set_id))


@router.post("/tires", tags=["tyres"], summary="Register a physical tyre", **CREATED)
def create_tire(data: TireCreate, session: SessionDep) -> TireRead:
    return TireRead.model_validate(service.create_tire(session, data))


@router.get("/tires", tags=["tyres"], summary="List physical tyres")
def list_tires(session: SessionDep, query: Annotated[TireListQuery, Query()]) -> Page[TireRead]:
    return page_of(service.list_tires(session, query), TireRead)


@router.get(
    "/tires/{tire_id}",
    tags=["tyres"],
    summary="Get a physical tyre",
    responses=error_responses(404),
)
def get_tire(tire_id: IdPath, session: SessionDep) -> TireRead:
    return TireRead.model_validate(service.get_tire(session, tire_id))


@router.post(
    "/runs/{run_id}/tire-assignments",
    tags=["tyre fitment"],
    summary="Record which tyre was fitted at each corner (atomic, create-once)",
    **CREATED,
)
def assign_tires(
    run_id: IdPath, data: RunTireAssignmentBatchCreate, session: SessionDep
) -> list[RunTireAssignmentRead]:
    assignments = service.assign_tires(session, run_id, data)
    return [RunTireAssignmentRead.model_validate(a) for a in assignments]


@router.get(
    "/runs/{run_id}/tire-assignments",
    tags=["tyre fitment"],
    summary="Tyres fitted for a run (FL, FR, RL, RR)",
    responses=error_responses(404),
)
def list_assignments(run_id: IdPath, session: SessionDep) -> list[RunTireAssignmentRead]:
    return [
        RunTireAssignmentRead.model_validate(a) for a in service.list_assignments(session, run_id)
    ]


@router.post(
    "/runs/{run_id}/tire-measurements",
    tags=["measurements"],
    summary="Record pre/post-run tyre pressures and temperatures (atomic, create-once)",
    **CREATED,
)
def record_tire_measurements(
    run_id: IdPath, data: TireMeasurementBatchCreate, session: SessionDep
) -> list[TireMeasurementRead]:
    rows = service.record_tire_measurements(session, run_id, data)
    return [TireMeasurementRead.model_validate(row) for row in rows]


@router.get(
    "/runs/{run_id}/tire-measurements",
    tags=["measurements"],
    summary="Tyre measurements of a run (PRE_RUN then POST_RUN; FL, FR, RL, RR)",
    responses=error_responses(404),
)
def list_tire_measurements(run_id: IdPath, session: SessionDep) -> list[TireMeasurementRead]:
    rows = service.list_tire_measurements(session, run_id)
    return [TireMeasurementRead.model_validate(row) for row in rows]


@router.post(
    "/runs/{run_id}/alignment-measurements",
    tags=["measurements"],
    summary="Record pre/post-run camber and toe (atomic, create-once)",
    **CREATED,
)
def record_alignment_measurements(
    run_id: IdPath, data: AlignmentMeasurementBatchCreate, session: SessionDep
) -> list[AlignmentMeasurementRead]:
    rows = service.record_alignment_measurements(session, run_id, data)
    return [AlignmentMeasurementRead.model_validate(row) for row in rows]


@router.get(
    "/runs/{run_id}/alignment-measurements",
    tags=["measurements"],
    summary="Alignment measurements of a run (PRE_RUN then POST_RUN; FL, FR, RL, RR)",
    responses=error_responses(404),
)
def list_alignment_measurements(
    run_id: IdPath, session: SessionDep
) -> list[AlignmentMeasurementRead]:
    rows = service.list_alignment_measurements(session, run_id)
    return [AlignmentMeasurementRead.model_validate(row) for row in rows]
