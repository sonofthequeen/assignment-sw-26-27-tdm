"""Importing this package registers every mapped table on Base.metadata (used by Alembic)."""

from app.models.base import Base, Corner
from app.models.laps import Lap, LapClassification
from app.models.reference import Driver, Season, Vehicle
from app.models.setup import SetupCornerParams, SetupSnapshot
from app.models.testing import (
    ConditionsSource,
    PlannedRun,
    PlannedRunStatus,
    Run,
    RunCondition,
    Test,
    TestStatus,
    TrackState,
    Weather,
)
from app.models.tracks import ActivityType, TrackLayout, TrackLocation

__all__ = [
    "ActivityType",
    "Base",
    "ConditionsSource",
    "Corner",
    "Driver",
    "Lap",
    "LapClassification",
    "PlannedRun",
    "PlannedRunStatus",
    "Run",
    "RunCondition",
    "Season",
    "SetupCornerParams",
    "SetupSnapshot",
    "Test",
    "TestStatus",
    "TrackLayout",
    "TrackLocation",
    "TrackState",
    "Vehicle",
    "Weather",
]
