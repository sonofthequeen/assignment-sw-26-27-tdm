from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

MILEAGE_POLICY = (
    "Each physically completed lap counts one full verified layout length, regardless of "
    "timing validity, penalties or classification. Incomplete laps count zero; partial "
    "distance is not modelled."
)


class MileageScope(StrEnum):
    RUN = "RUN"
    TEST = "TEST"
    SEASON = "SEASON"
    VEHICLE = "VEHICLE"
    DRIVER = "DRIVER"


class MileageResult(BaseModel):
    scope: MileageScope
    resource_id: int
    counted_lap_count: int = Field(description="Physically completed laps in scope.")
    contributing_run_count: int = Field(description="Runs with at least one counted lap.")
    distance_m: Decimal = Field(description="Exact, millimetre resolution (decimal string).")
    distance_km: Decimal
    policy: str = MILEAGE_POLICY
