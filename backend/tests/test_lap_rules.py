"""The derived lap rules agree between Python (instances) and SQL (queries)."""

import itertools

import pytest
from sqlalchemy import select

from app.models import Lap, LapClassification, Run
from app.models.laps import FASTEST_LAP_ORDER


@pytest.fixture
def run(session, base_graph):
    run = Run(
        test=base_graph["test"],
        run_number=1,
        driver=base_graph["driver"],
        track_layout=base_graph["layout"],
    )
    session.add(run)
    session.flush()
    return run


def test_effective_time_python_and_sql_agree(session, run):
    laps = [
        Lap(run=run, lap_number=1, lap_classification="FLYING", raw_time_ms=60_000,
            penalty_duration_ms=0, timing_valid=True, physically_completed=True),
        Lap(run=run, lap_number=2, lap_classification="FLYING", raw_time_ms=60_000,
            penalty_duration_ms=2_500, timing_valid=True, physically_completed=True),
        Lap(run=run, lap_number=3, lap_classification="FLYING", raw_time_ms=None,
            penalty_duration_ms=2_000, timing_valid=False, physically_completed=True,
            invalidation_reason="Untimed"),
    ]  # fmt: skip
    session.add_all(laps)
    session.flush()

    assert [lap.effective_time_ms for lap in laps] == [60_000, 62_500, None]
    from_sql = session.execute(
        select(Lap.lap_number, Lap.effective_time_ms).order_by(Lap.lap_number)
    ).all()
    assert [tuple(row) for row in from_sql] == [(1, 60_000), (2, 62_500), (3, None)]


def test_eligibility_and_mileage_python_and_sql_agree_for_every_combination(session, run):
    combinations = itertools.product(
        LapClassification, (True, False), (True, False), (60_000, None)
    )
    number = 0
    for classification, valid, completed, raw in combinations:
        if valid and raw is None:
            continue  # forbidden by the schema
        number += 1
        session.add(
            Lap(
                run=run,
                lap_number=number,
                lap_classification=classification,
                raw_time_ms=raw,
                timing_valid=valid,
                physically_completed=completed,
                invalidation_reason=None if valid else "Invalid",
            )
        )
    session.flush()

    laps = session.scalars(select(Lap).order_by(Lap.lap_number)).all()
    python_eligible = {lap.lap_number for lap in laps if lap.fastest_lap_eligible}
    sql_eligible = set(session.scalars(select(Lap.lap_number).where(Lap.fastest_lap_eligible)))
    assert python_eligible == sql_eligible
    assert all(
        lap.lap_classification == LapClassification.FLYING
        and lap.timing_valid
        and lap.physically_completed
        and lap.raw_time_ms is not None
        for lap in laps
        if lap.lap_number in python_eligible
    )
    assert len(python_eligible) == 1

    python_counted = {lap.lap_number for lap in laps if lap.counts_toward_mileage}
    sql_counted = set(session.scalars(select(Lap.lap_number).where(Lap.counts_toward_mileage)))
    assert (
        python_counted
        == sql_counted
        == {lap.lap_number for lap in laps if lap.physically_completed}
    )


def test_fastest_lap_order_is_total(session, run):
    session.add_all(
        [
            Lap(run=run, lap_number=n, lap_classification="FLYING", raw_time_ms=raw,
                penalty_duration_ms=penalty, timing_valid=True, physically_completed=True)
            for n, raw, penalty in ((1, 61_000, 0), (2, 60_000, 1_000), (3, 60_000, 1_000))
        ]
    )  # fmt: skip
    session.flush()
    ordered = session.scalars(select(Lap.lap_number).order_by(*FASTEST_LAP_ORDER)).all()
    # Equal effective time (61 000): lower raw time first, then lap number.
    assert ordered == [2, 3, 1]
