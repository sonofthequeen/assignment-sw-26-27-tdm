"""Setup snapshot schemas.

Plausibility bounds (camber, toe, RPM) are application policy, not database
constraints. Precision mirrors the NUMERIC(p, s) columns.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.models import Corner
from app.schemas.common import Id, LongText, PageQuery, RequestModel, ResponseModel, text
from app.schemas.testing import VehicleRef

PowerKw = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]
RpmLimit = Annotated[int, Field(gt=0, le=100_000)]
CamberDeg = Annotated[Decimal, Field(ge=-10, le=10, max_digits=5, decimal_places=2)]
ToeDeg = Annotated[Decimal, Field(ge=-5, le=5, max_digits=5, decimal_places=3)]
SpringRate = Annotated[Decimal, Field(gt=0, max_digits=7, decimal_places=2)]

VEHICLE_FIELDS = ("power_limit_kw", "rpm_limit_rpm", "torque_vectoring_mode", "control_map")
CORNER_FIELDS = ("static_camber_deg", "static_toe_deg", "spring_rate_n_per_mm")
CORNER_ORDER = tuple(Corner)  # FL, FR, RL, RR


def _unique_corners(corners: list[Corner], field: str) -> None:
    if len(corners) != len(set(corners)):
        raise ValueError(f"{field} must not repeat a corner")


# --- Requests -----------------------------------------------------------------


class SetupCornerValues(RequestModel):
    corner: Corner
    static_camber_deg: CamberDeg | None = Field(None, description="Negative = top inward.")
    static_toe_deg: ToeDeg | None = Field(None, description="Negative = toe-out.")
    spring_rate_n_per_mm: SpringRate | None = None

    @model_validator(mode="after")
    def _has_a_value(self):
        if all(getattr(self, f) is None for f in CORNER_FIELDS):
            raise ValueError("a corner entry must carry at least one value")
        return self


class SetupSnapshotCreate(RequestModel):
    """A root snapshot. Corners are optional: absent corners stay absent, never defaulted."""

    vehicle_id: Id
    name: text(120) | None = None
    power_limit_kw: PowerKw | None = None
    rpm_limit_rpm: RpmLimit | None = None
    torque_vectoring_mode: text(32) | None = None
    control_map: text(64) | None = None
    corners: list[SetupCornerValues] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _corners_unique(self):
        _unique_corners([c.corner for c in self.corners], "corners")
        return self


class SetupCornerChange(RequestModel):
    """Only the fields present are changed; an explicit null clears a value."""

    corner: Corner
    static_camber_deg: CamberDeg | None = None
    static_toe_deg: ToeDeg | None = None
    spring_rate_n_per_mm: SpringRate | None = None

    @model_validator(mode="after")
    def _changes_something(self):
        if not (self.model_fields_set - {"corner"}):
            raise ValueError("a corner change must set at least one field")
        return self


class SetupSnapshotDerive(RequestModel):
    """Derive a new snapshot from an existing one on the same vehicle.

    Vehicle-level fields that are omitted are copied from the source; fields that
    are present (including explicit null) override it. `name` is a label, not an
    engineering value, and is not inherited.
    """

    change_reason: LongText
    name: text(120) | None = None
    power_limit_kw: PowerKw | None = None
    rpm_limit_rpm: RpmLimit | None = None
    torque_vectoring_mode: text(32) | None = None
    control_map: text(64) | None = None
    corners: list[SetupCornerChange] = Field(default_factory=list, max_length=4)
    remove_corners: list[Corner] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _corner_sets_consistent(self):
        changed = [c.corner for c in self.corners]
        _unique_corners(changed, "corners")
        _unique_corners(self.remove_corners, "remove_corners")
        if set(changed) & set(self.remove_corners):
            raise ValueError("a corner cannot be both changed and removed")
        return self

    def vehicle_overrides(self) -> dict:
        return {f: getattr(self, f) for f in VEHICLE_FIELDS if f in self.model_fields_set}


class SetupSnapshotListQuery(PageQuery):
    vehicle_id: Id | None = None
    based_on_snapshot_id: Id | None = None


class SetupDiffQuery(RequestModel):
    against_snapshot_id: Id | None = Field(
        None, description="Baseline snapshot; defaults to the snapshot this one is based on."
    )


# --- Responses ----------------------------------------------------------------


class SetupCornerRead(ResponseModel):
    corner: Corner
    static_camber_deg: Decimal | None
    static_toe_deg: Decimal | None
    spring_rate_n_per_mm: Decimal | None


class SetupSnapshotRef(ResponseModel):
    id: int
    name: str | None
    created_at: datetime


class SetupSnapshotSummary(ResponseModel):
    id: int
    vehicle_id: int
    name: str | None
    based_on_snapshot_id: int | None
    change_reason: str | None
    created_at: datetime


class SetupSnapshotDetail(SetupSnapshotSummary):
    vehicle: VehicleRef
    based_on: SetupSnapshotRef | None
    power_limit_kw: Decimal | None
    rpm_limit_rpm: int | None
    torque_vectoring_mode: str | None
    control_map: str | None
    corners: list[SetupCornerRead]

    @field_validator("corners")
    @classmethod
    def _corner_order(cls, corners: list[SetupCornerRead]) -> list[SetupCornerRead]:
        return sorted(corners, key=lambda c: CORNER_ORDER.index(c.corner))

    @computed_field
    @property
    def is_derived(self) -> bool:
        return self.based_on_snapshot_id is not None

    @computed_field
    @property
    def missing_corners(self) -> list[Corner]:
        present = {c.corner for c in self.corners}
        return [corner for corner in CORNER_ORDER if corner not in present]


SetupValue = Decimal | int | str | None


class DiffBaseline(StrEnum):
    BASED_ON = "BASED_ON"  # compared with the snapshot it was derived from
    EXPLICIT = "EXPLICIT"  # compared with against_snapshot_id
    NONE = "NONE"  # root snapshot, no baseline requested


class VehicleFieldChange(BaseModel):
    field: str
    previous: SetupValue
    current: SetupValue


class CornerFieldChange(BaseModel):
    corner: Corner
    field: str
    previous: SetupValue
    current: SetupValue


class SetupDiff(BaseModel):
    setup_snapshot_id: int
    against_snapshot_id: int | None
    baseline: DiffBaseline
    vehicle_changes: list[VehicleFieldChange]
    corner_changes: list[CornerFieldChange]
    corners_added: list[Corner]
    corners_removed: list[Corner]

    @computed_field
    @property
    def has_changes(self) -> bool:
        return bool(
            self.vehicle_changes
            or self.corner_changes
            or self.corners_added
            or self.corners_removed
        )
