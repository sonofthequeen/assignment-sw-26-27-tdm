"""Season objectives and their traceability to tests and actual runs.

Progress is derived (count of linked runs), never stored. "Same season" rules
are cross-row and enforced in the service layer: a database constraint would
need UNIQUE(id, season_id) on test, i.e. a rebuild of an existing table.
"""

import enum

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, str_enum


class ObjectivePriority(enum.StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ObjectiveStatus(enum.StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    ACHIEVED = "ACHIEVED"
    DROPPED = "DROPPED"


class SeasonObjective(Base):
    __tablename__ = "season_objective"
    __table_args__ = (
        CheckConstraint("desired_repetitions > 0", name="desired_repetitions_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[ObjectivePriority] = mapped_column(
        str_enum(ObjectivePriority, "objective_priority")
    )
    desired_repetitions: Mapped[int] = mapped_column(Integer)
    status: Mapped[ObjectiveStatus] = mapped_column(
        str_enum(ObjectiveStatus, "objective_status"), default=ObjectiveStatus.OPEN
    )
    notes: Mapped[str | None] = mapped_column(Text)


class TestObjective(Base):
    """A test addresses an objective (composite PK: no duplicate links)."""

    __test__ = False
    __tablename__ = "test_objective"

    test_id: Mapped[int] = mapped_column(
        ForeignKey("test.id", ondelete="CASCADE"), primary_key=True
    )
    objective_id: Mapped[int] = mapped_column(ForeignKey("season_objective.id"), primary_key=True)


class RunObjective(Base):
    """An actual run addresses an objective; each linked run is one repetition."""

    __tablename__ = "run_objective"

    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), primary_key=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("season_objective.id"), primary_key=True)
