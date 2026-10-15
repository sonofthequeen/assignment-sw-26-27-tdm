"""Schemas for tests, planned runs and actual runs ("run" = on-track run)."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from app.models import ActivityType, PlannedRunStatus, TestStatus
from app.schemas.common import (
    DurationMs,
    Id,
    LongText,
    PageQuery,
    PositiveCount,
    RequestModel,
    ResponseModel,
    UtcDateTime,
    text,
)

# Mirrors NUMERIC(6, 3): kilowatt-hours with watt-hour resolution.
EnergyKwh = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=3)]


# --- Planned runs -----------------------------------------------------------


class PlannedRunCreate(RequestModel):
    """A planned run always starts as PLANNED; status changes are explicit commands."""

    sequence_number: PositiveCount
    expected_driver_id: Id | None = None
    expected_track_layout_id: Id | None = None
    expected_setup_snapshot_id: Id | None = None
    expected_lap_count: PositiveCount | None = None
    target_lap_time_ms: DurationMs | None = None
    expected_energy_limit_kwh: EnergyKwh | None = None
    expected_control_map: text(64) | None = None
    notes: LongText | None = None


class PlannedRunRead(ResponseModel):
    id: int
    test_id: int
    sequence_number: int
    status: PlannedRunStatus
    expected_driver_id: int | None
    expected_track_layout_id: int | None
    expected_setup_snapshot_id: int | None
    expected_lap_count: int | None
    target_lap_time_ms: int | None
    expected_energy_limit_kwh: Decimal | None
    expected_control_map: str | None
    cancellation_reason: str | None
    replaced_by_planned_run_id: int | None
    notes: str | None


# --- Tests ------------------------------------------------------------------


class TestCreate(RequestModel):
    __test__ = False

    season_id: Id
    vehicle_id: Id
    track_location_id: Id
    test_date: date
    title: text(160) | None = None
    status: TestStatus = TestStatus.PLANNED
    problems_encountered: LongText | None = None
    engineering_conclusions: LongText | None = None
    planned_runs: list[PlannedRunCreate] = Field(
        default_factory=list,
        max_length=100,
        description="Optional run plan created atomically with the test.",
    )

    @model_validator(mode="after")
    def _unique_sequence_numbers(self):
        numbers = [p.sequence_number for p in self.planned_runs]
        if len(numbers) != len(set(numbers)):
            raise ValueError("planned_runs sequence_number values must be unique")
        return self


class SeasonRef(ResponseModel):
    id: int
    name: str


class VehicleRef(ResponseModel):
    id: int
    code: str
    name: str


class TrackLocationRef(ResponseModel):
    id: int
    name: str


class TestSummary(ResponseModel):
    __test__ = False

    id: int
    season_id: int
    vehicle_id: int
    track_location_id: int
    test_date: date
    title: str | None
    status: TestStatus


class TestDetail(TestSummary):
    season: SeasonRef
    vehicle: VehicleRef
    track_location: TrackLocationRef
    problems_encountered: str | None
    engineering_conclusions: str | None
    planned_runs: list[PlannedRunRead]


class TestListQuery(PageQuery):
    __test__ = False

    season_id: Id | None = None
    vehicle_id: Id | None = None
    track_location_id: Id | None = None
    date_from: date | None = Field(None, description="Inclusive lower bound on test_date.")
    date_to: date | None = Field(None, description="Inclusive upper bound on test_date.")
    status: TestStatus | None = None

    @model_validator(mode="after")
    def _date_range(self):
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        return self


# --- Actual runs ------------------------------------------------------------


class RunCreate(RequestModel):
    """planned_run_id = null records an unexpected run (not in the plan)."""

    run_number: PositiveCount
    planned_run_id: Id | None = None
    driver_id: Id
    track_layout_id: Id
    setup_snapshot_id: Id | None = None
    started_at: UtcDateTime | None = None
    ended_at: UtcDateTime | None = None
    deviation_reason: LongText | None = None
    notes: LongText | None = None

    @model_validator(mode="after")
    def _time_order(self):
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be before started_at")
        return self


class DriverRef(ResponseModel):
    id: int
    code: str
    full_name: str


class TrackLayoutRef(ResponseModel):
    id: int
    name: str
    activity_type: ActivityType
    verified_length_m: Decimal


class RunSummary(ResponseModel):
    id: int
    test_id: int
    planned_run_id: int | None
    run_number: int
    driver_id: int
    track_layout_id: int
    setup_snapshot_id: int | None
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None


class RunDetail(RunSummary):
    driver: DriverRef
    track_layout: TrackLayoutRef
    deviation_reason: str | None
    notes: str | None
