"""Test databases are real SQLite files built by the Alembic migration.

A template database is migrated once per session and copied for every test, so
each test gets an isolated, file-backed database with the same connection
behaviour (PRAGMA foreign_keys per connection) as the application.
"""

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.database import create_db_engine, create_session_factory
from app.models import (
    ActivityType,
    Driver,
    Season,
    Test,
    TrackLayout,
    TrackLocation,
    Vehicle,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("template") / "template.sqlite3"
    command.upgrade(alembic_config(sqlite_url(path)), "head")
    return path


@pytest.fixture
def db_url(migrated_template, tmp_path) -> str:
    path = tmp_path / "test.sqlite3"
    shutil.copyfile(migrated_template, path)
    return sqlite_url(path)


@pytest.fixture
def engine(db_url):
    engine = create_db_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    factory = create_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture
def base_graph(session):
    """Minimal valid reference graph: one season, vehicle, driver, location, layout, test."""
    season = Season(name="Season A")
    vehicle = Vehicle(code="VEH-A", name="Vehicle A")
    driver = Driver(code="DRV-A", full_name="Driver A")
    location = TrackLocation(name="Location A")
    layout = TrackLayout(
        track_location=location,
        name="Autocross loop",
        activity_type=ActivityType.AUTOCROSS,
        verified_length_m=Decimal("1000.000"),
        length_verified_on=date(2026, 1, 1),
    )
    test = Test(season=season, vehicle=vehicle, track_location=location, test_date=date(2026, 3, 1))
    session.add_all([season, vehicle, driver, location, layout, test])
    session.commit()
    return {
        "season": season,
        "vehicle": vehicle,
        "driver": driver,
        "location": location,
        "layout": layout,
        "test": test,
    }
