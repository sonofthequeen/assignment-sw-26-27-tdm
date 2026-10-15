from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

# Bounded to SQLite/PostgreSQL 32-bit-safe integers so oversized input is a 422,
# not a driver OverflowError.
MAX_ID = 2_147_483_647
MAX_INT = 2_147_483_647

Id = Annotated[int, Field(gt=0, le=MAX_ID)]
PositiveCount = Annotated[int, Field(gt=0, le=MAX_INT)]
DurationMs = Annotated[int, Field(gt=0, le=MAX_INT)]


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# Offset required (naive input is rejected); normalised to UTC so responses are canonical.
UtcDateTime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


def text(max_length: int):
    """Trimmed, non-empty string with a maximum length."""
    constraints = StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    return Annotated[str, constraints]


LongText = text(4000)


class RequestModel(BaseModel):
    # Unknown fields are rejected so typos (or attempts to set ids) fail loudly.
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageQuery(RequestModel):
    limit: int = Field(50, ge=1, le=100, description="Page size (1-100).")
    offset: int = Field(0, ge=0, le=MAX_INT, description="Number of items to skip.")


class Page[T](BaseModel):
    items: list[T]
    limit: int
    offset: int
    total: int = Field(description="Total matching items (exact COUNT; acceptable at TDM scale).")
    order_by: list[str] = Field(description="Deterministic ordering applied to the collection.")


class ErrorDetailBody(BaseModel):
    field: str | None
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetailBody]


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_responses(*status_codes: int) -> dict:
    descriptions = {
        404: "Resource not found",
        409: "Conflict with existing data",
        422: "Request or domain validation failed",
    }
    return {
        code: {"model": ErrorResponse, "description": descriptions[code]} for code in status_codes
    }
