import enum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum


class LapClassification(enum.StrEnum):
    FLYING = "FLYING"
    IN_LAP = "IN_LAP"
    OUT_LAP = "OUT_LAP"
    ABORTED = "ABORTED"


class Lap(Base):
    """One traversal of the run's track layout.

    Timing validity and physical completion are independent:
    - a lap can be physically completed but timing-invalid (cone, track limits,
      transponder miss); it still counts toward mileage;
    - raw_time_ms may be NULL when no time was recorded, which forces
      timing_valid = false.
    effective time (raw + penalty), fastest lap and mileage are derived in
    queries and never stored.

    Deliberately NOT a database constraint: "ABORTED implies not physically
    completed". A driver can abort a push lap and still complete the loop, so
    the mileage policy for ABORTED laps is a documented service-level rule.
    """

    __tablename__ = "lap"
    __table_args__ = (
        UniqueConstraint("run_id", "lap_number"),
        CheckConstraint("lap_number > 0", name="lap_number_positive"),
        CheckConstraint("raw_time_ms IS NULL OR raw_time_ms > 0", name="raw_time_positive"),
        CheckConstraint("penalty_duration_ms >= 0", name="penalty_non_negative"),
        CheckConstraint(
            "raw_time_ms IS NOT NULL OR NOT timing_valid", name="untimed_lap_not_valid"
        ),
        # Valid <=> no invalidation reason; an invalid lap must say why.
        # Boolean expressions written without "= 1" so they also hold on PostgreSQL.
        CheckConstraint(
            "(timing_valid AND invalidation_reason IS NULL)"
            " OR (NOT timing_valid AND invalidation_reason IS NOT NULL"
            " AND length(trim(invalidation_reason)) > 0)",
            name="invalidation_reason_consistent",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    lap_number: Mapped[int] = mapped_column(Integer)
    lap_classification: Mapped[LapClassification] = mapped_column(
        str_enum(LapClassification, "lap_classification")
    )
    raw_time_ms: Mapped[int | None] = mapped_column(Integer)
    penalty_duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    timing_valid: Mapped[bool] = mapped_column(Boolean(create_constraint=True, name="timing_valid"))
    physically_completed: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="physically_completed")
    )
    invalidation_reason: Mapped[str | None] = mapped_column(Text)

    run: Mapped["Run"] = relationship(back_populates="laps")  # noqa: F821
