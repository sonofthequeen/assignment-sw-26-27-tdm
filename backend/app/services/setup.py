"""Setup snapshots: root creation, derivation and computed diffs.

Snapshots are append-only. There is no update or delete function here, and the
ORM guard in app.models.setup rejects mutation of persisted snapshots from any
code path. Diffs are computed from the two snapshots on demand and never stored,
so they cannot drift out of sync with the setup data.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.exceptions import DomainValidationError, NotFoundError
from app.models import Corner, SetupCornerParams, SetupSnapshot, Vehicle
from app.schemas.setup import (
    CORNER_FIELDS,
    CORNER_ORDER,
    VEHICLE_FIELDS,
    CornerFieldChange,
    DiffBaseline,
    SetupDiff,
    SetupSnapshotCreate,
    SetupSnapshotDerive,
    SetupSnapshotListQuery,
    VehicleFieldChange,
)
from app.services.lookup import get_referenced
from app.services.pagination import Ordering, PageResult, paginate

SNAPSHOT_ORDER = (
    Ordering("created_at desc", SetupSnapshot.created_at.desc()),
    Ordering("id desc", SetupSnapshot.id.desc()),
)


@dataclass(frozen=True)
class SetupValues:
    """The engineering content of a snapshot, without identity or metadata."""

    vehicle: dict
    corners: dict[Corner, dict]

    @classmethod
    def of(cls, snapshot: SetupSnapshot) -> "SetupValues":
        return cls(
            vehicle={f: getattr(snapshot, f) for f in VEHICLE_FIELDS},
            corners={c.corner: {f: getattr(c, f) for f in CORNER_FIELDS} for c in snapshot.corners},
        )


@dataclass(frozen=True)
class SetupComparison:
    vehicle_changes: list[VehicleFieldChange]
    corner_changes: list[CornerFieldChange]
    corners_added: list[Corner]
    corners_removed: list[Corner]

    @property
    def is_empty(self) -> bool:
        return not (
            self.vehicle_changes
            or self.corner_changes
            or self.corners_added
            or self.corners_removed
        )


def compare_setups(previous: SetupValues, current: SetupValues) -> SetupComparison:
    """Deterministic: vehicle fields in declaration order, corners FL, FR, RL, RR."""
    vehicle_changes = [
        VehicleFieldChange(field=f, previous=previous.vehicle[f], current=current.vehicle[f])
        for f in VEHICLE_FIELDS
        if previous.vehicle[f] != current.vehicle[f]
    ]
    corner_changes = [
        CornerFieldChange(
            corner=corner,
            field=f,
            previous=previous.corners[corner][f],
            current=current.corners[corner][f],
        )
        for corner in CORNER_ORDER
        if corner in previous.corners and corner in current.corners
        for f in CORNER_FIELDS
        if previous.corners[corner][f] != current.corners[corner][f]
    ]
    return SetupComparison(
        vehicle_changes=vehicle_changes,
        corner_changes=corner_changes,
        corners_added=[
            c for c in CORNER_ORDER if c in current.corners and c not in previous.corners
        ],
        corners_removed=[
            c for c in CORNER_ORDER if c in previous.corners and c not in current.corners
        ],
    )


# --- Commands -------------------------------------------------------------------


def create_setup_snapshot(session: Session, data: SetupSnapshotCreate) -> SetupSnapshot:
    get_referenced(session, Vehicle, data.vehicle_id, "vehicle", "vehicle_id")
    snapshot = SetupSnapshot(
        **data.model_dump(exclude={"corners"}),
        corners=[SetupCornerParams(**corner.model_dump()) for corner in data.corners],
    )
    session.add(snapshot)
    session.flush()
    return get_setup_snapshot(session, snapshot.id)


def derive_setup_snapshot(
    session: Session, source_id: int, data: SetupSnapshotDerive
) -> SetupSnapshot:
    """Creates a new snapshot from `source_id` plus the requested changes (source untouched)."""
    source = get_setup_snapshot(session, source_id)
    previous = SetupValues.of(source)

    vehicle = {**previous.vehicle, **data.vehicle_overrides()}
    corners = {corner: dict(values) for corner, values in previous.corners.items()}

    for index, corner in enumerate(data.remove_corners):
        if corner not in corners:
            raise DomainValidationError.for_field(
                "setup_corner_not_present",
                f"remove_corners.{index}",
                f"Corner {corner} has no values in snapshot {source_id}.",
            )
        del corners[corner]

    for index, change in enumerate(data.corners):
        merged = corners.get(change.corner, dict.fromkeys(CORNER_FIELDS))
        merged.update(change.model_dump(include=change.model_fields_set - {"corner"}))
        if all(value is None for value in merged.values()):
            raise DomainValidationError.for_field(
                "invalid_setup_value",
                f"corners.{index}",
                f"Corner {change.corner} would have no values; use remove_corners instead.",
            )
        corners[change.corner] = merged

    current = SetupValues(vehicle=vehicle, corners=corners)
    if compare_setups(previous, current).is_empty:
        raise DomainValidationError(
            code="setup_derivation_without_changes",
            message="The requested changes leave the setup identical to the source snapshot.",
        )

    derived = SetupSnapshot(
        vehicle_id=source.vehicle_id,
        based_on_snapshot_id=source.id,
        change_reason=data.change_reason,
        name=data.name,
        **vehicle,
        corners=[
            SetupCornerParams(corner=corner, **values)
            for corner, values in sorted(corners.items(), key=lambda i: CORNER_ORDER.index(i[0]))
        ],
    )
    session.add(derived)
    session.flush()
    return get_setup_snapshot(session, derived.id)


# --- Queries --------------------------------------------------------------------


def get_setup_snapshot(session: Session, snapshot_id: int) -> SetupSnapshot:
    snapshot = session.scalar(
        select(SetupSnapshot)
        .where(SetupSnapshot.id == snapshot_id)
        .options(
            joinedload(SetupSnapshot.vehicle),
            joinedload(SetupSnapshot.based_on),
            selectinload(SetupSnapshot.corners),
        )
        .execution_options(populate_existing=True)
    )
    if snapshot is None:
        raise NotFoundError("setup_snapshot", snapshot_id)
    return snapshot


def list_setup_snapshots(session: Session, query: SetupSnapshotListQuery) -> PageResult:
    statement = select(SetupSnapshot)
    if query.vehicle_id is not None:
        statement = statement.where(SetupSnapshot.vehicle_id == query.vehicle_id)
    if query.based_on_snapshot_id is not None:
        statement = statement.where(
            SetupSnapshot.based_on_snapshot_id == query.based_on_snapshot_id
        )
    return paginate(session, statement, query, SNAPSHOT_ORDER)


def diff_setup_snapshot(
    session: Session, snapshot_id: int, against_snapshot_id: int | None
) -> SetupDiff:
    current = get_setup_snapshot(session, snapshot_id)
    if against_snapshot_id is not None:
        get_referenced(
            session, SetupSnapshot, against_snapshot_id, "setup_snapshot", "against_snapshot_id"
        )
        baseline_snapshot = get_setup_snapshot(session, against_snapshot_id)
        if baseline_snapshot.vehicle_id != current.vehicle_id:
            # Parameters are only comparable within one vehicle (generations differ).
            raise DomainValidationError.for_field(
                "setup_snapshot_vehicle_mismatch",
                "against_snapshot_id",
                f"Setup snapshot {against_snapshot_id} belongs to a different vehicle.",
            )
        baseline = DiffBaseline.EXPLICIT
    elif current.based_on_snapshot_id is not None:
        baseline_snapshot = get_setup_snapshot(session, current.based_on_snapshot_id)
        baseline = DiffBaseline.BASED_ON
    else:
        return SetupDiff(
            setup_snapshot_id=current.id,
            against_snapshot_id=None,
            baseline=DiffBaseline.NONE,
            vehicle_changes=[],
            corner_changes=[],
            corners_added=[],
            corners_removed=[],
        )

    comparison = compare_setups(SetupValues.of(baseline_snapshot), SetupValues.of(current))
    return SetupDiff(
        setup_snapshot_id=current.id,
        against_snapshot_id=baseline_snapshot.id,
        baseline=baseline,
        vehicle_changes=comparison.vehicle_changes,
        corner_changes=comparison.corner_changes,
        corners_added=comparison.corners_added,
        corners_removed=comparison.corners_removed,
    )
