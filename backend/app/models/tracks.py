import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum


class ActivityType(enum.StrEnum):
    SKIDPAD = "SKIDPAD"
    AUTOCROSS = "AUTOCROSS"
    ENDURANCE = "ENDURANCE"
    ACCELERATION = "ACCELERATION"
    GENERIC_TESTING = "GENERIC_TESTING"


class TrackLocation(Base):
    __tablename__ = "track_location"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

    layouts: Mapped[list["TrackLayout"]] = relationship(
        back_populates="track_location", order_by="TrackLayout.id"
    )


class TrackLayout(Base):
    """A specific driven configuration at a location.

    One lap = one traversal of verified_length_m (one skidpad circle, one
    acceleration attempt, one autocross/endurance loop). Mileage is derived from
    this length; it is never stored per run.
    """

    __tablename__ = "track_layout"
    __table_args__ = (
        UniqueConstraint("track_location_id", "name"),
        CheckConstraint("verified_length_m > 0", name="verified_length_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    track_location_id: Mapped[int] = mapped_column(ForeignKey("track_location.id"))
    name: Mapped[str] = mapped_column(String(120))
    activity_type: Mapped[ActivityType] = mapped_column(str_enum(ActivityType, "activity_type"))
    verified_length_m: Mapped[Decimal] = mapped_column(Numeric(9, 3))
    # Verification is explicit: a length without a verification date is not accepted.
    length_verified_on: Mapped[date] = mapped_column(Date)
    length_verification_note: Mapped[str | None] = mapped_column(Text)

    track_location: Mapped[TrackLocation] = relationship(back_populates="layouts")
