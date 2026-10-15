"""Tests, planned runs and actual runs, including service-layer cross-row rules."""

from decimal import Decimal

import pytest

from app.models import SetupSnapshot
from tests.api_helpers import (
    API,
    assert_error,
    create_driver,
    create_layout,
    create_location,
    create_season,
    create_test,
    create_vehicle,
    test_context,
)


@pytest.fixture
def ctx(client):
    return test_context(client)


def add_snapshot(app, vehicle_id: int) -> int:
    """Setup snapshots have no API until Phase 4; insert one directly."""
    with app.state.session_factory.begin() as session:
        snapshot = SetupSnapshot(vehicle_id=vehicle_id, power_limit_kw=Decimal("80"))
        session.add(snapshot)
        session.flush()
        return snapshot.id


# --- Tests --------------------------------------------------------------------


def test_create_test_returns_detail_with_references(client, ctx):
    test = ctx["test"]
    assert test["status"] == "PLANNED"
    assert test["season"] == {"id": ctx["season"]["id"], "name": "Season A"}
    assert test["vehicle"] == {"id": ctx["vehicle"]["id"], "code": "VEH-A", "name": "Vehicle A"}
    assert test["track_location"] == {"id": ctx["location"]["id"], "name": "Location A"}
    assert test["planned_runs"] == []
    assert client.get(f"{API}/tests/{test['id']}").json() == test


@pytest.mark.parametrize(
    ("field", "resource"),
    [("season_id", "Season"), ("vehicle_id", "Vehicle"), ("track_location_id", "Track location")],
)
def test_create_test_rejects_missing_references(client, ctx, field, resource):
    payload = {
        "season_id": ctx["season"]["id"],
        "vehicle_id": ctx["vehicle"]["id"],
        "track_location_id": ctx["location"]["id"],
        "test_date": "2026-03-02",
        field: 999,
    }
    error = assert_error(
        client.post(f"{API}/tests", json=payload), 422, "referenced_resource_not_found"
    )
    assert error["details"] == [{"field": field, "issue": f"{resource} 999 does not exist."}]


def test_create_test_with_run_plan_in_one_request(client, ctx):
    response = client.post(
        f"{API}/tests",
        json={
            "season_id": ctx["season"]["id"],
            "vehicle_id": ctx["vehicle"]["id"],
            "track_location_id": ctx["location"]["id"],
            "test_date": "2026-04-01",
            "planned_runs": [
                {"sequence_number": 2, "expected_lap_count": 10},
                {
                    "sequence_number": 1,
                    "expected_driver_id": ctx["driver"]["id"],
                    "expected_track_layout_id": ctx["layout"]["id"],
                    "target_lap_time_ms": 61_500,
                    "expected_energy_limit_kwh": "4.500",
                    "expected_control_map": "MAP-ENDU",
                },
            ],
        },
    )
    assert response.status_code == 201, response.json()
    plans = response.json()["planned_runs"]
    assert [p["sequence_number"] for p in plans] == [1, 2]
    assert all(p["status"] == "PLANNED" for p in plans)
    assert plans[0]["expected_energy_limit_kwh"] == "4.500"


def test_inline_plan_with_duplicate_sequence_numbers_is_rejected(client, ctx):
    response = client.post(
        f"{API}/tests",
        json={
            "season_id": ctx["season"]["id"],
            "vehicle_id": ctx["vehicle"]["id"],
            "track_location_id": ctx["location"]["id"],
            "test_date": "2026-04-01",
            "planned_runs": [{"sequence_number": 1}, {"sequence_number": 1}],
        },
    )
    assert_error(response, 422, "request_validation_failed")


def test_list_tests_newest_first_with_filters(client):
    season_a = create_season(client, "A")
    season_b = create_season(client, "B")
    car_1 = create_vehicle(client, "CAR-1")
    car_2 = create_vehicle(client, "CAR-2")
    track = create_location(client, "Track")
    other_track = create_location(client, "Other")

    t1 = create_test(client, season_a["id"], car_1["id"], track["id"], "2026-03-01")
    t2 = create_test(client, season_a["id"], car_2["id"], track["id"], "2026-03-15")
    t3 = create_test(client, season_b["id"], car_1["id"], other_track["id"], "2026-03-15")
    t4 = create_test(
        client, season_b["id"], car_1["id"], track["id"], "2026-05-01", status="COMPLETED"
    )

    def ids(**params):
        page = client.get(f"{API}/tests", params=params).json()
        return [t["id"] for t in page["items"]]

    assert ids() == [t4["id"], t3["id"], t2["id"], t1["id"]]  # date desc, then id desc
    assert ids(season_id=season_a["id"]) == [t2["id"], t1["id"]]
    assert ids(vehicle_id=car_1["id"]) == [t4["id"], t3["id"], t1["id"]]
    assert ids(track_location_id=other_track["id"]) == [t3["id"]]
    assert ids(date_from="2026-03-10", date_to="2026-03-31") == [t3["id"], t2["id"]]
    assert ids(status="COMPLETED") == [t4["id"]]
    assert ids(season_id=season_b["id"], vehicle_id=car_1["id"], track_location_id=track["id"]) == [
        t4["id"]
    ]
    page = client.get(f"{API}/tests").json()
    assert page["order_by"] == ["test_date desc", "id desc"]
    assert "planned_runs" not in page["items"][0]  # summaries stay compact


def test_inverted_date_range_is_rejected(client):
    assert_error(
        client.get(f"{API}/tests", params={"date_from": "2026-05-01", "date_to": "2026-01-01"}),
        422,
        "request_validation_failed",
    )


def test_missing_test_returns_404(client):
    assert_error(client.get(f"{API}/tests/12345"), 404, "test_not_found")


# --- Planned runs ---------------------------------------------------------------


def test_create_get_and_list_planned_runs(client, ctx):
    test_id = ctx["test"]["id"]
    second = client.post(f"{API}/tests/{test_id}/planned-runs", json={"sequence_number": 2})
    first = client.post(
        f"{API}/tests/{test_id}/planned-runs",
        json={"sequence_number": 1, "expected_driver_id": ctx["driver"]["id"]},
    )
    assert second.status_code == first.status_code == 201
    plan = first.json()
    assert plan["status"] == "PLANNED" and plan["test_id"] == test_id
    detail = client.get(f"{API}/planned-runs/{plan['id']}").json()
    assert {key: detail[key] for key in plan} == plan  # detail extends the create response
    assert (detail["replaces"], detail["runs"]) == ([], [])

    page = client.get(f"{API}/tests/{test_id}/planned-runs").json()
    assert [p["sequence_number"] for p in page["items"]] == [1, 2]
    assert page["order_by"] == ["sequence_number asc", "id asc"]


def test_planned_run_for_missing_test_returns_404(client):
    response = client.post(f"{API}/tests/999/planned-runs", json={"sequence_number": 1})
    assert_error(response, 404, "test_not_found")
    assert_error(client.get(f"{API}/tests/999/planned-runs"), 404, "test_not_found")
    assert_error(client.get(f"{API}/planned-runs/999"), 404, "planned_run_not_found")


def test_planned_run_sequence_number_unique_within_test(client, ctx):
    path = f"{API}/tests/{ctx['test']['id']}/planned-runs"
    assert client.post(path, json={"sequence_number": 1}).status_code == 201
    assert_error(client.post(path, json={"sequence_number": 1}), 409, "planned_run_sequence_taken")


def test_planned_run_status_cannot_be_set_on_create(client, ctx):
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/planned-runs",
        json={"sequence_number": 1, "status": "CANCELLED", "cancellation_reason": "Rain"},
    )
    assert_error(response, 422, "request_validation_failed")


def test_planned_run_layout_must_be_at_test_location(client, ctx):
    elsewhere = create_layout(client, create_location(client, "Elsewhere")["id"])
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/planned-runs",
        json={"sequence_number": 1, "expected_track_layout_id": elsewhere["id"]},
    )
    error = assert_error(response, 422, "track_layout_not_at_test_location")
    assert error["details"][0]["field"] == "expected_track_layout_id"


# --- Actual runs ----------------------------------------------------------------


def run_payload(ctx, **overrides) -> dict:
    return {
        "run_number": 1,
        "driver_id": ctx["driver"]["id"],
        "track_layout_id": ctx["layout"]["id"],
        **overrides,
    }


def test_run_linked_to_planned_run_of_same_test(client, ctx):
    test_id = ctx["test"]["id"]
    plan = client.post(f"{API}/tests/{test_id}/planned-runs", json={"sequence_number": 1}).json()
    response = client.post(
        f"{API}/tests/{test_id}/runs",
        json=run_payload(
            ctx,
            planned_run_id=plan["id"],
            started_at="2026-03-01T11:30:00+02:00",
            ended_at="2026-03-01T11:52:00+02:00",
        ),
    )
    assert response.status_code == 201, response.json()
    run = response.json()
    assert run["planned_run_id"] == plan["id"]
    assert run["started_at"] == "2026-03-01T09:30:00Z"
    assert run["driver"] == {"id": ctx["driver"]["id"], "code": "DRV-A", "full_name": "Driver A"}
    assert run["track_layout"]["verified_length_m"] == "1000.000"
    assert client.get(f"{API}/runs/{run['id']}").json() == run


def test_several_attempts_may_reference_one_planned_run(client, ctx):
    test_id = ctx["test"]["id"]
    plan = client.post(f"{API}/tests/{test_id}/planned-runs", json={"sequence_number": 1}).json()
    for number in (1, 2):
        response = client.post(
            f"{API}/tests/{test_id}/runs",
            json=run_payload(ctx, run_number=number, planned_run_id=plan["id"]),
        )
        assert response.status_code == 201


def test_unexpected_run_has_no_planned_run(client, ctx):
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs",
        json=run_payload(ctx, deviation_reason="Extra shakedown run"),
    )
    assert response.status_code == 201
    assert response.json()["planned_run_id"] is None


def test_run_rejects_planned_run_from_another_test(client, ctx):
    other_test = create_test(
        client, ctx["season"]["id"], ctx["vehicle"]["id"], ctx["location"]["id"], "2026-03-02"
    )
    foreign_plan = client.post(
        f"{API}/tests/{other_test['id']}/planned-runs", json={"sequence_number": 1}
    ).json()
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs",
        json=run_payload(ctx, planned_run_id=foreign_plan["id"]),
    )
    error = assert_error(response, 422, "planned_run_not_in_test")
    assert error["details"][0]["field"] == "planned_run_id"


def test_run_rejects_layout_at_another_location(client, ctx):
    elsewhere = create_layout(client, create_location(client, "Elsewhere")["id"])
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs",
        json=run_payload(ctx, track_layout_id=elsewhere["id"]),
    )
    assert_error(response, 422, "track_layout_not_at_test_location")


def test_run_rejects_setup_snapshot_of_another_vehicle(client, app, ctx):
    other_vehicle = create_vehicle(client, "OTHER")
    foreign_snapshot = add_snapshot(app, other_vehicle["id"])
    own_snapshot = add_snapshot(app, ctx["vehicle"]["id"])
    path = f"{API}/tests/{ctx['test']['id']}/runs"

    response = client.post(path, json=run_payload(ctx, setup_snapshot_id=foreign_snapshot))
    assert_error(response, 422, "setup_snapshot_vehicle_mismatch")

    response = client.post(path, json=run_payload(ctx, setup_snapshot_id=own_snapshot))
    assert response.status_code == 201
    assert response.json()["setup_snapshot_id"] == own_snapshot


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"driver_id": 999}, "driver_id"),
        ({"track_layout_id": 999}, "track_layout_id"),
        ({"planned_run_id": 999}, "planned_run_id"),
        ({"setup_snapshot_id": 999}, "setup_snapshot_id"),
    ],
)
def test_run_rejects_missing_references(client, ctx, override, field):
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs", json=run_payload(ctx, **override)
    )
    error = assert_error(response, 422, "referenced_resource_not_found")
    assert error["details"][0]["field"] == field


def test_run_number_unique_within_test_but_not_across_tests(client, ctx):
    path = f"{API}/tests/{ctx['test']['id']}/runs"
    assert client.post(path, json=run_payload(ctx)).status_code == 201
    assert_error(client.post(path, json=run_payload(ctx)), 409, "run_number_taken")

    other_test = create_test(
        client, ctx["season"]["id"], ctx["vehicle"]["id"], ctx["location"]["id"], "2026-03-02"
    )
    other = client.post(f"{API}/tests/{other_test['id']}/runs", json=run_payload(ctx))
    assert other.status_code == 201


@pytest.mark.parametrize(
    "override",
    [
        {"started_at": "2026-03-01T09:00:00"},  # naive timestamp
        {"started_at": "2026-03-01T10:00:00Z", "ended_at": "2026-03-01T09:00:00Z"},
        {"run_number": 0},
        {"deviation_reason": "   "},
    ],
)
def test_invalid_run_payloads_are_rejected(client, ctx, override):
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs", json=run_payload(ctx, **override)
    )
    assert_error(response, 422, "request_validation_failed")


def test_list_runs_in_run_number_order(client, ctx):
    path = f"{API}/tests/{ctx['test']['id']}/runs"
    for number in (3, 1, 2):
        client.post(path, json=run_payload(ctx, run_number=number))
    page = client.get(path).json()
    assert [r["run_number"] for r in page["items"]] == [1, 2, 3]
    assert page["order_by"] == ["run_number asc", "id asc"]
    assert "driver" not in page["items"][0]


def test_runs_for_missing_test_and_missing_run(client, ctx):
    assert_error(client.post(f"{API}/tests/999/runs", json=run_payload(ctx)), 404, "test_not_found")
    assert_error(client.get(f"{API}/runs/999"), 404, "run_not_found")


def test_layout_at_same_location_used_by_test_with_multiple_layouts(client, ctx):
    skidpad = create_layout(client, ctx["location"]["id"], "Skidpad", activity_type="SKIDPAD")
    path = f"{API}/tests/{ctx['test']['id']}/runs"
    assert client.post(path, json=run_payload(ctx, run_number=1)).status_code == 201
    response = client.post(path, json=run_payload(ctx, run_number=2, track_layout_id=skidpad["id"]))
    assert response.status_code == 201
    assert response.json()["track_layout"]["activity_type"] == "SKIDPAD"


def test_second_driver_can_drive_runs(client, ctx):
    driver_b = create_driver(client, "DRV-B", "Driver B")
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs", json=run_payload(ctx, driver_id=driver_b["id"])
    )
    assert response.json()["driver"]["code"] == "DRV-B"
