"""Tyre inventory, per-run fitment and measurements.

Policy: fitment and measurements are append-only and create-once per
(run, corner[, phase]). There is no update or delete; corrections are deferred to
explicit correction records. Batch requests are all-or-nothing within the request
transaction. Uniqueness is enforced by the database (translated to 409); the
service pre-checks give field-level messages for the common cases.
"""

from collections import Counter
from decimal import Decimal

from sqlalchemy import case, select, tuple_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.exceptions import ConflictError, DomainValidationError, ErrorDetail, NotFoundError
from app.models import (
    AlignmentMeasurement,
    Corner,
    MeasurementPhase,
    Run,
    RunTireAssignment,
    Tire,
    TireCompound,
    TireMeasurement,
    TireSet,
)
from app.policies import TYRE_MEASUREMENT_LIMITS
from app.schemas.common import PageQuery
from app.schemas.tyres import (
    AlignmentMeasurementBatchCreate,
    RunTireAssignmentBatchCreate,
    TireCompoundCreate,
    TireCreate,
    TireListQuery,
    TireMeasurementBatchCreate,
    TireSetCreate,
    TireSetListQuery,
)
from app.services.lookup import get_or_404, get_referenced
from app.services.pagination import Ordering, PageResult, paginate

COMPOUND_ORDER = (
    Ordering("manufacturer asc", TireCompound.manufacturer.asc()),
    Ordering("name asc", TireCompound.name.asc()),
    Ordering("id asc", TireCompound.id.asc()),
)
SET_ORDER = (Ordering("set_code asc", TireSet.set_code.asc()), Ordering("id asc", TireSet.id.asc()))
TIRE_ORDER = (
    Ordering("serial_number asc", Tire.serial_number.asc()),
    Ordering("id asc", Tire.id.asc()),
)
CORNER_RANK = {corner: index for index, corner in enumerate(Corner)}
PHASE_RANK = {MeasurementPhase.PRE_RUN: 0, MeasurementPhase.POST_RUN: 1}


def _corner_order(column):
    return case(CORNER_RANK, value=column)


def _phase_order(column):
    return case(PHASE_RANK, value=column)


# --- Compounds, sets, tyres ------------------------------------------------------------


def create_compound(session: Session, data: TireCompoundCreate) -> TireCompound:
    compound = TireCompound(**data.model_dump())
    session.add(compound)
    session.flush()
    return compound


def get_compound(session: Session, compound_id: int) -> TireCompound:
    return get_or_404(session, TireCompound, compound_id, "tire_compound")


def list_compounds(session: Session, page: PageQuery) -> PageResult:
    return paginate(session, select(TireCompound), page, COMPOUND_ORDER)


def create_tire_set(session: Session, data: TireSetCreate) -> TireSet:
    """The set and any listed tyres are created together (the tyres take its compound)."""
    get_referenced(session, TireCompound, data.compound_id, "tire_compound", "compound_id")
    tire_set = TireSet(**data.model_dump(exclude={"tires"}))
    session.add(tire_set)
    session.flush()
    session.add_all(
        Tire(**tire.model_dump(), tire_set_id=tire_set.id, compound_id=tire_set.compound_id)
        for tire in data.tires
    )
    session.flush()
    return get_tire_set(session, tire_set.id)


def get_tire_set(session: Session, tire_set_id: int) -> TireSet:
    tire_set = session.scalar(
        select(TireSet)
        .where(TireSet.id == tire_set_id)
        .options(joinedload(TireSet.compound), selectinload(TireSet.tires))
        .execution_options(populate_existing=True)
    )
    if tire_set is None:
        raise NotFoundError("tire_set", tire_set_id)
    return tire_set


def list_tire_sets(session: Session, query: TireSetListQuery) -> PageResult:
    statement = select(TireSet)
    if query.compound_id is not None:
        statement = statement.where(TireSet.compound_id == query.compound_id)
    return paginate(session, statement, query, SET_ORDER)


def create_tire(session: Session, data: TireCreate) -> Tire:
    if data.tire_set_id is not None:
        tire_set = get_referenced(session, TireSet, data.tire_set_id, "tire_set", "tire_set_id")
        if data.compound_id is not None and data.compound_id != tire_set.compound_id:
            raise DomainValidationError.for_field(
                "tire_compound_mismatch",
                "compound_id",
                f"Tire set {tire_set.id} uses compound {tire_set.compound_id}; "
                "a tyre in a set always has the set's compound.",
            )
        compound_id = tire_set.compound_id
    elif data.compound_id is not None:
        get_referenced(session, TireCompound, data.compound_id, "tire_compound", "compound_id")
        compound_id = data.compound_id
    else:
        raise DomainValidationError.for_field(
            "tire_compound_required",
            "compound_id",
            "A tyre outside a set must name its compound.",
        )
    tire = Tire(
        serial_number=data.serial_number,
        tire_set_id=data.tire_set_id,
        compound_id=compound_id,
        notes=data.notes,
    )
    session.add(tire)
    session.flush()
    return get_tire(session, tire.id)


def get_tire(session: Session, tire_id: int) -> Tire:
    tire = session.scalar(select(Tire).where(Tire.id == tire_id).options(joinedload(Tire.compound)))
    if tire is None:
        raise NotFoundError("tire", tire_id)
    return tire


def list_tires(session: Session, query: TireListQuery) -> PageResult:
    statement = select(Tire).options(joinedload(Tire.compound))
    for column, value in (
        (Tire.tire_set_id, query.tire_set_id),
        (Tire.compound_id, query.compound_id),
        (Tire.serial_number, query.serial_number),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return paginate(session, statement, query, TIRE_ORDER)


# --- Fitment -----------------------------------------------------------------------------


def _in_batch_duplicates(values: list, field: str, label: str) -> list[ErrorDetail]:
    counts = Counter(values)
    return [
        ErrorDetail(field.format(index=i), f"{label} {value} repeats in the request.")
        for i, value in enumerate(values)
        if counts[value] > 1
    ]


def assign_tires(
    session: Session, run_id: int, data: RunTireAssignmentBatchCreate
) -> list[RunTireAssignment]:
    get_or_404(session, Run, run_id, "run")
    items = data.assignments
    if not items:
        raise DomainValidationError.for_field(
            "empty_tire_assignment_batch", "assignments", "Assign at least one corner."
        )
    checks = (
        ("duplicate_tire_corner", [a.corner for a in items], "corner", "Corner"),
        ("duplicate_tire_assignment", [a.tire_id for a in items], "tire_id", "Tire"),
    )
    for code, values, attribute, label in checks:
        field = "assignments.{index}." + attribute
        if duplicates := _in_batch_duplicates(values, field, label):
            raise DomainValidationError(
                code=code,
                message=f"{label} values must be unique in one request.",
                details=duplicates,
            )
    for index, item in enumerate(items):
        get_referenced(session, Tire, item.tire_id, "tire", f"assignments.{index}.tire_id")

    existing = session.scalars(
        select(RunTireAssignment).where(RunTireAssignment.run_id == run_id)
    ).all()
    taken_corners = {a.corner for a in existing}
    used_tires = {a.tire_id for a in existing}
    conflicts = [
        ErrorDetail(f"assignments.{i}.corner", f"Corner {a.corner} already has a tyre.")
        for i, a in enumerate(items)
        if a.corner in taken_corners
    ] + [
        ErrorDetail(f"assignments.{i}.tire_id", f"Tire {a.tire_id} is already fitted.")
        for i, a in enumerate(items)
        if a.tire_id in used_tires
    ]
    if conflicts:
        raise ConflictError(
            code="tire_assignment_conflict",
            message="Fitment is recorded once per corner and per tyre for a run.",
            details=conflicts,
        )

    session.add_all(RunTireAssignment(run_id=run_id, **item.model_dump()) for item in items)
    session.flush()
    return list_assignments(session, run_id)


def list_assignments(session: Session, run_id: int) -> list[RunTireAssignment]:
    get_or_404(session, Run, run_id, "run")
    return list(
        session.scalars(
            select(RunTireAssignment)
            .where(RunTireAssignment.run_id == run_id)
            .options(joinedload(RunTireAssignment.tire).joinedload(Tire.compound))
            .order_by(_corner_order(RunTireAssignment.corner))
        )
    )


# --- Measurements ------------------------------------------------------------------------


def _check_range(code, field, value, low, high, unit) -> None:
    if value is not None and not low <= value <= high:
        raise DomainValidationError.for_field(
            code,
            field,
            f"Value {value} {unit} is outside {low}..{high} {unit} (validation policy).",
        )


def _reject_duplicate_keys(items, prefix: str) -> None:
    keys = [(m.corner, m.phase) for m in items]
    counts = Counter(keys)
    duplicates = [
        ErrorDetail(f"{prefix}.{i}.phase", f"{corner} {phase} repeats in the request.")
        for i, (corner, phase) in enumerate(keys)
        if counts[(corner, phase)] > 1
    ]
    if duplicates:
        raise DomainValidationError(
            code="duplicate_measurement_in_batch",
            message="Each corner and phase may appear once per request.",
            details=duplicates,
        )


def _existing_keys(session: Session, model, run_id: int, items) -> set:
    return {
        (corner, phase)
        for corner, phase in session.execute(
            select(model.corner, model.phase).where(
                model.run_id == run_id,
                tuple_(model.corner, model.phase).in_([(m.corner, m.phase) for m in items]),
            )
        )
    }


def record_tire_measurements(
    session: Session, run_id: int, data: TireMeasurementBatchCreate
) -> list[TireMeasurement]:
    get_or_404(session, Run, run_id, "run")
    items = data.measurements
    if not items:
        raise DomainValidationError.for_field(
            "empty_measurement_batch", "measurements", "Provide at least one measurement."
        )
    _reject_duplicate_keys(items, "measurements")
    limits = TYRE_MEASUREMENT_LIMITS
    fitted = set(
        session.scalars(select(RunTireAssignment.corner).where(RunTireAssignment.run_id == run_id))
    )
    for index, item in enumerate(items):
        prefix = f"measurements.{index}."
        if all(value is None for value in item.values().values()):
            raise DomainValidationError.for_field(
                "invalid_tire_measurement", f"{prefix}pressure_kpa", "Provide at least one value."
            )
        _check_range(
            "invalid_tire_measurement", f"{prefix}pressure_kpa", item.pressure_kpa,
            Decimal("0.1"), limits.pressure_max_kpa, "kPa",
        )  # fmt: skip
        for field in ("temperature_inner_c", "temperature_center_c", "temperature_outer_c"):
            _check_range(
                "invalid_tire_measurement", f"{prefix}{field}", getattr(item, field),
                limits.temperature_min_c, limits.temperature_max_c, "°C",
            )  # fmt: skip
        if item.corner not in fitted:
            raise DomainValidationError.for_field(
                "tire_assignment_not_found",
                f"{prefix}corner",
                f"No tyre is fitted at {item.corner} for run {run_id}; assign one first.",
            )
    if existing := _existing_keys(session, TireMeasurement, run_id, items):
        raise ConflictError(
            code="tire_measurement_conflict",
            message="Tyre measurements are recorded once per corner and phase.",
            details=[
                ErrorDetail(f"measurements.{i}.phase", f"{m.corner} {m.phase} already exists.")
                for i, m in enumerate(items)
                if (m.corner, m.phase) in existing
            ],
        )
    session.add_all(TireMeasurement(run_id=run_id, **item.model_dump()) for item in items)
    session.flush()
    return list_tire_measurements(session, run_id)


def list_tire_measurements(session: Session, run_id: int) -> list[TireMeasurement]:
    get_or_404(session, Run, run_id, "run")
    return list(
        session.scalars(
            select(TireMeasurement)
            .where(TireMeasurement.run_id == run_id)
            .options(joinedload(TireMeasurement.assignment))
            .order_by(
                _phase_order(TireMeasurement.phase),
                _corner_order(TireMeasurement.corner),
                TireMeasurement.id,
            )
        )
    )


def record_alignment_measurements(
    session: Session, run_id: int, data: AlignmentMeasurementBatchCreate
) -> list[AlignmentMeasurement]:
    """Observed alignment around a run. Never touches the run's setup snapshot."""
    get_or_404(session, Run, run_id, "run")
    items = data.measurements
    if not items:
        raise DomainValidationError.for_field(
            "empty_measurement_batch", "measurements", "Provide at least one measurement."
        )
    _reject_duplicate_keys(items, "measurements")
    limits = TYRE_MEASUREMENT_LIMITS
    for index, item in enumerate(items):
        prefix = f"measurements.{index}."
        if item.camber_deg is None and item.toe_deg is None:
            raise DomainValidationError.for_field(
                "invalid_alignment_measurement",
                f"{prefix}camber_deg",
                "Provide camber_deg, toe_deg or both.",
            )
        _check_range(
            "invalid_alignment_measurement", f"{prefix}camber_deg", item.camber_deg,
            -limits.camber_abs_max_deg, limits.camber_abs_max_deg, "deg",
        )  # fmt: skip
        _check_range(
            "invalid_alignment_measurement", f"{prefix}toe_deg", item.toe_deg,
            -limits.toe_abs_max_deg, limits.toe_abs_max_deg, "deg",
        )  # fmt: skip
    if existing := _existing_keys(session, AlignmentMeasurement, run_id, items):
        raise ConflictError(
            code="alignment_measurement_conflict",
            message="Alignment is recorded once per corner and phase.",
            details=[
                ErrorDetail(f"measurements.{i}.phase", f"{m.corner} {m.phase} already exists.")
                for i, m in enumerate(items)
                if (m.corner, m.phase) in existing
            ],
        )
    session.add_all(AlignmentMeasurement(run_id=run_id, **item.model_dump()) for item in items)
    session.flush()
    return list_alignment_measurements(session, run_id)


def list_alignment_measurements(session: Session, run_id: int) -> list[AlignmentMeasurement]:
    get_or_404(session, Run, run_id, "run")
    return list(
        session.scalars(
            select(AlignmentMeasurement)
            .where(AlignmentMeasurement.run_id == run_id)
            .order_by(
                _phase_order(AlignmentMeasurement.phase),
                _corner_order(AlignmentMeasurement.corner),
                AlignmentMeasurement.id,
            )
        )
    )
