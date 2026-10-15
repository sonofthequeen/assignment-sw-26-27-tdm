"""Derived mileage per run, test, season, vehicle and driver (never stored).

Query strategy: one grouped SQL query per request counts physically completed
laps per track layout within the scope (laps -> runs -> layouts, plus tests for
season/vehicle scopes). The per-layout counts are multiplied by the verified
length in Python with Decimal arithmetic. SQLite stores NUMERIC with REAL
affinity, so SUM(length) in SQL would accumulate binary floating point; the
number of distinct layouts is small, so this costs nothing.

Planned runs never contribute: only Lap rows of actual runs are counted, so
unexpected runs and repeated attempts count like any other run.
"""

from decimal import Decimal

from sqlalchemy import ColumnElement, distinct, func, select
from sqlalchemy.orm import Session

from app.models import Driver, Lap, Run, Season, Test, TrackLayout, Vehicle
from app.schemas.mileage import MileageResult, MileageScope
from app.services.lookup import get_or_404

MM = Decimal("0.001")
MICRO_KM = Decimal("0.000001")

_SCOPES = {
    MileageScope.RUN: (Run, "run", lambda rid: Run.id == rid, False),
    MileageScope.TEST: (Test, "test", lambda rid: Run.test_id == rid, False),
    MileageScope.SEASON: (Season, "season", lambda rid: Test.season_id == rid, True),
    MileageScope.VEHICLE: (Vehicle, "vehicle", lambda rid: Test.vehicle_id == rid, True),
    MileageScope.DRIVER: (Driver, "driver", lambda rid: Run.driver_id == rid, False),
}


def _counted_laps_per_layout(session: Session, condition: ColumnElement, join_test: bool):
    statement = (
        select(
            TrackLayout.verified_length_m,
            func.count(Lap.id),
            func.count(distinct(Run.id)),
        )
        .select_from(Lap)
        .join(Run, Lap.run_id == Run.id)
        .join(TrackLayout, Run.track_layout_id == TrackLayout.id)
        .where(Lap.counts_toward_mileage, condition)
        .group_by(TrackLayout.id, TrackLayout.verified_length_m)
        .order_by(TrackLayout.id)
    )
    if join_test:
        statement = statement.join(Test, Run.test_id == Test.id)
    return session.execute(statement).all()


def get_mileage(session: Session, scope: MileageScope, resource_id: int) -> MileageResult:
    model, resource, condition, join_test = _SCOPES[scope]
    get_or_404(session, model, resource_id, resource)

    rows = _counted_laps_per_layout(session, condition(resource_id), join_test)
    distance_m = sum((Decimal(length) * laps for length, laps, _ in rows), Decimal(0))
    # A run uses exactly one layout, so per-layout run counts never double count.
    return MileageResult(
        scope=scope,
        resource_id=resource_id,
        counted_lap_count=sum(laps for _, laps, _ in rows),
        contributing_run_count=sum(runs for _, _, runs in rows),
        distance_m=distance_m.quantize(MM),
        distance_km=(distance_m / 1000).quantize(MICRO_KM),
    )
