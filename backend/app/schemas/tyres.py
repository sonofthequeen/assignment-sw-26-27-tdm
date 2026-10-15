"""Tyre inventory, fitment and measurement schemas ("tire" = one physical tyre)."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from app.models import Corner, MeasurementPhase
from app.schemas.common import Id, LongText, PageQuery, RequestModel, ResponseModel, text

# Mirror NUMERIC(p, s); plausibility ranges are service-checked (app.policies).
PressureKpa = Annotated[Decimal, Field(gt=0, max_digits=4, decimal_places=1)]
TyreTemperatureC = Annotated[Decimal, Field(max_digits=4, decimal_places=1)]
CamberDeg = Annotated[Decimal, Field(max_digits=5, decimal_places=2)]
ToeDeg = Annotated[Decimal, Field(max_digits=5, decimal_places=3)]


def _unique(values: list, message: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(message)


# --- Inventory -----------------------------------------------------------------------


class TireCompoundCreate(RequestModel):
    manufacturer: text(80)
    name: text(80) = Field(description="Compound name or code, unique per manufacturer.")
    notes: LongText | None = None


class TireCompoundRead(ResponseModel):
    id: int
    manufacturer: str
    name: str
    notes: str | None


class TireInSetCreate(RequestModel):
    serial_number: text(64)
    notes: LongText | None = None


class TireSetCreate(RequestModel):
    set_code: text(32)
    compound_id: Id
    introduced_on: date | None = None
    notes: LongText | None = None
    tires: list[TireInSetCreate] = Field(
        default_factory=list,
        max_length=8,
        description="Optional physical tyres created atomically with the set.",
    )

    @model_validator(mode="after")
    def _unique_serials(self):
        _unique([t.serial_number for t in self.tires], "serial_number values must be unique")
        return self


class TireSetListQuery(PageQuery):
    compound_id: Id | None = None


class TireRef(ResponseModel):
    id: int
    serial_number: str


class TireSetRead(ResponseModel):
    id: int
    set_code: str
    compound_id: int
    introduced_on: date | None
    notes: str | None


class TireSetDetail(TireSetRead):
    compound: TireCompoundRead
    tires: list[TireRef]


class TireCreate(RequestModel):
    """A tyre in a set inherits the set's compound; a standalone tyre must name one."""

    serial_number: text(64) = Field(description="Globally unique physical identifier.")
    tire_set_id: Id | None = None
    compound_id: Id | None = None
    notes: LongText | None = None


class TireListQuery(PageQuery):
    tire_set_id: Id | None = None
    compound_id: Id | None = None
    serial_number: text(64) | None = Field(None, description="Exact match.")


class TireRead(ResponseModel):
    id: int
    serial_number: str
    compound_id: int
    tire_set_id: int | None
    notes: str | None
    compound: TireCompoundRead


# --- Fitment -----------------------------------------------------------------------------


class RunTireAssignmentCreate(RequestModel):
    corner: Corner
    tire_id: Id
    notes: LongText | None = None


class RunTireAssignmentBatchCreate(RequestModel):
    """Up to four corners, recorded together or not at all."""

    assignments: list[RunTireAssignmentCreate] = Field(max_length=4)


class RunTireAssignmentRead(ResponseModel):
    run_id: int
    corner: Corner
    tire_id: int
    notes: str | None
    tire: TireRead


# --- Measurements --------------------------------------------------------------------------


class TireMeasurementCreate(RequestModel):
    corner: Corner
    phase: MeasurementPhase
    pressure_kpa: PressureKpa | None = Field(None, description="Gauge pressure, kPa.")
    temperature_inner_c: TyreTemperatureC | None = None
    temperature_center_c: TyreTemperatureC | None = None
    temperature_outer_c: TyreTemperatureC | None = None
    notes: LongText | None = None

    def values(self) -> dict:
        return {
            f: getattr(self, f)
            for f in (
                "pressure_kpa",
                "temperature_inner_c",
                "temperature_center_c",
                "temperature_outer_c",
            )
        }


class TireMeasurementBatchCreate(RequestModel):
    measurements: list[TireMeasurementCreate] = Field(max_length=8)


class TireMeasurementRead(ResponseModel):
    id: int
    run_id: int
    corner: Corner
    phase: MeasurementPhase
    tire_id: int = Field(description="The physical tyre fitted at this corner for the run.")
    pressure_kpa: Decimal | None
    temperature_inner_c: Decimal | None
    temperature_center_c: Decimal | None
    temperature_outer_c: Decimal | None
    notes: str | None


class AlignmentMeasurementCreate(RequestModel):
    corner: Corner
    phase: MeasurementPhase
    camber_deg: CamberDeg | None = Field(None, description="Negative = top of wheel inward.")
    toe_deg: ToeDeg | None = Field(None, description="Negative = toe-out.")
    notes: LongText | None = None


class AlignmentMeasurementBatchCreate(RequestModel):
    measurements: list[AlignmentMeasurementCreate] = Field(max_length=8)


class AlignmentMeasurementRead(ResponseModel):
    id: int
    run_id: int
    corner: Corner
    phase: MeasurementPhase
    camber_deg: Decimal | None
    toe_deg: Decimal | None
    notes: str | None
