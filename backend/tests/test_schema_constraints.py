"""Database-level invariants of the MVP-Core schema.

Each failing case asserts the specific named constraint (or UNIQUE columns)
that SQLite reports, so a test cannot pass because of an unrelated error.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import (
    ActivityType,
    ConditionsSource,
    Corner,
    Lap,
    LapClassification,
    PlannedRun,
    PlannedRunStatus,
    Run,
    RunCondition,
    SetupCornerParams,
    SetupSnapshot,
    TrackLayout,
    TrackLocation,
)


def assert_rejected(session, match: str, *objects) -> None:
    session.add_all(objects)
    with pytest.raises(IntegrityError, match=match):
        session.flush()
    session.rollback()


def make_run(graph, run_number=1, **overrides) -> Run:
    values = {
        "test": graph["test"],
        "run_number": run_number,
        "driver": graph["driver"],
        "track_layout": graph["layout"],
    }
    values.update(overrides)
    return Run(**values)


def make_lap(run, lap_number=1, **overrides) -> Lap:
    values = {
        "run": run,
        "lap_number": lap_number,
        "lap_classification": LapClassification.FLYING,
        "raw_time_ms": 65_432,
        "timing_valid": True,
        "physically_completed": True,
    }
    values.update(overrides)
    return Lap(**values)


# --- Track layouts ---------------------------------------------------------


@pytest.mark.parametrize("length", [Decimal("0"), Decimal("-1.5")])
def test_layout_length_must_be_positive(session, base_graph, length):
    layout = TrackLayout(
        track_location=base_graph["location"],
        name="Bad",
        activity_type=ActivityType.SKIDPAD,
        verified_length_m=length,
        length_verified_on=date(2026, 1, 1),
    )
    assert_rejected(session, "ck_track_layout_verified_length_positive", layout)


def test_layout_name_unique_within_location_only(session, base_graph):
    duplicate = TrackLayout(
        track_location=base_graph["location"],
        name="Autocross loop",
        activity_type=ActivityType.AUTOCROSS,
        verified_length_m=Decimal("900"),
        length_verified_on=date(2026, 1, 1),
    )
    assert_rejected(session, "UNIQUE constraint failed: track_layout.track_location_id", duplicate)

    other_location = TrackLocation(name="Location B")
    same_name_elsewhere = TrackLayout(
        track_location=other_location,
        name="Autocross loop",
        activity_type=ActivityType.AUTOCROSS,
        verified_length_m=Decimal("900"),
        length_verified_on=date(2026, 1, 1),
    )
    session.add_all([other_location, same_name_elsewhere])
    session.commit()


def test_invalid_activity_type_rejected_by_database(engine, base_graph):
    with pytest.raises(IntegrityError, match="ck_track_layout_activity_type"), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO track_layout (track_location_id, name, activity_type,"
                " verified_length_m, length_verified_on)"
                " VALUES (:loc, 'X', 'DRAG_RACE', 100, '2026-01-01')"
            ),
            {"loc": base_graph["location"].id},
        )


# --- Planned and actual runs ------------------------------------------------


def test_planned_run_sequence_unique_within_test(session, base_graph):
    session.add(PlannedRun(test=base_graph["test"], sequence_number=1))
    session.commit()
    assert_rejected(
        session,
        "UNIQUE constraint failed: planned_run.test_id, planned_run.sequence_number",
        PlannedRun(test=base_graph["test"], sequence_number=1),
    )


def test_cancelled_planned_run_requires_reason(session, base_graph):
    plan = PlannedRun(test=base_graph["test"], sequence_number=1, status=PlannedRunStatus.CANCELLED)
    assert_rejected(session, "ck_planned_run_cancelled_requires_reason", plan)


def test_cancelled_planned_run_with_reason_is_preserved(session, base_graph):
    plan = PlannedRun(
        test=base_graph["test"],
        sequence_number=1,
        status=PlannedRunStatus.CANCELLED,
        cancellation_reason="Rain",
    )
    session.add(plan)
    session.commit()
    assert session.get(PlannedRun, plan.id).status is PlannedRunStatus.CANCELLED


def test_replaced_status_and_replacement_link_must_agree(session, base_graph):
    test = base_graph["test"]
    replaced_without_link = PlannedRun(
        test=test, sequence_number=1, status=PlannedRunStatus.REPLACED
    )
    assert_rejected(session, "ck_planned_run_replaced_iff_replacement", replaced_without_link)

    replacement = PlannedRun(test=test, sequence_number=2)
    session.add(replacement)
    session.commit()
    link_without_status = PlannedRun(test=test, sequence_number=1, replaced_by=replacement)
    assert_rejected(session, "ck_planned_run_replaced_iff_replacement", link_without_status)

    replaced = PlannedRun(
        test=test, sequence_number=1, status=PlannedRunStatus.REPLACED, replaced_by=replacement
    )
    session.add(replaced)
    session.commit()


def test_run_number_unique_within_test(session, base_graph):
    session.add(make_run(base_graph, run_number=1))
    session.commit()
    assert_rejected(
        session, "UNIQUE constraint failed: run.test_id, run.run_number", make_run(base_graph, 1)
    )


def test_planned_run_may_have_several_actual_runs_and_unexpected_runs_have_none(
    session, base_graph
):
    plan = PlannedRun(test=base_graph["test"], sequence_number=1, expected_lap_count=10)
    first_attempt = make_run(base_graph, 1, planned_run=plan, deviation_reason="Aborted: cone")
    retry = make_run(base_graph, 2, planned_run=plan)
    unexpected = make_run(base_graph, 3)
    session.add_all([plan, first_attempt, retry, unexpected])
    session.commit()

    session.expire_all()
    assert [r.run_number for r in session.get(PlannedRun, plan.id).runs] == [1, 2]
    assert session.get(Run, unexpected.id).planned_run_id is None


def test_run_with_missing_driver_violates_foreign_key(session, base_graph):
    run = Run(
        test=base_graph["test"],
        run_number=1,
        driver_id=999_999,
        track_layout=base_graph["layout"],
    )
    assert_rejected(session, "FOREIGN KEY constraint failed", run)


def test_run_end_cannot_precede_start(session, base_graph):
    start = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    run = make_run(base_graph, started_at=start, ended_at=start - timedelta(minutes=1))
    assert_rejected(session, "ck_run_time_order", run)


# --- Timestamps ---------------------------------------------------------------


def test_timestamps_are_normalised_to_utc_and_returned_aware(session, base_graph):
    cest = timezone(timedelta(hours=2))
    run = make_run(base_graph, started_at=datetime(2026, 3, 1, 11, 30, tzinfo=cest))
    session.add(run)
    session.commit()
    session.expire_all()

    stored = session.get(Run, run.id).started_at
    assert stored == datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
    assert stored.tzinfo is UTC


def test_naive_timestamp_is_rejected(session, base_graph):
    session.add(make_run(base_graph, started_at=datetime(2026, 3, 1, 9, 0)))
    with pytest.raises(StatementError, match="naive datetime rejected"):
        session.flush()
    session.rollback()


# --- Run conditions -----------------------------------------------------------


def test_temperatures_require_a_source(session, base_graph):
    run = make_run(base_graph)
    condition = RunCondition(run=run, asphalt_temperature_c=Decimal("34.5"))
    assert_rejected(session, "ck_run_condition_temperature_requires_source", run, condition)


def test_unavailable_conditions_are_stored_as_null_and_decimals_round_trip(session, base_graph):
    unknown = RunCondition(run=make_run(base_graph, 1))
    measured = RunCondition(
        run=make_run(base_graph, 2),
        ambient_temperature_c=Decimal("21.3"),
        asphalt_temperature_c=Decimal("34.5"),
        conditions_source=ConditionsSource.MEASURED,
    )
    session.add_all([unknown, measured])
    session.commit()
    session.expire_all()

    assert session.get(RunCondition, unknown.run_id).asphalt_temperature_c is None
    reloaded = session.get(RunCondition, measured.run_id)
    assert reloaded.asphalt_temperature_c == Decimal("34.5")
    assert reloaded.ambient_temperature_c == Decimal("21.3")


# --- Laps ---------------------------------------------------------------------


@pytest.mark.parametrize("raw_time_ms", [0, -1])
def test_lap_time_must_be_positive(session, base_graph, raw_time_ms):
    lap = make_lap(make_run(base_graph), raw_time_ms=raw_time_ms)
    assert_rejected(session, "ck_lap_raw_time_positive", lap)


def test_lap_number_must_be_positive(session, base_graph):
    assert_rejected(session, "ck_lap_lap_number_positive", make_lap(make_run(base_graph), 0))


def test_penalty_cannot_be_negative(session, base_graph):
    lap = make_lap(make_run(base_graph), penalty_duration_ms=-2000)
    assert_rejected(session, "ck_lap_penalty_non_negative", lap)


def test_lap_number_unique_within_run(session, base_graph):
    run = make_run(base_graph)
    session.add(make_lap(run, 1))
    session.commit()
    assert_rejected(
        session, "UNIQUE constraint failed: lap.run_id, lap.lap_number", make_lap(run, 1)
    )


def test_same_lap_number_allowed_in_different_runs(session, base_graph):
    session.add_all([make_lap(make_run(base_graph, 1), 1), make_lap(make_run(base_graph, 2), 1)])
    session.commit()


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_timing_invalid_lap_requires_reason(session, base_graph, reason):
    lap = make_lap(make_run(base_graph), timing_valid=False, invalidation_reason=reason)
    assert_rejected(session, "ck_lap_invalidation_reason_consistent", lap)


def test_valid_lap_cannot_carry_invalidation_reason(session, base_graph):
    lap = make_lap(make_run(base_graph), timing_valid=True, invalidation_reason="Cone")
    assert_rejected(session, "ck_lap_invalidation_reason_consistent", lap)


def test_untimed_lap_cannot_be_timing_valid(session, base_graph):
    lap = make_lap(make_run(base_graph), raw_time_ms=None, timing_valid=True)
    assert_rejected(session, "ck_lap_untimed_lap_not_valid", lap)


def test_timing_invalid_but_physically_completed_lap_is_stored(session, base_graph):
    run = make_run(base_graph)
    track_limits = make_lap(
        run, 1, timing_valid=False, invalidation_reason="Track limits", physically_completed=True
    )
    transponder_miss = make_lap(
        run,
        2,
        raw_time_ms=None,
        timing_valid=False,
        invalidation_reason="Transponder miss",
        physically_completed=True,
    )
    session.add_all([track_limits, transponder_miss])
    session.commit()
    assert session.get(Lap, transponder_miss.id).penalty_duration_ms == 0


def test_penalised_lap_stays_timing_valid(session, base_graph):
    lap = make_lap(make_run(base_graph), penalty_duration_ms=2000, timing_valid=True)
    session.add(lap)
    session.commit()
    assert session.get(Lap, lap.id).timing_valid is True


def test_aborted_lap_physical_completion_is_not_a_database_rule(session, base_graph):
    # Documented policy: ABORTED vs physical completion is decided at service level.
    run = make_run(base_graph)
    session.add_all(
        [
            make_lap(run, 1, lap_classification=LapClassification.ABORTED,
                     timing_valid=False, invalidation_reason="Aborted", physically_completed=False),
            make_lap(run, 2, lap_classification=LapClassification.ABORTED,
                     timing_valid=False, invalidation_reason="Lifted", physically_completed=True),
        ]
    )  # fmt: skip
    session.commit()


def test_invalid_lap_classification_rejected_by_database(engine, session, base_graph):
    run = make_run(base_graph)
    session.add(run)
    session.commit()
    with pytest.raises(IntegrityError, match="ck_lap_lap_classification"), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO lap (run_id, lap_number, lap_classification, raw_time_ms,"
                " timing_valid, physically_completed) VALUES (:run, 1, 'WARMUP', 1000, 1, 1)"
            ),
            {"run": run.id},
        )


def test_deleting_a_run_cascades_to_its_laps_and_conditions(engine, session, base_graph):
    run = make_run(base_graph)
    session.add_all([make_lap(run, 1), make_lap(run, 2), RunCondition(run=run)])
    session.commit()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM run WHERE id = :id"), {"id": run.id})
        assert conn.execute(text("SELECT count(*) FROM lap")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM run_condition")).scalar_one() == 0


def test_test_with_runs_cannot_be_deleted(engine, session, base_graph):
    session.add(make_run(base_graph))
    session.commit()
    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"), engine.begin() as c:
        c.execute(text("DELETE FROM test WHERE id = :id"), {"id": base_graph["test"].id})


# --- Setup snapshots ----------------------------------------------------------


def make_snapshot(graph, **overrides) -> SetupSnapshot:
    values = {"vehicle": graph["vehicle"], "power_limit_kw": Decimal("80.00")}
    values.update(overrides)
    return SetupSnapshot(**values)


def test_snapshot_gets_aware_creation_timestamp(session, base_graph):
    snapshot = make_snapshot(base_graph)
    session.add(snapshot)
    session.commit()
    session.expire_all()
    assert session.get(SetupSnapshot, snapshot.id).created_at.tzinfo is UTC


def test_one_corner_row_per_snapshot_and_corner(engine, session, base_graph):
    snapshot = make_snapshot(base_graph)
    session.add(SetupCornerParams(setup_snapshot=snapshot, corner=Corner.FL))
    session.commit()
    # Raw SQL: the ORM identity map would refuse the duplicate before the database sees it.
    with (
        pytest.raises(IntegrityError, match="UNIQUE constraint failed: setup_corner_params"),
        engine.begin() as conn,
    ):
        conn.execute(
            text("INSERT INTO setup_corner_params (setup_snapshot_id, corner) VALUES (:s, 'FL')"),
            {"s": snapshot.id},
        )


def test_invalid_corner_rejected_by_database(engine, session, base_graph):
    snapshot = make_snapshot(base_graph)
    session.add(snapshot)
    session.commit()
    with pytest.raises(IntegrityError, match="ck_setup_corner_params_corner"), engine.begin() as c:
        c.execute(
            text("INSERT INTO setup_corner_params (setup_snapshot_id, corner) VALUES (:s, 'XX')"),
            {"s": snapshot.id},
        )


def test_derived_snapshot_requires_change_reason(session, base_graph):
    parent = make_snapshot(base_graph)
    session.add(parent)
    session.commit()
    child = make_snapshot(base_graph, based_on=parent, power_limit_kw=Decimal("70"))
    assert_rejected(session, "ck_setup_snapshot_derived_requires_reason", child)


def test_spring_rate_must_be_positive(session, base_graph):
    corner = SetupCornerParams(
        setup_snapshot=make_snapshot(base_graph),
        corner=Corner.RR,
        spring_rate_n_per_mm=Decimal("0"),
    )
    assert_rejected(session, "ck_setup_corner_params_spring_rate_positive", corner)


def test_snapshot_is_reusable_across_runs_and_corners_round_trip(session, base_graph):
    snapshot = make_snapshot(base_graph, name="Autocross baseline")
    snapshot.corners = [
        SetupCornerParams(
            corner=corner,
            static_camber_deg=Decimal("-1.50"),
            static_toe_deg=Decimal("-0.100"),
            spring_rate_n_per_mm=Decimal("35.00"),
        )
        for corner in Corner
    ]
    session.add_all(
        [
            make_run(base_graph, 1, setup_snapshot=snapshot),
            make_run(base_graph, 2, setup_snapshot=snapshot),
        ]
    )
    session.commit()
    session.expire_all()

    runs = session.scalars(select(Run).where(Run.setup_snapshot_id == snapshot.id)).all()
    assert len(runs) == 2
    corners = session.get(SetupSnapshot, snapshot.id).corners
    assert [c.corner for c in corners] == [Corner.FL, Corner.FR, Corner.RL, Corner.RR]
    assert corners[0].static_toe_deg == Decimal("-0.100")
