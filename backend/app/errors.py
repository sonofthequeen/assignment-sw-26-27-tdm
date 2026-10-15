"""Centralised error responses.

Every error leaves the API in one shape:
    {"error": {"code": str, "message": str, "details": [{"field": str|None, "issue": str}]}}

Database IntegrityErrors are translated through a registry keyed by *constraint
name*, so the API never exposes SQL, table names or constraint names. SQLite
reports CHECK failures by constraint name but UNIQUE/PRIMARY KEY failures only as
"table.column" lists, and FOREIGN KEY failures with no name at all; the
(table, columns) -> constraint-name map is derived from the ORM metadata so the
two backends share one registry (PostgreSQL would use diag.constraint_name).
"""

import logging
import re
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import DomainError, ErrorDetail
from app.models import Base

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslatedError:
    status_code: int
    code: str
    message: str
    details: tuple[ErrorDetail, ...] = ()


def _unique(code: str, field: str, message: str) -> TranslatedError:
    return TranslatedError(409, code, message, (ErrorDetail(field, message),))


def _check(field: str, issue: str) -> TranslatedError:
    return TranslatedError(422, "constraint_violation", issue, (ErrorDetail(field, issue),))


KNOWN_CONSTRAINTS: dict[str, TranslatedError] = {
    "uq_season_name": _unique("season_name_taken", "name", "A season with this name exists."),
    "uq_vehicle_code": _unique("vehicle_code_taken", "code", "A vehicle with this code exists."),
    "uq_driver_code": _unique("driver_code_taken", "code", "A driver with this code exists."),
    "uq_track_location_name": _unique(
        "track_location_name_taken", "name", "A track location with this name exists."
    ),
    "uq_track_layout_track_location_id_name": _unique(
        "track_layout_name_taken", "name", "This location already has a layout with this name."
    ),
    "uq_planned_run_test_id_sequence_number": _unique(
        "planned_run_sequence_taken",
        "sequence_number",
        "This test already has a planned run with this sequence number.",
    ),
    "uq_run_test_id_run_number": _unique(
        "run_number_taken", "run_number", "This test already has a run with this run number."
    ),
    "uq_lap_run_id_lap_number": _unique(
        "lap_number_taken", "lap_number", "This run already has a lap with this lap number."
    ),
    "uq_tire_compound_manufacturer_name": _unique(
        "tire_compound_conflict", "name", "This manufacturer already has a compound with this name."
    ),
    "uq_tire_set_set_code": _unique(
        "tire_set_code_taken", "set_code", "A tyre set with this code exists."
    ),
    "uq_tire_serial_number": _unique(
        "tire_identifier_taken", "serial_number", "A tyre with this serial number exists."
    ),
    "pk_run_tire_assignment": _unique(
        "tire_assignment_conflict", "corner", "This corner already has a tyre for the run."
    ),
    "uq_run_tire_assignment_run_id_tire_id": _unique(
        "tire_assignment_conflict", "tire_id", "This tyre is already fitted for the run."
    ),
    "uq_tire_measurement_run_id_corner_phase": _unique(
        "tire_measurement_conflict", "phase", "This corner and phase are already measured."
    ),
    "uq_alignment_measurement_run_id_corner_phase": _unique(
        "alignment_measurement_conflict", "phase", "This corner and phase are already measured."
    ),
    "pk_run_condition": _unique(
        "run_condition_already_exists", "run_id", "This run already has recorded conditions."
    ),
    "pk_setup_corner_params": _unique(
        "setup_corner_taken", "corner", "This setup already has values for this corner."
    ),
    "ck_season_date_order": _check("ends_on", "ends_on must not be before starts_on."),
    "ck_track_layout_verified_length_positive": _check(
        "verified_length_m", "verified_length_m must be greater than 0."
    ),
    "ck_run_time_order": _check("ended_at", "ended_at must not be before started_at."),
}

GENERIC_INTEGRITY_ERROR = TranslatedError(
    409, "integrity_conflict", "The request conflicts with existing data."
)
GENERIC_CHECK_ERROR = TranslatedError(
    422, "constraint_violation", "The request violates a data integrity rule."
)
FOREIGN_KEY_ERROR = TranslatedError(
    422, "referenced_resource_not_found", "The request references a resource that does not exist."
)


def _unique_constraint_names() -> dict[tuple[str, tuple[str, ...]], str]:
    names = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint | PrimaryKeyConstraint) and constraint.name:
                columns = tuple(column.name for column in constraint.columns)
                names[(table.name, columns)] = str(constraint.name)
    return names


_UNIQUE_BY_COLUMNS = _unique_constraint_names()
_SQLITE_UNIQUE = re.compile(r"UNIQUE constraint failed: (?P<columns>[\w., ]+)")
_SQLITE_CHECK = re.compile(r"CHECK constraint failed: (?P<name>\w+)")


def constraint_name_from_integrity_error(exc: IntegrityError) -> str | None:
    message = str(exc.orig)
    if match := _SQLITE_CHECK.search(message):
        return match.group("name")
    if match := _SQLITE_UNIQUE.search(message):
        qualified = [part.strip().split(".") for part in match.group("columns").split(",")]
        table = qualified[0][0]
        columns = tuple(column for _, column in qualified)
        return _UNIQUE_BY_COLUMNS.get((table, columns))
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)


def translate_integrity_error(exc: IntegrityError) -> TranslatedError:
    name = constraint_name_from_integrity_error(exc)
    if name in KNOWN_CONSTRAINTS:
        return KNOWN_CONSTRAINTS[name]
    message = str(exc.orig)
    if "FOREIGN KEY constraint failed" in message:
        return FOREIGN_KEY_ERROR
    if "CHECK constraint failed" in message or "NOT NULL constraint failed" in message:
        return GENERIC_CHECK_ERROR
    return GENERIC_INTEGRITY_ERROR


def error_body(code: str, message: str, details=()) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": [{"field": d.field, "issue": d.issue} for d in details],
        }
    }


def _response(status_code: int, code: str, message: str, details=()) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message, details))


def _field_path(location: tuple) -> str | None:
    # Drop the "body"/"query"/"path" prefix FastAPI adds to error locations.
    parts = [str(part) for part in location[1:]] if len(location) > 1 else []
    return ".".join(parts) or None


async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
    return _response(exc.status_code, exc.code, exc.message, exc.details)


async def _request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [ErrorDetail(_field_path(tuple(e["loc"])), e["msg"]) for e in exc.errors()]
    return _response(422, "request_validation_failed", "The request is invalid.", details)


async def _integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    translated = translate_integrity_error(exc)
    # The raw database message stays in the server log only.
    logger.warning("Integrity error translated to %s: %s", translated.code, exc.orig)
    return _response(
        translated.status_code, translated.code, translated.message, translated.details
    )


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {404: "not_found", 405: "method_not_allowed"}
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error."
    return _response(exc.status_code, codes.get(exc.status_code, "http_error"), message)


async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return _response(500, "internal_error", "An unexpected error occurred.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(IntegrityError, _integrity_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)
