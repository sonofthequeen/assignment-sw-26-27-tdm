"""Tyre inventory, per-run fitment and pre/post-run measurements.

Naming: code, tables and API paths use "tire"; a Tire row is one physical tyre.
Units are part of column names (kPa gauge pressure, degrees Celsius, degrees).
"""

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Corner, str_enum


class MeasurementPhase(enum.StrEnum):
    PRE_RUN = "PRE_RUN"
    POST_RUN = "POST_RUN"


class TireCompound(Base):
    __tablename__ = "tire_compound"
    __table_args__ = (UniqueConstraint("manufacturer", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)


class TireSet(Base):
    """A physical set of tyres sharing one compound."""

    __tablename__ = "tire_set"
    __table_args__ = (
        # Target of tire's composite FK: lets the database guarantee that a tyre in a
        # set has the set's compound (no trigger, no duplicated source of truth).
        UniqueConstraint("id", "compound_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    set_code: Mapped[str] = mapped_column(String(32), unique=True)
    compound_id: Mapped[int] = mapped_column(ForeignKey("tire_compound.id"))
    introduced_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    compound: Mapped[TireCompound] = relationship()
    # Read-only navigation: tire_set_id/compound_id are written explicitly by the
    # service, so the ORM must not sync them through two overlapping paths.
    tires: Mapped[list["Tire"]] = relationship(
        primaryjoin="TireSet.id == foreign(Tire.tire_set_id)",
        order_by="Tire.serial_number",
        viewonly=True,
    )


class Tire(Base):
    """One physical tyre with a globally unique serial number.

    compound_id is always set, so runs are filterable by compound with one join.
    tire_set_id is optional (single spare tyres exist). When it is set, the
    composite FK (tire_set_id, compound_id) -> tire_set(id, compound_id) forces
    the tyre's compound to equal its set's compound. With tire_set_id NULL the
    composite FK is not checked (MATCH SIMPLE), and compound_id stands alone.
    """

    __tablename__ = "tire"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tire_set_id", "compound_id"], ["tire_set.id", "tire_set.compound_id"]
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(64), unique=True)
    compound_id: Mapped[int] = mapped_column(ForeignKey("tire_compound.id"))
    tire_set_id: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)

    compound: Mapped[TireCompound] = relationship()
    tire_set: Mapped[TireSet | None] = relationship(
        primaryjoin="foreign(Tire.tire_set_id) == TireSet.id", viewonly=True
    )


class RunTireAssignment(Base):
    """Which physical tyre was fitted at which corner for one actual run.

    PK (run_id, corner): one tyre per corner. UNIQUE (run_id, tire_id): one tyre
    cannot occupy two corners of the same run. The same tyre may be used on many
    runs. Fitment is recorded once; there is no update operation.
    """

    __tablename__ = "run_tire_assignment"
    __table_args__ = (UniqueConstraint("run_id", "tire_id"),)

    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), primary_key=True)
    corner: Mapped[Corner] = mapped_column(str_enum(Corner, "corner"), primary_key=True)
    tire_id: Mapped[int] = mapped_column(ForeignKey("tire.id"))
    notes: Mapped[str | None] = mapped_column(Text)

    tire: Mapped[Tire] = relationship()


class TireMeasurement(Base):
    """Pressure and three-zone temperature of the tyre fitted at a corner.

    The composite FK to run_tire_assignment(run_id, corner) means a measurement
    cannot exist for a corner without a fitted tyre. Values may be partially
    missing (NULL = not measured), but at least one must be present.
    """

    __tablename__ = "tire_measurement"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "corner"],
            ["run_tire_assignment.run_id", "run_tire_assignment.corner"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "corner", "phase"),
        CheckConstraint("pressure_kpa IS NULL OR pressure_kpa > 0", name="pressure_positive"),
        CheckConstraint(
            "pressure_kpa IS NOT NULL OR temperature_inner_c IS NOT NULL"
            " OR temperature_center_c IS NOT NULL OR temperature_outer_c IS NOT NULL",
            name="has_a_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column()
    corner: Mapped[Corner] = mapped_column(str_enum(Corner, "corner"))
    phase: Mapped[MeasurementPhase] = mapped_column(str_enum(MeasurementPhase, "phase"))
    pressure_kpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    temperature_inner_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    temperature_center_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    temperature_outer_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    notes: Mapped[str | None] = mapped_column(Text)

    assignment: Mapped[RunTireAssignment] = relationship(
        primaryjoin="and_(TireMeasurement.run_id == RunTireAssignment.run_id,"
        " TireMeasurement.corner == RunTireAssignment.corner)",
        foreign_keys=[run_id, corner],
        viewonly=True,
    )

    @property
    def tire_id(self) -> int:
        """The physical tyre measured: the one fitted at this corner for the run."""
        return self.assignment.tire_id


class AlignmentMeasurement(Base):
    """Observed camber/toe at a corner around one run.

    Distinct from SetupSnapshot, which holds the intended static setup; a
    measurement never modifies a snapshot.
    """

    __tablename__ = "alignment_measurement"
    __table_args__ = (
        UniqueConstraint("run_id", "corner", "phase"),
        CheckConstraint("camber_deg IS NOT NULL OR toe_deg IS NOT NULL", name="has_a_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    corner: Mapped[Corner] = mapped_column(str_enum(Corner, "corner"))
    phase: Mapped[MeasurementPhase] = mapped_column(str_enum(MeasurementPhase, "phase"))
    # Negative camber = top of wheel inward; negative toe = toe-out.
    camber_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    toe_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    notes: Mapped[str | None] = mapped_column(Text)
