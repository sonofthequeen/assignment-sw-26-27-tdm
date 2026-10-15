import re

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
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
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001"


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
