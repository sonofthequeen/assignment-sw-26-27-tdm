from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from app.models import ActivityType
from app.schemas.common import Id, LongText, PageQuery, RequestModel, ResponseModel, text

# Mirrors NUMERIC(9, 3): metres with millimetre resolution.
LengthM = Annotated[Decimal, Field(gt=0, max_digits=9, decimal_places=3)]


class TrackLocationCreate(RequestModel):
    name: text(120)


class TrackLocationRead(ResponseModel):
    id: int
    name: str


class TrackLayoutCreate(RequestModel):
    track_location_id: Id
    name: text(120)
    activity_type: ActivityType
    verified_length_m: LengthM = Field(description="Verified length of one lap, metres.")
    length_verified_on: date = Field(description="Date the length was verified.")
    length_verification_note: LongText | None = None


class TrackLayoutRead(ResponseModel):
    id: int
    track_location_id: int
    name: str
    activity_type: ActivityType
    verified_length_m: Decimal
    length_verified_on: date
    length_verification_note: str | None


class TrackLayoutListQuery(PageQuery):
    track_location_id: Id | None = None
    activity_type: ActivityType | None = None
