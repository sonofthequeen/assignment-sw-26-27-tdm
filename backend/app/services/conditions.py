"""Run conditions: create-once per run.

Correction policy: conditions are written once. A second write is a 409; silently
overwriting measured conditions would destroy history. Corrections are deferred
to explicit correction records.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.exceptions import ConflictError, DomainValidationError, ErrorDetail, NotFoundError
from app.models import Run, RunCondition
from app.policies import CONDITION_LIMITS
from app.schemas.conditions import RunConditionCreate
from app.services.lookup import get_or_404


def _check_range(value: Decimal | None, low: Decimal, high: Decimal, field: str) -> None:
    if value is not None and not low <= value <= high:
        raise DomainValidationError.for_field(
            "invalid_condition_value",
            field,
            f"{field} must be between {low} and {high} °C (validation policy).",
        )


def create_run_condition(session: Session, run_id: int, data: RunConditionCreate) -> RunCondition:
    get_or_404(session, Run, run_id, "run")
    limits = CONDITION_LIMITS
    _check_range(
        data.ambient_temperature_c,
        limits.ambient_min_c,
        limits.ambient_max_c,
        "ambient_temperature_c",
    )
    _check_range(
        data.asphalt_temperature_c,
        limits.asphalt_min_c,
        limits.asphalt_max_c,
        "asphalt_temperature_c",
    )
    if session.get(RunCondition, run_id) is not None:
        raise ConflictError(
            code="run_condition_already_exists",
            message=f"Run {run_id} already has recorded conditions; they are write-once.",
            details=[ErrorDetail(None, "Conditions cannot be overwritten.")],
        )
    condition = RunCondition(run_id=run_id, **data.model_dump())
    session.add(condition)
    session.flush()
    return condition


def get_run_condition(session: Session, run_id: int) -> RunCondition:
    get_or_404(session, Run, run_id, "run")
    condition = session.get(RunCondition, run_id)
    if condition is None:
        raise NotFoundError("run_condition", run_id)
    return condition
