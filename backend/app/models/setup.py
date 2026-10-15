from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Corner, UTCDateTime, str_enum, utc_now


class SetupSnapshot(Base):
    """Immutable, reusable vehicle setup.

    Append-only by design: a change is recorded as a new snapshot pointing at
    the snapshot it was derived from (based_on_snapshot_id), with the reason and
    timestamp of the change. Several runs may reference the same snapshot, which
    is how reusable configurations are represented. Immutability is enforced in
    the service/API layer (no update operation exists), not by triggers.

    Whole-vehicle parameters live as typed columns here; per-corner parameters
    live in SetupCornerParams. A separate 1:1 vehicle-parameter table was
    rejected because it adds a join and a "header without parameters" state
    without adding integrity.
    """

    __tablename__ = "setup_snapshot"
    __table_args__ = (
        CheckConstraint(
            "based_on_snapshot_id IS NULL OR based_on_snapshot_id <> id", name="not_based_on_self"
        ),
        CheckConstraint(
            "based_on_snapshot_id IS NULL OR change_reason IS NOT NULL",
            name="derived_requires_reason",
        ),
        CheckConstraint(
            "power_limit_kw IS NULL OR power_limit_kw > 0", name="power_limit_positive"
        ),
        CheckConstraint("rpm_limit_rpm IS NULL OR rpm_limit_rpm > 0", name="rpm_limit_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"))
    name: Mapped[str | None] = mapped_column(String(120))
    based_on_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("setup_snapshot.id"))
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    power_limit_kw: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    rpm_limit_rpm: Mapped[int | None] = mapped_column(Integer)
    # Labels rather than enums: available modes/maps differ per vehicle generation.
    torque_vectoring_mode: Mapped[str | None] = mapped_column(String(32))
    control_map: Mapped[str | None] = mapped_column(String(64))

    vehicle: Mapped["Vehicle"] = relationship()  # noqa: F821
    based_on: Mapped["SetupSnapshot | None"] = relationship(remote_side=[id])
    corners: Mapped[list["SetupCornerParams"]] = relationship(
        back_populates="setup_snapshot",
        order_by="SetupCornerParams.corner",
        cascade="all, delete-orphan",
    )


class SetupCornerParams(Base):
    """Per-corner setup values; at most one row per (snapshot, corner)."""

    __tablename__ = "setup_corner_params"
    __table_args__ = (
        CheckConstraint(
            "spring_rate_n_per_mm IS NULL OR spring_rate_n_per_mm > 0",
            name="spring_rate_positive",
        ),
    )

    setup_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("setup_snapshot.id", ondelete="CASCADE"), primary_key=True
    )
    corner: Mapped[Corner] = mapped_column(str_enum(Corner, "corner"), primary_key=True)
    # Negative camber = top of wheel inward; negative toe = toe-out.
    static_camber_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    static_toe_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    spring_rate_n_per_mm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))

    setup_snapshot: Mapped[SetupSnapshot] = relationship(back_populates="corners")
