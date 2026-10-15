"""Lap ingestion, fastest-lap selection and per-run lap statistics.

Laps are append-only in this phase (no update or delete). Client-provided
validity is never "fixed" silently: contradictory input is rejected.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.exceptions import ConflictError, DomainValidationError, ErrorDetail, NotFoundError
from app.models import Lap, Run
from app.models.laps import FASTEST_LAP_ORDER
from app.policies import LAP_INGESTION, LAP_PLAUSIBILITY
from app.schemas.common import PageQuery
from app.schemas.laps import LapBulkCreate, LapCreate
from app.services.lookup import get_or_404
from app.services.pagination import Ordering, PageResult, paginate

LAP_ORDER = (Ordering("lap_number asc", Lap.lap_number.asc()), Ordering("id asc", Lap.id.asc()))


def _invalid(field: str, message: str) -> DomainValidationError:
    return DomainValidationError.for_field("invalid_lap_state", field, message)


def validate_lap(lap: LapCreate, run: Run, prefix: str = "") -> None:
    if lap.timing_valid and lap.raw_time_ms is None:
        raise _invalid(f"{prefix}raw_time_ms", "A timing-valid lap must have raw_time_ms.")
    if lap.timing_valid and lap.invalidation_reason is not None:
        raise _invalid(
            f"{prefix}invalidation_reason", "A timing-valid lap cannot have an invalidation reason."
        )
    if not lap.timing_valid and lap.invalidation_reason is None:
        raise _invalid(
            f"{prefix}invalidation_reason",
            "A timing-invalid lap must state an invalidation reason.",
        )
    _check_plausible_speed(lap, run, prefix)


def _check_plausible_speed(lap: LapCreate, run: Run, prefix: str) -> None:
    """Rejects implied average speeds no car can reach over one full layout.

    Uses raw time (penalties are not traversal time) and only for physically
    completed laps: an incomplete lap did not cover the verified length.
    """
    if lap.raw_time_ms is None or not lap.physically_completed:
        return
    layout = run.track_layout
    limit_mps = LAP_PLAUSIBILITY.max_average_speed_mps[layout.activity_type]
    # length / (ms / 1000) > limit, kept in exact Decimal arithmetic.
    if layout.verified_length_m * 1000 > limit_mps * lap.raw_time_ms:
        implied = (layout.verified_length_m * 1000 / Decimal(lap.raw_time_ms)).quantize(
            Decimal("0.1")
        )
        raise DomainValidationError.for_field(
            "impossible_lap_time",
            f"{prefix}raw_time_ms",
            f"{lap.raw_time_ms} ms over {layout.verified_length_m} m implies {implied} m/s, above "
            f"the {limit_mps} m/s plausibility limit for {layout.activity_type}.",
        )


def _get_run_with_layout(session: Session, run_id: int) -> Run:
    run = session.scalar(select(Run).where(Run.id == run_id).options(joinedload(Run.track_layout)))
    if run is None:
        raise NotFoundError("run", run_id)
    return run


def _reject_existing_lap_numbers(
    session: Session, run_id: int, laps: list[LapCreate], prefix: str
) -> None:
    requested = {lap.lap_number for lap in laps}
    existing = set(
        session.scalars(
            select(Lap.lap_number).where(Lap.run_id == run_id, Lap.lap_number.in_(requested))
        )
    )
    if existing:
        raise ConflictError(
            code="lap_number_taken",
            message="This run already has laps with these lap numbers.",
            details=[
                ErrorDetail(f"{prefix.format(index=i)}lap_number", f"Lap {lap.lap_number} exists.")
                for i, lap in enumerate(laps)
                if lap.lap_number in existing
            ],
        )


def create_lap(session: Session, run_id: int, data: LapCreate) -> Lap:
    run = _get_run_with_layout(session, run_id)
    validate_lap(data, run)
    _reject_existing_lap_numbers(session, run_id, [data], prefix="")
    lap = Lap(run_id=run_id, **data.model_dump())
    session.add(lap)
    session.flush()
    return lap


def create_laps(session: Session, run_id: int, data: LapBulkCreate) -> list[Lap]:
    """All-or-nothing: any invalid lap aborts the request transaction."""
    run = _get_run_with_layout(session, run_id)
    if not data.laps:
        raise DomainValidationError.for_field(
            "empty_lap_batch", "laps", "The batch must contain at least one lap."
        )
    if len(data.laps) > LAP_INGESTION.max_batch_size:
        raise DomainValidationError.for_field(
            "lap_batch_too_large",
            "laps",
            f"At most {LAP_INGESTION.max_batch_size} laps per request.",
        )
    counts = Counter(lap.lap_number for lap in data.laps)
    duplicates = [
        ErrorDetail(f"laps.{i}.lap_number", f"Lap number {lap.lap_number} repeats in the batch.")
        for i, lap in enumerate(data.laps)
        if counts[lap.lap_number] > 1
    ]
    if duplicates:
        raise DomainValidationError(
            code="duplicate_lap_number_in_batch",
            message="Lap numbers must be unique within the batch.",
            details=duplicates,
        )
    for index, lap in enumerate(data.laps):
        validate_lap(lap, run, prefix=f"laps.{index}.")
    _reject_existing_lap_numbers(session, run_id, data.laps, prefix="laps.{index}.")

    laps = [
        Lap(run_id=run_id, **lap.model_dump())
        for lap in sorted(data.laps, key=lambda lap: lap.lap_number)
    ]
    session.add_all(laps)
    session.flush()
    return laps


def get_lap(session: Session, lap_id: int) -> Lap:
    return get_or_404(session, Lap, lap_id, "lap")


def list_laps(session: Session, run_id: int, page: PageQuery) -> PageResult:
    get_or_404(session, Run, run_id, "run")
    return paginate(session, select(Lap).where(Lap.run_id == run_id), page, LAP_ORDER)


@dataclass(frozen=True)
class RunLapSummary:
    recorded_lap_count: int
    physically_completed_lap_count: int
    eligible_lap_count: int
    fastest_lap: Lap | None


EMPTY_LAP_SUMMARY = RunLapSummary(0, 0, 0, None)


def lap_summaries(session: Session, run_ids: list[int]) -> dict[int, RunLapSummary]:
    """Lap statistics for many runs in two queries, independent of the number of runs.

    The fastest lap per run uses ROW_NUMBER() over FASTEST_LAP_ORDER, so the
    single-run endpoints, historical search and plan comparisons share one ranking.
    """
    if not run_ids:
        return {}
    counts = session.execute(
        select(
            Lap.run_id,
            func.count(Lap.id),
            func.count(Lap.id).filter(Lap.counts_toward_mileage),
            func.count(Lap.id).filter(Lap.fastest_lap_eligible),
        )
        .where(Lap.run_id.in_(run_ids))
        .group_by(Lap.run_id)
    ).all()
    ranked = (
        select(
            Lap.id.label("lap_id"),
            func.row_number()
            .over(partition_by=Lap.run_id, order_by=FASTEST_LAP_ORDER)
            .label("rank"),
        )
        .where(Lap.run_id.in_(run_ids), Lap.fastest_lap_eligible)
        .subquery()
    )
    fastest = {
        lap.run_id: lap
        for lap in session.scalars(
            select(Lap).join(ranked, ranked.c.lap_id == Lap.id).where(ranked.c.rank == 1)
        )
    }
    return {
        run_id: RunLapSummary(recorded, completed, eligible, fastest.get(run_id))
        for run_id, recorded, completed, eligible in counts
    }


def summarize_run_laps(session: Session, run_id: int) -> RunLapSummary:
    return lap_summaries(session, [run_id]).get(run_id, EMPTY_LAP_SUMMARY)


def get_fastest_lap(session: Session, run_id: int) -> RunLapSummary:
    get_or_404(session, Run, run_id, "run")
    return summarize_run_laps(session, run_id)
