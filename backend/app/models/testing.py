"""Test (test day), planned runs and actual runs.

"Run" in this module always means an actual on-track run of the vehicle, never
a software process execution.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, str_enum


class TestStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlannedRunStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    MODIFIED = "MODIFIED"
    CANCELLED = "CANCELLED"
    REPLACED = "REPLACED"


class Test(Base):
    """A test day: the context hub for planned and actual runs.

    References the track *location* (per the brief); each run references the
    concrete layout driven. "Run layout belongs to the test's location" is a
    cross-row rule enforced in the service layer.
    """

    __test__ = False  # stop pytest from collecting this ORM class
    __tablename__ = "test"
    __table_args__ = (
        # Season test list / season filter in run search, ordered by date.
        Index(None, "season_id", "test_date"),
        # Vehicle history and "previous run of this vehicle" for setup diffs.
        Index(None, "vehicle_id", "test_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"))
    track_location_id: Mapped[int] = mapped_column(ForeignKey("track_location.id"))
    # Local calendar date of the test day (not a timestamp).
    test_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[TestStatus] = mapped_column(
        str_enum(TestStatus, "test_status"), default=TestStatus.PLANNED
    )
    problems_encountered: Mapped[str | None] = mapped_column(Text)
    engineering_conclusions: Mapped[str | None] = mapped_column(Text)

    season: Mapped["Season"] = relationship()  # noqa: F821
    vehicle: Mapped["Vehicle"] = relationship()  # noqa: F821
    track_location: Mapped["TrackLocation"] = relationship()  # noqa: F821
    planned_runs: Mapped[list["PlannedRun"]] = relationship(
        back_populates="test", order_by="PlannedRun.sequence_number"
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="test", order_by="Run.run_number")


class PlannedRun(Base):
    """The plan for one run, preserved unchanged after the test day.

    Actual outcomes never overwrite these values; comparison is derived by
    joining Run rows. Status transitions are enforced in the service layer;
    only row-local invariants are database constraints.
    """

    __tablename__ = "planned_run"
    __table_args__ = (
        UniqueConstraint("test_id", "sequence_number"),
        CheckConstraint("sequence_number > 0", name="sequence_number_positive"),
        CheckConstraint(
            "expected_lap_count IS NULL OR expected_lap_count > 0",
            name="expected_lap_count_positive",
        ),
        CheckConstraint(
            "target_lap_time_ms IS NULL OR target_lap_time_ms > 0",
            name="target_lap_time_positive",
        ),
        CheckConstraint(
            "expected_energy_limit_kwh IS NULL OR expected_energy_limit_kwh > 0",
            name="energy_limit_positive",
        ),
        CheckConstraint(
            "status <> 'CANCELLED' OR cancellation_reason IS NOT NULL",
            name="cancelled_requires_reason",
        ),
        CheckConstraint(
            "(status = 'REPLACED') = (replaced_by_planned_run_id IS NOT NULL)",
            name="replaced_iff_replacement",
        ),
        CheckConstraint(
            "replaced_by_planned_run_id IS NULL OR replaced_by_planned_run_id <> id",
            name="not_replaced_by_self",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("test.id"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[PlannedRunStatus] = mapped_column(
        str_enum(PlannedRunStatus, "planned_run_status"), default=PlannedRunStatus.PLANNED
    )
    expected_driver_id: Mapped[int | None] = mapped_column(ForeignKey("driver.id"))
    expected_track_layout_id: Mapped[int | None] = mapped_column(ForeignKey("track_layout.id"))
    expected_setup_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("setup_snapshot.id"))
    expected_lap_count: Mapped[int | None] = mapped_column(Integer)
    target_lap_time_ms: Mapped[int | None] = mapped_column(Integer)
    expected_energy_limit_kwh: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    expected_control_map: Mapped[str | None] = mapped_column(String(64))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    replaced_by_planned_run_id: Mapped[int | None] = mapped_column(ForeignKey("planned_run.id"))
    notes: Mapped[str | None] = mapped_column(Text)

    test: Mapped[Test] = relationship(back_populates="planned_runs")
    expected_driver: Mapped["Driver | None"] = relationship()  # noqa: F821
    expected_track_layout: Mapped["TrackLayout | None"] = relationship()  # noqa: F821
    expected_setup_snapshot: Mapped["SetupSnapshot | None"] = relationship()  # noqa: F821
    replaced_by: Mapped["PlannedRun | None"] = relationship(remote_side=[id])
    # One plan may have several actual attempts (retries, aborted attempts).
    runs: Mapped[list["Run"]] = relationship(back_populates="planned_run", order_by="Run.id")


class Run(Base):
    """An actual on-track run.

    Completed lap count, best lap and mileage are derived from Lap rows and the
    layout length; none of them is stored here.
    """

    __tablename__ = "run"
    __table_args__ = (
        UniqueConstraint("test_id", "run_number"),
        CheckConstraint("run_number > 0", name="run_number_positive"),
        CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
            name="time_order",
        ),
        # Driver filter in historical search; driver lifetime mileage.
        Index(None, "driver_id"),
        # Layout filter in historical search; fastest laps per layout.
        Index(None, "track_layout_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("test.id"))
    # NULL = unexpected run (not in the plan). Not unique: one plan, many attempts.
    planned_run_id: Mapped[int | None] = mapped_column(ForeignKey("planned_run.id"))
    run_number: Mapped[int] = mapped_column(Integer)
    driver_id: Mapped[int] = mapped_column(ForeignKey("driver.id"))
    track_layout_id: Mapped[int] = mapped_column(ForeignKey("track_layout.id"))
    # NULL = setup unknown (e.g. imported history); never invented.
    setup_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("setup_snapshot.id"))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deviation_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    test: Mapped[Test] = relationship(back_populates="runs")
    planned_run: Mapped[PlannedRun | None] = relationship(back_populates="runs")
    driver: Mapped["Driver"] = relationship()  # noqa: F821
    track_layout: Mapped["TrackLayout"] = relationship()  # noqa: F821
    setup_snapshot: Mapped["SetupSnapshot | None"] = relationship()  # noqa: F821
    condition: Mapped["RunCondition | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    laps: Mapped[list["Lap"]] = relationship(  # noqa: F821
        back_populates="run", order_by="Lap.lap_number", cascade="all, delete-orphan"
    )


class Weather(enum.StrEnum):
    CLEAR = "CLEAR"
    CLOUDY = "CLOUDY"
    OVERCAST = "OVERCAST"
    DRIZZLE = "DRIZZLE"
    RAIN = "RAIN"


class TrackState(enum.StrEnum):
    DRY = "DRY"
    DAMP = "DAMP"
    WET = "WET"


class ConditionsSource(enum.StrEnum):
    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"


class RunCondition(Base):
    """Conditions for one run (1:1). NULL means unavailable, never guessed.

    Temperature plausibility ranges are application-level validation policy,
    not database constraints.
    """

    __tablename__ = "run_condition"
    __table_args__ = (
        CheckConstraint(
            "conditions_source IS NOT NULL"
            " OR (ambient_temperature_c IS NULL AND asphalt_temperature_c IS NULL)",
            name="temperature_requires_source",
        ),
    )

    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), primary_key=True)
    ambient_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    asphalt_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    conditions_source: Mapped[ConditionsSource | None] = mapped_column(
        str_enum(ConditionsSource, "conditions_source")
    )
    weather: Mapped[Weather | None] = mapped_column(str_enum(Weather, "weather"))
    track_state: Mapped[TrackState | None] = mapped_column(str_enum(TrackState, "track_state"))
    notes: Mapped[str | None] = mapped_column(Text)

    run: Mapped[Run] = relationship(back_populates="condition")
