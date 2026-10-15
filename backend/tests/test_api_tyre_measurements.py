"""Pre/post-run tyre measurements and alignment measurements."""

import pytest
from sqlalchemy import func, select

from app.models import AlignmentMeasurement, TireMeasurement
from tests.api_helpers import API, assert_error, test_context
from tests.tyre_helpers import CORNERS, add_run, create_compound, fit_four, tire_set_with_four


@pytest.fixture
def ctx(client):
    return test_context(client)


@pytest.fixture
def fitted_run(client, ctx):
    compound = create_compound(client)
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    assignments = fit_four(client, run["id"], tires)
    return {"run": run, "assignments": {a["corner"]: a for a in assignments}}


def count(app, model) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def tyre(corner="FL", phase="PRE_RUN", **values) -> dict:
    return {"corner": corner, "phase": phase, **values}


def post_tyre(client, run_id, *measurements):
    return client.post(
        f"{API}/runs/{run_id}/tire-measurements", json={"measurements": list(measurements)}
    )


def post_alignment(client, run_id, *measurements):
    return client.post(
        f"{API}/runs/{run_id}/alignment-measurements", json={"measurements": list(measurements)}
    )


FULL = {
    "pressure_kpa": "82.5",
    "temperature_inner_c": "64.0",
    "temperature_center_c": "61.5",
    "temperature_outer_c": "58.0",
}


# --- Tyre measurements --------------------------------------------------------------------


def test_pre_and_post_run_measurements_for_every_corner(client, fitted_run):
    run_id = fitted_run["run"]["id"]
    batch = [tyre(c, p, **FULL) for p in ("POST_RUN", "PRE_RUN") for c in reversed(CORNERS)]
    response = post_tyre(client, run_id, *batch)
    assert response.status_code == 201, response.json()
    rows = response.json()
    assert [(r["phase"], r["corner"]) for r in rows] == [("PRE_RUN", c) for c in CORNERS] + [
        ("POST_RUN", c) for c in CORNERS
    ]
    first = rows[0]
    assert {k: first[k] for k in FULL} == FULL
    assert first["tire_id"] == fitted_run["assignments"]["FL"]["tire_id"]
    assert client.get(f"{API}/runs/{run_id}/tire-measurements").json() == rows


def test_partial_measurement_keeps_missing_values_null(client, fitted_run):
    rows = post_tyre(client, fitted_run["run"]["id"], tyre(pressure_kpa="80.0")).json()
    assert rows[0]["pressure_kpa"] == "80.0"
    assert rows[0]["temperature_inner_c"] is None


def test_measurement_requires_a_fitted_tyre_at_that_corner(client, app, ctx):
    compound = create_compound(client)
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    client.post(
        f"{API}/runs/{run['id']}/tire-assignments",
        json={"assignments": [{"corner": "FL", "tire_id": tires[0]["id"]}]},
    )
    response = post_tyre(client, run["id"], tyre("FL", **FULL), tyre("RR", **FULL))
    error = assert_error(response, 422, "tire_assignment_not_found")
    assert error["details"][0]["field"] == "measurements.1.corner"
    assert count(app, TireMeasurement) == 0


def test_duplicate_measurement_conflicts(client, app, fitted_run):
    run_id = fitted_run["run"]["id"]
    post_tyre(client, run_id, tyre(**FULL))
    error = assert_error(
        post_tyre(client, run_id, tyre("FR", **FULL), tyre("FL", **FULL)),
        409,
        "tire_measurement_conflict",
    )
    assert error["details"] == [
        {"field": "measurements.1.phase", "issue": "FL PRE_RUN already exists."}
    ]
    assert count(app, TireMeasurement) == 1
    in_batch = post_tyre(client, run_id, tyre("RL", **FULL), tyre("RL", **FULL))
    assert_error(in_batch, 422, "duplicate_measurement_in_batch")


@pytest.mark.parametrize(
    ("values", "status_code", "code"),
    [
        ({}, 422, "invalid_tire_measurement"),  # nothing measured
        ({"pressure_kpa": "0"}, 422, "request_validation_failed"),
        ({"pressure_kpa": "-5"}, 422, "request_validation_failed"),
        ({"pressure_kpa": "82.55"}, 422, "request_validation_failed"),  # precision
        ({"pressure_kpa": "400.1"}, 422, "invalid_tire_measurement"),
        ({"temperature_center_c": "150.1"}, 422, "invalid_tire_measurement"),
        ({"temperature_outer_c": "-30.1"}, 422, "invalid_tire_measurement"),
        ({"temperature_inner_c": "1000.0"}, 422, "request_validation_failed"),
        ({"pressure_psi": "12"}, 422, "request_validation_failed"),
    ],
)
def test_invalid_tyre_measurements_persist_nothing(
    client, app, fitted_run, values, status_code, code
):
    response = post_tyre(client, fitted_run["run"]["id"], tyre("FR", **FULL), tyre("FL", **values))
    assert_error(response, status_code, code)
    assert count(app, TireMeasurement) == 0


@pytest.mark.parametrize(
    "values",
    [{"pressure_kpa": "400.0"}, {"temperature_inner_c": "150.0"}, {"temperature_outer_c": "-30.0"}],
)
def test_policy_bounds_are_inclusive(client, fitted_run, values):
    assert post_tyre(client, fitted_run["run"]["id"], tyre(**values)).status_code == 201


def test_invalid_phase_and_missing_run(client, fitted_run):
    response = post_tyre(client, fitted_run["run"]["id"], tyre(phase="MID_RUN", **FULL))
    assert_error(response, 422, "request_validation_failed")
    assert_error(post_tyre(client, 999, tyre(**FULL)), 404, "run_not_found")
    assert_error(post_tyre(client, fitted_run["run"]["id"]), 422, "empty_measurement_batch")


# --- Alignment ------------------------------------------------------------------------------


def test_alignment_pre_and_post_with_partial_values(client, ctx):
    run = add_run(client, ctx)  # alignment needs no tyre assignment
    response = post_alignment(
        client,
        run["id"],
        {"corner": "RR", "phase": "POST_RUN", "camber_deg": "-1.80", "toe_deg": "0.050"},
        {"corner": "FL", "phase": "PRE_RUN", "camber_deg": "-1.50"},
        {"corner": "FL", "phase": "POST_RUN", "toe_deg": "-0.100"},
    )
    assert response.status_code == 201, response.json()
    rows = response.json()
    assert [(r["phase"], r["corner"]) for r in rows] == [
        ("PRE_RUN", "FL"),
        ("POST_RUN", "FL"),
        ("POST_RUN", "RR"),
    ]
    assert (rows[0]["camber_deg"], rows[0]["toe_deg"]) == ("-1.50", None)
    assert (rows[1]["camber_deg"], rows[1]["toe_deg"]) == (None, "-0.100")
    assert client.get(f"{API}/runs/{run['id']}/alignment-measurements").json() == rows


@pytest.mark.parametrize(
    ("measurement", "code"),
    [
        ({"corner": "FL", "phase": "PRE_RUN"}, "invalid_alignment_measurement"),
        (
            {"corner": "FL", "phase": "PRE_RUN", "camber_deg": "-10.01"},
            "invalid_alignment_measurement",
        ),
        ({"corner": "FL", "phase": "PRE_RUN", "toe_deg": "5.001"}, "invalid_alignment_measurement"),
        ({"corner": "FL", "phase": "PRE_RUN", "camber_deg": "-1.234"}, "request_validation_failed"),
        ({"corner": "XX", "phase": "PRE_RUN", "camber_deg": "-1"}, "request_validation_failed"),
    ],
)
def test_invalid_alignment_is_rejected(client, app, ctx, measurement, code):
    run = add_run(client, ctx)
    assert_error(post_alignment(client, run["id"], measurement), 422, code)
    assert count(app, AlignmentMeasurement) == 0


def test_duplicate_alignment_conflicts(client, ctx):
    run = add_run(client, ctx)
    entry = {"corner": "FL", "phase": "PRE_RUN", "camber_deg": "-1.50"}
    post_alignment(client, run["id"], entry)
    assert_error(post_alignment(client, run["id"], entry), 409, "alignment_measurement_conflict")


def test_alignment_does_not_change_the_setup_snapshot(client, ctx):
    snapshot = client.post(
        f"{API}/setup-snapshots",
        json={
            "vehicle_id": ctx["vehicle"]["id"],
            "corners": [{"corner": "FL", "static_camber_deg": "-1.50"}],
        },
    ).json()
    run = add_run(client, ctx, setup_snapshot_id=snapshot["id"])
    post_alignment(client, run["id"], {"corner": "FL", "phase": "POST_RUN", "camber_deg": "-2.10"})
    assert client.get(f"{API}/setup-snapshots/{snapshot['id']}").json() == snapshot
