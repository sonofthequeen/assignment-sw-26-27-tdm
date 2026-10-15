import re

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import create_db_engine
from app.models import Base
from tests.conftest import alembic_config, sqlite_url


def _normalise_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _schema_snapshot(engine) -> dict:
    """Everything that matters for integrity, in a comparable form."""
    insp = inspect(engine)
    snapshot = {}
    for table in sorted(insp.get_table_names()):
        if table == "alembic_version":
            continue
        snapshot[table] = {
            "columns": [
                (c["name"], str(c["type"]), c["nullable"], c["default"])
                for c in insp.get_columns(table)
            ],
            "pk": insp.get_pk_constraint(table),
            "fks": sorted(
                (
                    fk["name"],
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                    fk["options"].get("ondelete"),
                )
                for fk in insp.get_foreign_keys(table)
            ),
            "uniques": sorted(
                (u["name"], tuple(u["column_names"])) for u in insp.get_unique_constraints(table)
            ),
            "checks": sorted(
                (c["name"], _normalise_sql(c["sqltext"])) for c in insp.get_check_constraints(table)
            ),
            "indexes": sorted(
                (i["name"], tuple(i["column_names"]), bool(i["unique"]))
                for i in insp.get_indexes(table)
            ),
        }
    return snapshot


def test_upgrade_from_empty_database_creates_all_model_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert tables == set(Base.metadata.tables) | {"alembic_version"}
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    head = ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()
    assert version == head


def test_migration_schema_matches_orm_schema(engine, tmp_path):
    """Compares the migrated DB with a DB built from the models (CHECKs included).

    Alembic's compare_metadata ignores CHECK constraints, hence this explicit comparison.
    """
    orm_engine = create_db_engine(sqlite_url(tmp_path / "orm.sqlite3"))
    try:
        Base.metadata.create_all(orm_engine)
        migrated = _schema_snapshot(engine)
        from_models = _schema_snapshot(orm_engine)
    finally:
        orm_engine.dispose()
    assert migrated == from_models


def test_alembic_autogenerate_detects_no_drift(engine):
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_all_constraints_are_named(engine):
    snapshot = _schema_snapshot(engine)
    for table, schema in snapshot.items():
        assert schema["pk"]["name"] == f"pk_{table}"
        for kind in ("fks", "uniques", "checks", "indexes"):
            for entry in schema[kind]:
                assert entry[0], f"unnamed {kind} constraint on {table}"


def test_downgrade_to_base_then_upgrade_again(tmp_path):
    url = sqlite_url(tmp_path / "roundtrip.sqlite3")
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_db_engine(url)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
    command.upgrade(config, "head")


def test_foreign_keys_enabled_on_every_connection(engine):
    for _ in range(3):
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_foreign_key_violation_is_rejected(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO track_location (id, name) VALUES (1, 'Loc')"))
    with (
        pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"),
        engine.begin() as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO track_layout (track_location_id, name, activity_type,"
                " verified_length_m, length_verified_on)"
                " VALUES (999, 'Ghost', 'SKIDPAD', 50, '2026-01-01')"
            )
        )


def test_revision_0002_upgrade_preserves_existing_rows_and_downgrade_works(tmp_path):
    url = sqlite_url(tmp_path / "data.sqlite3")
    config = alembic_config(url)
    command.upgrade(config, "0001")
    engine = create_db_engine(url)
    try:
        with engine.begin() as conn:
            for statement in (
                "INSERT INTO season (id, name) VALUES (1, 'S')",
                "INSERT INTO vehicle (id, code, name) VALUES (1, 'V', 'V')",
                "INSERT INTO track_location (id, name) VALUES (1, 'L')",
                "INSERT INTO track_layout (id, track_location_id, name, activity_type,"
                " verified_length_m, length_verified_on) VALUES (1, 1, 'A', 'SKIDPAD', 50,"
                " '2026-01-01')",
                "INSERT INTO driver (id, code, full_name) VALUES (1, 'D', 'D')",
                "INSERT INTO test (id, season_id, vehicle_id, track_location_id, test_date, status)"
                " VALUES (1, 1, 1, 1, '2026-03-01', 'PLANNED')",
                "INSERT INTO planned_run (id, test_id, sequence_number, status, notes)"
                " VALUES (1, 1, 1, 'PLANNED', 'keep')",
                "INSERT INTO run (id, test_id, planned_run_id, run_number, driver_id,"
                " track_layout_id) VALUES (1, 1, 1, 1, 1, 1)",
            ):
                conn.execute(text(statement))

        command.upgrade(config, "head")
        with engine.connect() as conn:
            row = conn.execute(text("SELECT notes, replacement_reason FROM planned_run")).one()
            assert tuple(row) == ("keep", None)

        # Downgrade rebuilds planned_run while run rows reference it (FK handling in env.py).
        command.downgrade(config, "0001")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT notes FROM planned_run")).scalar_one() == "keep"
            assert conn.execute(text("SELECT planned_run_id FROM run")).scalar_one() == 1
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
            columns = {c["name"] for c in inspect(conn).get_columns("planned_run")}
            assert "replacement_reason" not in columns
            assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    finally:
        engine.dispose()


def test_revision_0003_adds_tyre_tables_without_touching_existing_data(tmp_path):
    url = sqlite_url(tmp_path / "phase6.sqlite3")
    config = alembic_config(url)
    command.upgrade(config, "0002")
    engine = create_db_engine(url)
    seed = (
        "INSERT INTO season (id, name) VALUES (1, 'S')",
        "INSERT INTO vehicle (id, code, name) VALUES (1, 'V', 'V')",
        "INSERT INTO track_location (id, name) VALUES (1, 'L')",
        "INSERT INTO track_layout (id, track_location_id, name, activity_type, verified_length_m,"
        " length_verified_on) VALUES (1, 1, 'A', 'AUTOCROSS', 1000, '2026-01-01')",
        "INSERT INTO driver (id, code, full_name) VALUES (1, 'D', 'D')",
        "INSERT INTO test (id, season_id, vehicle_id, track_location_id, test_date, status)"
        " VALUES (1, 1, 1, 1, '2026-03-01', 'PLANNED')",
        "INSERT INTO run (id, test_id, run_number, driver_id, track_layout_id)"
        " VALUES (1, 1, 1, 1, 1)",
        "INSERT INTO run_condition (run_id, asphalt_temperature_c, conditions_source)"
        " VALUES (1, 34.5, 'MEASURED')",
        "INSERT INTO lap (run_id, lap_number, lap_classification, raw_time_ms, timing_valid,"
        " physically_completed) VALUES (1, 1, 'FLYING', 65000, 1, 1)",
    )
    snapshot_query = "SELECT count(*) FROM lap"
    try:
        with engine.begin() as conn:
            for statement in seed:
                conn.execute(text(statement))

        command.upgrade(config, "head")
        with engine.begin() as conn:
            assert conn.execute(text(snapshot_query)).scalar_one() == 1
            assert (
                conn.execute(text("SELECT asphalt_temperature_c FROM run_condition")).scalar_one()
                == 34.5
            )
            conn.execute(
                text("INSERT INTO tire_compound (id, manufacturer, name) VALUES (1, 'M', 'C')")
            )
            conn.execute(
                text("INSERT INTO tire (id, serial_number, compound_id) VALUES (1, 'T', 1)")
            )
            conn.execute(
                text(
                    "INSERT INTO run_tire_assignment (run_id, corner, tire_id) VALUES (1, 'FL', 1)"
                )
            )

        command.downgrade(config, "0002")
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert not tables & {"tire", "tire_set", "tire_compound", "run_tire_assignment"}
            assert conn.execute(text(snapshot_query)).scalar_one() == 1
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
        command.upgrade(config, "head")
    finally:
        engine.dispose()
