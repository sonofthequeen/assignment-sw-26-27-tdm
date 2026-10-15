from typing import Annotated

from pydantic import BaseModel, Field, StrictBool

from app.models import LapClassification
from app.schemas.common import (
    MAX_INT,
    DurationMs,
    LongText,
    PositiveCount,
    RequestModel,
    ResponseModel,
)

PenaltyMs = Annotated[int, Field(ge=0, le=MAX_INT)]


class LapCreate(RequestModel):
    """One lap of the run's layout.

    Consistency rules (checked by the service, backed by database constraints):
    - timing_valid = true needs raw_time_ms and no invalidation_reason;
    - timing_valid = false needs a non-blank invalidation_reason;
    - raw_time_ms = null (untimed) is only allowed with timing_valid = false.
    Booleans are strict: 1/"yes" are not accepted as true.
    """

    lap_number: PositiveCount
    lap_classification: LapClassification
    raw_time_ms: DurationMs | None = Field(None, description="Measured lap time; null if untimed.")
    penalty_duration_ms: PenaltyMs = Field(0, description="Added to raw time for ranking only.")
    timing_valid: StrictBool
    physically_completed: StrictBool = Field(
        description="True if the car completed one full traversal of the layout."
    )
    invalidation_reason: LongText | None = None


class LapBulkCreate(RequestModel):
    laps: list[LapCreate] = Field(description="All laps are stored, or none (max 500).")


class LapRead(ResponseModel):
    id: int
    run_id: int
    lap_number: int
    lap_classification: LapClassification
    raw_time_ms: int | None
    penalty_duration_ms: int
    effective_time_ms: int | None = Field(description="raw_time_ms + penalty_duration_ms.")
    timing_valid: bool
    physically_completed: bool
    invalidation_reason: str | None
    fastest_lap_eligible: bool
    counts_toward_mileage: bool


class LapBatchResult(BaseModel):
    run_id: int
    created_count: int
    laps: list[LapRead]


FASTEST_LAP_POLICY = (
    "Eligible: timing_valid, timed, physically_completed FLYING laps. "
    "Ranked by effective_time_ms, then raw_time_ms, lap_number, lap id (all ascending)."
)


class FastestLapResult(BaseModel):
    run_id: int
    recorded_lap_count: int
    eligible_lap_count: int
    lap: LapRead | None = Field(description="Null when the run has no eligible lap.")
    policy: str = FASTEST_LAP_POLICY
