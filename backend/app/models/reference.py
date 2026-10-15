from datetime import date

from sqlalchemy import CheckConstraint, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Season(Base):
    __tablename__ = "season"
    __table_args__ = (
        CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="date_order",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Free-text label (e.g. "2026/27") so no season year is hard-coded.
    name: Mapped[str] = mapped_column(String(64), unique=True)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)


class Vehicle(Base):
    """One physical car / vehicle generation."""

    __tablename__ = "vehicle"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Driver(Base):
    __tablename__ = "driver"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Short unique handle; full names are not guaranteed unique.
    code: Mapped[str] = mapped_column(String(16), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
