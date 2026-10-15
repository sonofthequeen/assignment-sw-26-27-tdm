"""FastAPI application factory.

Run locally with:  uvicorn app.main:create_app --factory --reload   (from backend/)
The schema is created by Alembic migrations only; the app never calls create_all.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import create_db_engine, create_session_factory
from app.errors import register_exception_handlers
from app.routers import api_router

API_PREFIX = "/api/v1"

DESCRIPTION = """
Race UP **Test Data Manager**: a traceable engineering history of Formula Student
testing, organised as **Season → Test → Run → Lap**.

In this API, *run* always means an actual on-track run of the vehicle.
Units are part of field names (`_m`, `_ms`, `_kwh`, …). Decimal quantities are
serialised as JSON strings to preserve precision. Timestamps are ISO 8601 with offset.

Errors always use `{"error": {"code", "message", "details": [{"field", "issue"}]}}`.
"""

OPENAPI_TAGS = [
    {"name": "seasons", "description": "Testing seasons."},
    {"name": "vehicles", "description": "Vehicles / vehicle generations."},
    {"name": "drivers", "description": "Drivers."},
    {"name": "tracks", "description": "Track locations and layouts with verified lap lengths."},
    {"name": "tests", "description": "Test days: the context for planned and actual runs."},
    {"name": "planned runs", "description": "The pre-test run plan, preserved unchanged."},
    {"name": "runs", "description": "Actual on-track runs, planned or unexpected."},
    {
        "name": "setup snapshots",
        "description": "Append-only vehicle setups: create, derive a change, compare.",
    },
    {"name": "run conditions", "description": "Ambient/asphalt conditions per run (write-once)."},
    {"name": "laps", "description": "Lap records, effective time and fastest eligible lap."},
    {"name": "mileage", "description": "Derived distance per run, test, season, vehicle, driver."},
    {"name": "analytics", "description": "Read-only rankings over historical laps."},
    {"name": "tyres", "description": "Compounds, tyre sets and physical tyres (one row per tyre)."},
    {"name": "tyre fitment", "description": "Which physical tyre was on which corner of a run."},
    {"name": "measurements", "description": "Pre/post-run tyre and alignment measurements."},
    {"name": "objectives", "description": "Season objectives linked to tests and runs."},
    {"name": "files", "description": "Index of telemetry/log files stored elsewhere."},
]


def create_app(database_url: str | None = None) -> FastAPI:
    engine = create_db_engine(database_url or get_settings().database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(
        title="Race UP Test Data Manager",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app
