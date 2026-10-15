"""Database-level tyre invariants (raw SQL bypasses the service on purpose)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def db(engine, base_graph):
    run_sql = (
        "INSERT INTO run (id, test_id, run_number, driver_id, track_layout_id)"
        f" VALUES (1, {base_graph['test'].id}, 1, {base_graph['driver'].id},"
        f" {base_graph['layout'].id})"
    )
    with engine.begin() as conn:
        for statement in (
            run_sql,
            "INSERT INTO tire_compound (id, manufacturer, name) VALUES (1, 'M', 'SOFT')",
            "INSERT INTO tire_compound (id, manufacturer, name) VALUES (2, 'M', 'HARD')",
            "INSERT INTO tire_set (id, set_code, compound_id) VALUES (1, 'S1', 1)",
            "INSERT INTO tire (id, serial_number, compound_id, tire_set_id) VALUES (1, 'T1', 1, 1)",
            "INSERT INTO tire (id, serial_number, compound_id, tire_set_id) VALUES (2, 'T2', 1, 1)",
            "INSERT INTO run_tire_assignment (run_id, corner, tire_id) VALUES (1, 'FL', 1)",
        ):
            conn.execute(text(statement))
    return engine


def rejected(engine, statement: str, match: str) -> None:
    with pytest.raises(IntegrityError, match=match), engine.begin() as conn:
        conn.execute(text(statement))


def test_tyre_compound_must_match_its_set_compound(db):
    rejected(
        db,
        "INSERT INTO tire (serial_number, compound_id, tire_set_id) VALUES ('T3', 2, 1)",
        "FOREIGN KEY constraint failed",
    )


def test_standalone_tyre_needs_only_a_compound(db):
    with db.begin() as conn:
        conn.execute(text("INSERT INTO tire (serial_number, compound_id) VALUES ('SPARE', 2)"))


def test_serial_number_unique(db):
    rejected(db, "INSERT INTO tire (serial_number, compound_id) VALUES ('T1', 1)", "UNIQUE")


def test_one_tyre_per_corner_and_one_corner_per_tyre(db):
    rejected(
        db,
        "INSERT INTO run_tire_assignment (run_id, corner, tire_id) VALUES (1, 'FL', 2)",
        "UNIQUE constraint failed: run_tire_assignment.run_id, run_tire_assignment.corner",
    )
    rejected(
        db,
        "INSERT INTO run_tire_assignment (run_id, corner, tire_id) VALUES (1, 'FR', 1)",
        "UNIQUE constraint failed: run_tire_assignment.run_id, run_tire_assignment.tire_id",
    )


def test_invalid_corner_rejected(db):
    rejected(
        db,
        "INSERT INTO run_tire_assignment (run_id, corner, tire_id) VALUES (1, 'XX', 2)",
        "ck_run_tire_assignment_corner",
    )


def test_measurement_requires_assignment_at_that_corner(db):
    rejected(
        db,
        "INSERT INTO tire_measurement (run_id, corner, phase, pressure_kpa)"
        " VALUES (1, 'RR', 'PRE_RUN', 80)",
        "FOREIGN KEY constraint failed",
    )


def test_measurement_value_phase_and_uniqueness_rules(db):
    rejected(
        db,
        "INSERT INTO tire_measurement (run_id, corner, phase) VALUES (1, 'FL', 'PRE_RUN')",
        "ck_tire_measurement_has_a_value",
    )
    rejected(
        db,
        "INSERT INTO tire_measurement (run_id, corner, phase, pressure_kpa)"
        " VALUES (1, 'FL', 'PRE_RUN', 0)",
        "ck_tire_measurement_pressure_positive",
    )
    rejected(
        db,
        "INSERT INTO tire_measurement (run_id, corner, phase, pressure_kpa)"
        " VALUES (1, 'FL', 'MID', 80)",
        "ck_tire_measurement_phase",
    )
    insert = (
        "INSERT INTO tire_measurement (run_id, corner, phase, pressure_kpa)"
        " VALUES (1, 'FL', 'PRE_RUN', 80)"
    )
    with db.begin() as conn:
        conn.execute(text(insert))
    rejected(db, insert, "UNIQUE")


def test_alignment_needs_a_value_and_is_unique_per_phase(db):
    rejected(
        db,
        "INSERT INTO alignment_measurement (run_id, corner, phase) VALUES (1, 'FL', 'PRE_RUN')",
        "ck_alignment_measurement_has_a_value",
    )
    insert = (
        "INSERT INTO alignment_measurement (run_id, corner, phase, camber_deg)"
        " VALUES (1, 'FL', 'PRE_RUN', -1.5)"
    )
    with db.begin() as conn:
        conn.execute(text(insert))
    rejected(db, insert, "UNIQUE")


def test_referenced_tyre_cannot_be_deleted(db):
    rejected(db, "DELETE FROM tire WHERE id = 1", "FOREIGN KEY constraint failed")
