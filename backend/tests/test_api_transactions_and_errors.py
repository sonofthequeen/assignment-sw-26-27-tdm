"""Transaction ownership, rollback, error translation and FK enforcement in API sessions."""

from datetime import date

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.errors import translate_integrity_error
from app.models import Driver, PlannedRun, Season, Test, TrackLayout
from tests.api_helpers import API, assert_error, create_layout, create_location, test_context


def count(app, model) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_failed_multi_entity_create_rolls_back_everything(client, app):
    """The test row is flushed before the 3rd planned run fails validation; nothing persists."""
    ctx = test_context(client)
    elsewhere = create_layout(client, create_location(client, "Elsewhere")["id"])
    tests_before, plans_before = count(app, Test), count(app, PlannedRun)

    response = client.post(
        f"{API}/tests",
        json={
            "season_id": ctx["season"]["id"],
            "vehicle_id": ctx["vehicle"]["id"],
            "track_location_id": ctx["location"]["id"],
            "test_date": "2026-06-01",
            "planned_runs": [
                {"sequence_number": 1},
                {"sequence_number": 2},
                {"sequence_number": 3, "expected_track_layout_id": elsewhere["id"]},
            ],
        },
    )

    error = assert_error(response, 422, "track_layout_not_at_test_location")
    assert error["details"][0]["field"] == "planned_runs.2.expected_track_layout_id"
    assert count(app, Test) == tests_before
    assert count(app, PlannedRun) == plans_before


def test_commit_failure_is_reported_and_nothing_is_persisted(client, app):
    """The session dependency finishes the transaction before the response is sent."""

    def fail_commit(session):
        raise RuntimeError("simulated commit failure")

    event.listen(app.state.session_factory, "before_commit", fail_commit)
    try:
        response = client.post(f"{API}/seasons", json={"name": "Never stored"})
    finally:
        event.remove(app.state.session_factory, "before_commit", fail_commit)

    error = assert_error(response, 500, "internal_error")
    assert error["message"] == "An unexpected error occurred."
    assert "simulated" not in response.text and "Traceback" not in response.text
    assert count(app, Season) == 0


def test_successful_request_commits(client, app):
    client.post(f"{API}/seasons", json={"name": "Stored"})
    assert count(app, Season) == 1


def test_api_sessions_enforce_foreign_keys(app):
    # Same session factory the request dependency uses.
    with app.state.session_factory() as session:
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        session.add(
            TrackLayout(
                track_location_id=999,
                name="Ghost",
                activity_type="SKIDPAD",
                verified_length_m=50,
                length_verified_on=date(2026, 1, 1),
            )
        )
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            session.flush()


def test_malformed_json_returns_standard_422(client):
    response = client.post(
        f"{API}/seasons", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert_error(response, 422, "request_validation_failed")


# --- IntegrityError translation (centralised, tested against real SQLite errors) ---


def integrity_error_from(app, *statements) -> IntegrityError:
    with app.state.session_factory() as session:
        try:
            for statement in statements:
                session.execute(text(statement))
            session.flush()
        except IntegrityError as exc:
            return exc
    raise AssertionError("expected an IntegrityError")


def test_unique_violation_is_mapped_by_constraint(app):
    exc = integrity_error_from(
        app,
        "INSERT INTO driver (code, full_name) VALUES ('X', 'A')",
        "INSERT INTO driver (code, full_name) VALUES ('X', 'B')",
    )
    translated = translate_integrity_error(exc)
    assert (translated.status_code, translated.code) == (409, "driver_code_taken")


def test_composite_unique_violation_is_mapped(app):
    exc = integrity_error_from(
        app,
        "INSERT INTO track_location (id, name) VALUES (1, 'L')",
        "INSERT INTO track_layout (track_location_id, name, activity_type, verified_length_m,"
        " length_verified_on) VALUES (1, 'A', 'SKIDPAD', 50, '2026-01-01')",
        "INSERT INTO track_layout (track_location_id, name, activity_type, verified_length_m,"
        " length_verified_on) VALUES (1, 'A', 'SKIDPAD', 60, '2026-01-01')",
    )
    assert translate_integrity_error(exc).code == "track_layout_name_taken"


def test_known_check_violation_maps_to_field_level_422(app):
    exc = integrity_error_from(
        app,
        "INSERT INTO track_location (id, name) VALUES (1, 'L')",
        "INSERT INTO track_layout (track_location_id, name, activity_type, verified_length_m,"
        " length_verified_on) VALUES (1, 'A', 'SKIDPAD', 0, '2026-01-01')",
    )
    translated = translate_integrity_error(exc)
    assert (translated.status_code, translated.code) == (422, "constraint_violation")
    assert translated.details[0].field == "verified_length_m"


def test_registered_check_names_its_field(app):
    exc = integrity_error_from(
        app,
        "INSERT INTO season (name, starts_on, ends_on) VALUES ('S', '2026-02-01', '2026-01-01')",
    )
    translated = translate_integrity_error(exc)
    assert (translated.status_code, translated.details[0].field) == (422, "ends_on")


RUN_GRAPH = (
    "INSERT INTO season (id, name) VALUES (1, 'S')",
    "INSERT INTO vehicle (id, code, name) VALUES (1, 'V', 'V')",
    "INSERT INTO track_location (id, name) VALUES (1, 'L')",
    "INSERT INTO track_layout (id, track_location_id, name, activity_type, verified_length_m,"
    " length_verified_on) VALUES (1, 1, 'A', 'SKIDPAD', 50, '2026-01-01')",
    "INSERT INTO driver (id, code, full_name) VALUES (1, 'D', 'D')",
    "INSERT INTO test (id, season_id, vehicle_id, track_location_id, test_date, status)"
    " VALUES (1, 1, 1, 1, '2026-03-01', 'PLANNED')",
)


def test_unregistered_check_gets_generic_422_without_details(app):
    exc = integrity_error_from(
        app,
        *RUN_GRAPH,
        "INSERT INTO run (id, test_id, run_number, driver_id, track_layout_id)"
        " VALUES (1, 1, 1, 1, 1)",
        "INSERT INTO lap (run_id, lap_number, lap_classification, raw_time_ms, timing_valid,"
        " physically_completed) VALUES (1, 1, 'FLYING', -5, 1, 1)",
    )
    translated = translate_integrity_error(exc)
    assert (translated.status_code, translated.code, translated.details) == (
        422,
        "constraint_violation",
        (),
    )


def test_foreign_key_violation_gets_generic_reference_error(app):
    exc = integrity_error_from(
        app,
        *RUN_GRAPH,
        "INSERT INTO run (test_id, run_number, driver_id, track_layout_id) VALUES (77, 1, 1, 1)",
    )
    translated = translate_integrity_error(exc)
    assert (translated.status_code, translated.code) == (422, "referenced_resource_not_found")


def test_every_registered_constraint_name_exists_in_the_schema():
    from app.errors import KNOWN_CONSTRAINTS
    from app.models import Base

    names = {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
    }
    assert set(KNOWN_CONSTRAINTS) <= names


def test_driver_rows_untouched_by_failed_requests(client, app):
    client.post(f"{API}/drivers", json={"code": "A", "full_name": "A"})
    client.post(f"{API}/drivers", json={"code": "A", "full_name": "Duplicate"})
    with app.state.session_factory() as session:
        assert [d.full_name for d in session.scalars(select(Driver))] == ["A"]
