import enum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text, UniqueConstraint, and_
from sqlalchemy.ext.hybrid import hybrid_property
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
    effective time (raw + penalty), fastest-lap eligibility and mileage are
    derived (hybrid properties below) and never stored.

    Deliberately NOT a database constraint: "ABORTED implies not physically
    completed". A driver can abort a push lap and still complete the loop; such
    a record (physically_completed = true) counts one full layout for mileage.
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

    # Derived values. Each is defined once and works both on instances (Python) and in
    # queries (SQL), so the API, rankings and aggregates cannot disagree. None is stored.

    @hybrid_property
    def effective_time_ms(self) -> int | None:
        """raw + penalty; None for an untimed lap (no time is ever invented)."""
        if self.raw_time_ms is None:
            return None
        return self.raw_time_ms + (self.penalty_duration_ms or 0)

    @effective_time_ms.inplace.expression
    @classmethod
    def _effective_time_ms_expression(cls):
        # NULL + n is NULL in SQL, matching the Python rule for untimed laps.
        return cls.raw_time_ms + cls.penalty_duration_ms

    @hybrid_property
    def fastest_lap_eligible(self) -> bool:
        """Timed, timing-valid, physically completed FLYING laps only.

        Penalised laps stay eligible and are ranked by effective time. IN_LAP,
        OUT_LAP and ABORTED laps are never eligible, even when they count for mileage.
        """
        return (
            self.timing_valid
            and self.raw_time_ms is not None
            and self.physically_completed
            and self.lap_classification == LapClassification.FLYING
        )

    @fastest_lap_eligible.inplace.expression
    @classmethod
    def _fastest_lap_eligible_expression(cls):
        return and_(
            cls.timing_valid.is_(True),
            cls.raw_time_ms.is_not(None),
            cls.physically_completed.is_(True),
            cls.lap_classification == LapClassification.FLYING,
        )

    @hybrid_property
    def counts_toward_mileage(self) -> bool:
        """One full verified layout length per physically completed lap, whatever the
        timing validity, penalty or classification (an ABORTED attempt that completed
        the loop counts). Incomplete laps count zero: no partial distance is modelled."""
        return bool(self.physically_completed)

    @counts_toward_mileage.inplace.expression
    @classmethod
    def _counts_toward_mileage_expression(cls):
        return cls.physically_completed.is_(True)


# Deterministic ranking for fastest-lap selection.
FASTEST_LAP_ORDER = (
    Lap.effective_time_ms.asc(),
    Lap.raw_time_ms.asc(),
    Lap.lap_number.asc(),
    Lap.id.asc(),
)
