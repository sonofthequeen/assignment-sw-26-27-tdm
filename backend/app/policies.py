"""Engineering validation policy (not physical constants, not database constraints).

These values are deliberately application-level: they reject obviously impossible
or implausible input with clear errors, and can be changed here without a
migration. They are conservative so that genuine Formula Student data is never
rejected.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.models import ActivityType


@dataclass(frozen=True)
class ConditionLimits:
    """Accepted measured/estimated temperatures, degrees Celsius (inclusive)."""

    ambient_min_c: Decimal = Decimal("-30.0")
    ambient_max_c: Decimal = Decimal("60.0")
    asphalt_min_c: Decimal = Decimal("-30.0")
    asphalt_max_c: Decimal = Decimal("90.0")


def _default_speed_limits() -> dict[ActivityType, Decimal]:
    # Upper bounds on the *average* speed over one full layout, metres per second.
    # Formula Student cars top out around 30-35 m/s; average lap speeds are far lower
    # (skidpad ~11 m/s, acceleration ~25 m/s over 75 m, autocross/endurance ~15 m/s).
    # Each cap is well above any real average, so only impossible records are rejected.
    # No minimum speed is enforced: slow laps (traffic, yellow flags) are real data.
    return {
        ActivityType.SKIDPAD: Decimal("25"),
        ActivityType.ACCELERATION: Decimal("45"),
        ActivityType.AUTOCROSS: Decimal("40"),
        ActivityType.ENDURANCE: Decimal("40"),
        ActivityType.GENERIC_TESTING: Decimal("50"),
    }


@dataclass(frozen=True)
class LapPlausibility:
    max_average_speed_mps: dict[ActivityType, Decimal] = field(
        default_factory=_default_speed_limits
    )


@dataclass(frozen=True)
class LapIngestion:
    max_batch_size: int = 500


CONDITION_LIMITS = ConditionLimits()
LAP_PLAUSIBILITY = LapPlausibility()
LAP_INGESTION = LapIngestion()


@dataclass(frozen=True)
class TyreMeasurementLimits:
    """Plausibility for tyre and alignment measurements (inclusive).

    Pressure is gauge pressure. Formula Student slicks typically run 60-120 kPa;
    the 400 kPa cap (about 58 psi) is far above any real value and catches unit
    mix-ups such as millibar entered as kPa, without rejecting real data.
    Tyre surface temperatures cover a cold morning to an overheated tyre.
    Camber/toe bounds match the setup snapshot validation.
    """

    pressure_max_kpa: Decimal = Decimal("400.0")
    temperature_min_c: Decimal = Decimal("-30.0")
    temperature_max_c: Decimal = Decimal("150.0")
    camber_abs_max_deg: Decimal = Decimal("10")
    toe_abs_max_deg: Decimal = Decimal("5")


TYRE_MEASUREMENT_LIMITS = TyreMeasurementLimits()
