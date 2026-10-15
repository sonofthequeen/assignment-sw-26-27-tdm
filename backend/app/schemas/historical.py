"""Historical run search and narrow analytics (read models)."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models import ActivityType, ConditionsSource, TestStatus, TrackState, Weather
from app.schemas.common import Id, PageQuery, RequestModel
from app.schemas.conditions import TemperatureC
from app.schemas.testing import (
    DriverRef,
    SeasonRef,
    TrackLayoutRef,
    TrackLocationRef,
    VehicleRef,
)

# --- Filters --------------------------------------------------------------------


class RunFilters(RequestModel):
    """Filters shared by run search and lap analytics. Every supplied filter is ANDed.

    Dates refer to the test day (test_date) and are inclusive. Temperature bounds are
    inclusive; when any is given, runs without that recorded temperature are excluded.
    """

    season_id: Id | None = None
    vehicle_id: Id | None = None
    driver_id: Id | None = None
    track_location_id: Id | None = None
    track_layout_id: Id | None = None
    activity_type: ActivityType | None = None
    date_from: date | None = Field(None, description="Inclusive lower bound on test_date.")
    date_to: date | None = Field(None, description="Inclusive upper bound on test_date.")
    ambient_temperature_min_c: TemperatureC | None = None
    ambient_temperature_max_c: TemperatureC | None = None
    asphalt_temperature_min_c: TemperatureC | None = None
    asphalt_temperature_max_c: TemperatureC | None = None
    tire_compound_id: Id | None = Field(
        None, description="Runs with at least one fitted tyre of this compound."
    )


class RunSearchQuery(PageQuery, RunFilters):
    planned_run_id: Id | None = Field(None, description="Only actual attempts of this plan.")
    has_plan: bool | None = Field(
        None, description="true: planned runs only; false: unexpected runs only."
    )
    test_status: TestStatus | None = None


class FastestLapQuery(PageQuery, RunFilters):
    """Requires track_layout_id or activity_type: lap times are only comparable per layout."""


# --- Results --------------------------------------------------------------------


class TestRef(BaseModel):
    __test__ = False

    id: int
    test_date: date
    status: TestStatus
    title: str | None


class ConditionsSummary(BaseModel):
    ambient_temperature_c: Decimal | None
    asphalt_temperature_c: Decimal | None
    conditions_source: ConditionsSource | None
    weather: Weather | None
    track_state: TrackState | None


class FastestLapSummary(BaseModel):
    lap_id: int
    lap_number: int
    raw_time_ms: int
    penalty_duration_ms: int
    effective_time_ms: int


class HistoricalRunSummary(BaseModel):
    id: int
    run_number: int
    test: TestRef
    season: SeasonRef
    vehicle: VehicleRef
    driver: DriverRef
    track_location: TrackLocationRef
    track_layout: TrackLayoutRef
    planned_run_id: int | None
    unexpected: bool
    setup_snapshot_id: int | None
    started_at: datetime | None
    conditions: ConditionsSummary | None = Field(description="Null when none are recorded.")
    recorded_lap_count: int
    physically_completed_lap_count: int
    fastest_lap: FastestLapSummary | None = Field(description="Null when no lap is eligible.")
    distance_m: Decimal = Field(description="Physically completed laps x verified length.")


class RankedLap(BaseModel):
    rank: int = Field(description="1-based position in the full filtered ranking.")
    lap_id: int
    lap_number: int
    raw_time_ms: int
    penalty_duration_ms: int
    effective_time_ms: int
    run_id: int
    run_number: int
    test: TestRef
    season: SeasonRef
    vehicle: VehicleRef
    driver: DriverRef
    track_layout: TrackLayoutRef
    conditions: ConditionsSummary | None
    setup_snapshot_id: int | None


# --- Test plan-vs-actual summary ---------------------------------------------------


class AttemptSummary(BaseModel):
    run_id: int
    run_number: int
    deviation_reason: str | None
    recorded_lap_count: int
    physically_completed_lap_count: int
    fastest_effective_time_ms: int | None
    differing_aspects: list[str] = Field(
        description="Aspects compared as DIFFERENT or TARGET_MISSED (full detail: plan-comparison)."
    )


class PlanOutcome(BaseModel):
    planned_run_id: int
    sequence_number: int
    status: str
    category: str = Field(description="EXECUTED, NOT_EXECUTED, CANCELLED or REPLACED.")
    cancellation_reason: str | None
    replacement_reason: str | None
    replaced_by_planned_run_id: int | None
    attempt_count: int
    repeated: bool = Field(description="More than one actual attempt.")
    attempts: list[AttemptSummary]


class PlanVsActualCounts(BaseModel):
    planned_runs: int
    executed: int
    not_executed: int
    cancelled: int
    replaced: int
    with_repeated_attempts: int
    actual_runs: int
    unexpected_runs: int


class TestPlanVsActual(BaseModel):
    __test__ = False

    test_id: int
    counts: PlanVsActualCounts
    planned_runs: list[PlanOutcome]
    unexpected_runs: list[AttemptSummary]
