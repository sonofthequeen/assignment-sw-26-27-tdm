from datetime import date

from pydantic import model_validator

from app.schemas.common import RequestModel, ResponseModel, text


class SeasonCreate(RequestModel):
    name: text(64)
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def _date_order(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on must not be before starts_on")
        return self


class SeasonRead(ResponseModel):
    id: int
    name: str
    starts_on: date | None
    ends_on: date | None


class VehicleCreate(RequestModel):
    code: text(32)
    name: text(120)


class VehicleRead(ResponseModel):
    id: int
    code: str
    name: str


class DriverCreate(RequestModel):
    code: text(16)
    full_name: text(120)


class DriverRead(ResponseModel):
    id: int
    code: str
    full_name: str
