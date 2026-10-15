"""Planned-versus-actual comparison for one actual run."""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from app.models import PlannedRunStatus


class ComparisonStatus(StrEnum):
    MATCH = "MATCH"
    DIFFERENT = "DIFFERENT"
    NO_PLAN = "NO_PLAN"  # unexpected run: there is nothing to compare against
    NOT_PLANNED = "NOT_PLANNED"  # the plan set no expectation for this aspect
    ACTUAL_NOT_RECORDED = "ACTUAL_NOT_RECORDED"  # expectation exists, actual value unknown
    NOT_YET_SUPPORTED = "NOT_YET_SUPPORTED"  # the actual value is not modelled (energy)
    TARGET_MET = "TARGET_MET"  # fastest eligible effective lap <= target
    TARGET_MISSED = "TARGET_MISSED"  # fastest eligible effective lap > target


class ComparisonAspect(StrEnum):
    DRIVER = "driver_id"
    TRACK_LAYOUT = "track_layout_id"
    SETUP_SNAPSHOT = "setup_snapshot_id"
    CONTROL_MAP = "control_map"
    LAP_COUNT = "lap_count"
    TARGET_LAP_TIME = "target_lap_time_ms"
    ENERGY_LIMIT = "energy_limit_kwh"


ComparedValue = Decimal | int | str | None


class PlanComparisonItem(BaseModel):
    aspect: ComparisonAspect
    expected: ComparedValue
    actual: ComparedValue
    status: ComparisonStatus
    note: str | None = None


class RunPlanComparison(BaseModel):
    run_id: int
    test_id: int
    planned_run_id: int | None
    planned_run_status: PlannedRunStatus | None
    unexpected: bool
    deviation_reason: str | None
    recorded_lap_count: int
    physically_completed_lap_count: int
    fastest_eligible_lap_id: int | None
    items: list[PlanComparisonItem]
