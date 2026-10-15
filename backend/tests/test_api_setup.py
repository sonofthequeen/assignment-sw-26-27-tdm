"""Setup snapshots: creation, derivation, append-only behaviour and diffs."""

import pytest
from sqlalchemy import event, func, select

from app.models import SetupCornerParams, SetupSnapshot
from tests.api_helpers import API, assert_error, create_vehicle

FOUR_CORNERS = [
    {
        "corner": c,
        "static_camber_deg": camber,
        "static_toe_deg": "0.050",
        "spring_rate_n_per_mm": rate,
    }
    for c, camber, rate in (
        ("RR", "-1.20", "40.00"),
        ("FL", "-1.50", "35.00"),
        ("RL", "-1.20", "40.00"),
        ("FR", "-1.50", "35.00"),
    )
]  # deliberately unordered


@pytest.fixture
def vehicle(client):
    return create_vehicle(client)


def create_snapshot(client, vehicle_id, **extra):
    return client.post(f"{API}/setup-snapshots", json={"vehicle_id": vehicle_id, **extra})


def snapshot_ok(client, vehicle_id, **extra) -> dict:
    response = create_snapshot(client, vehicle_id, **extra)
    assert response.status_code == 201, response.json()
    return response.json()


def derive(client, source_id, **changes):
    payload = {"change_reason": "Test change", **changes}
    return client.post(f"{API}/setup-snapshots/{source_id}/derive", json=payload)


def diff(client, snapshot_id, **params) -> dict:
    response = client.get(f"{API}/setup-snapshots/{snapshot_id}/diff", params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def table_counts(app) -> tuple[int, int]:
    with app.state.session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(SetupSnapshot)),
            session.scalar(select(func.count()).select_from(SetupCornerParams)),
        )


# --- Create -------------------------------------------------------------------------


def test_create_root_snapshot_with_four_corners_in_fixed_order(client, vehicle):
    snapshot = snapshot_ok(
        client,
        vehicle["id"],
        name="Autocross baseline",
        power_limit_kw="80.00",
        rpm_limit_rpm=18000,
        torque_vectoring_mode="TV-2",
        control_map="MAP-AX",
        corners=FOUR_CORNERS,
    )
    assert snapshot["is_derived"] is False
    assert (snapshot["based_on_snapshot_id"], snapshot["based_on"]) == (None, None)
    assert snapshot["change_reason"] is None
    assert snapshot["vehicle"] == {"id": vehicle["id"], "code": "VEH-A", "name": "Vehicle A"}
    assert [c["corner"] for c in snapshot["corners"]] == ["FL", "FR", "RL", "RR"]
    assert snapshot["corners"][0] == {
        "corner": "FL",
        "static_camber_deg": "-1.50",
        "static_toe_deg": "0.050",
        "spring_rate_n_per_mm": "35.00",
    }
    assert snapshot["missing_corners"] == []
    assert snapshot["power_limit_kw"] == "80.00"
    assert snapshot["created_at"].endswith("Z")
    assert client.get(f"{API}/setup-snapshots/{snapshot['id']}").json() == snapshot


def test_partial_corner_data_stays_explicitly_absent(client, vehicle):
    snapshot = snapshot_ok(
        client, vehicle["id"], corners=[{"corner": "FR", "static_camber_deg": "-1.00"}]
    )
    assert [c["corner"] for c in snapshot["corners"]] == ["FR"]
    assert snapshot["corners"][0]["static_toe_deg"] is None
    assert snapshot["missing_corners"] == ["FL", "RL", "RR"]
    assert snapshot["power_limit_kw"] is None  # nothing invented


def test_snapshot_for_missing_vehicle_is_rejected(client):
    error = assert_error(create_snapshot(client, 999), 422, "referenced_resource_not_found")
    assert error["details"][0]["field"] == "vehicle_id"


@pytest.mark.parametrize(
    "extra",
    [
        {"corners": [{"corner": "FL", "static_camber_deg": "-1"}] * 2},  # duplicate corner
        {"corners": [{"corner": "XX", "static_camber_deg": "-1"}]},  # invalid corner
        {"corners": [{"corner": "FL"}]},  # corner without values
        {"corners": [{"corner": "FL", "spring_rate_n_per_mm": "0"}]},
        {"corners": [{"corner": "FL", "static_camber_deg": "-1.234"}]},  # precision
        {"corners": [{"corner": "FL", "static_camber_deg": "-25"}]},  # implausible
        {"power_limit_kw": "0"},
        {"power_limit_kw": "-5"},
        {"rpm_limit_rpm": 0},
        {"based_on_snapshot_id": 1},  # roots cannot claim a parent
        {"change_reason": "x"},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"unknown": 1},
    ],
)
def test_invalid_snapshot_payloads_are_rejected(client, app, vehicle, extra):
    assert_error(create_snapshot(client, vehicle["id"], **extra), 422, "request_validation_failed")
    assert table_counts(app) == (0, 0)


def test_list_is_compact_newest_first_and_filterable(client, vehicle):
    other = create_vehicle(client, "VEH-B", "Vehicle B")
    first = snapshot_ok(client, vehicle["id"], corners=FOUR_CORNERS)
    second = snapshot_ok(client, other["id"])
    third = derive(client, first["id"], power_limit_kw="70").json()

    page = client.get(f"{API}/setup-snapshots").json()
    assert [s["id"] for s in page["items"]] == [third["id"], second["id"], first["id"]]
    assert page["order_by"] == ["created_at desc", "id desc"]
    assert "corners" not in page["items"][0]

    def ids(**params):
        items = client.get(f"{API}/setup-snapshots", params=params).json()["items"]
        return [s["id"] for s in items]

    assert ids(vehicle_id=vehicle["id"]) == [third["id"], first["id"]]
    assert ids(based_on_snapshot_id=first["id"]) == [third["id"]]
    assert ids(limit=1, offset=1) == [second["id"]]
    assert_error(
        client.get(f"{API}/setup-snapshots", params={"limit": 500}),
        422,
        "request_validation_failed",
    )


def test_missing_snapshot_returns_404(client):
    assert_error(client.get(f"{API}/setup-snapshots/42"), 404, "setup_snapshot_not_found")
    assert_error(derive(client, 42), 404, "setup_snapshot_not_found")
    assert_error(client.get(f"{API}/setup-snapshots/42/diff"), 404, "setup_snapshot_not_found")


# --- Derive -------------------------------------------------------------------------


def test_derive_copies_unchanged_values_and_overrides_selected_ones(client, vehicle):
    source = snapshot_ok(
        client,
        vehicle["id"],
        name="Baseline",
        power_limit_kw="80.00",
        rpm_limit_rpm=18000,
        control_map="MAP-AX",
        corners=FOUR_CORNERS,
    )
    response = derive(
        client,
        source["id"],
        change_reason="Lower power for wet track",
        power_limit_kw="60.00",
        corners=[{"corner": "RL", "static_toe_deg": "0.100"}],
    )
    assert response.status_code == 201, response.json()
    derived = response.json()

    assert derived["is_derived"] is True
    assert derived["based_on_snapshot_id"] == source["id"]
    assert derived["based_on"] == {
        "id": source["id"],
        "name": "Baseline",
        "created_at": source["created_at"],
    }
    assert derived["change_reason"] == "Lower power for wet track"
    assert derived["vehicle_id"] == source["vehicle_id"]
    assert derived["name"] is None  # labels are not inherited
    assert (derived["power_limit_kw"], derived["rpm_limit_rpm"]) == ("60.00", 18000)
    assert derived["control_map"] == "MAP-AX"
    corners = {c["corner"]: c for c in derived["corners"]}
    assert corners["RL"]["static_toe_deg"] == "0.100"
    assert corners["RL"]["static_camber_deg"] == "-1.20"  # untouched field of a changed corner
    assert corners["FL"] == {c["corner"]: c for c in source["corners"]}["FL"]

    assert client.get(f"{API}/setup-snapshots/{source['id']}").json() == source  # source intact


def test_derive_can_clear_a_value_add_and_remove_corners(client, vehicle):
    source = snapshot_ok(
        client,
        vehicle["id"],
        rpm_limit_rpm=18000,
        corners=[
            {"corner": "FL", "static_camber_deg": "-1.50"},
            {"corner": "FR", "static_camber_deg": "-1.50"},
        ],
    )
    derived = derive(
        client,
        source["id"],
        rpm_limit_rpm=None,
        corners=[{"corner": "RR", "spring_rate_n_per_mm": "42.00"}],
        remove_corners=["FR"],
    ).json()
    assert derived["rpm_limit_rpm"] is None
    assert [c["corner"] for c in derived["corners"]] == ["FL", "RR"]
    assert derived["missing_corners"] == ["FR", "RL"]


@pytest.mark.parametrize(
    ("changes", "status_code", "code"),
    [
        ({"change_reason": "   "}, 422, "request_validation_failed"),
        ({"change_reason": None}, 422, "request_validation_failed"),
        ({"vehicle_id": 2}, 422, "request_validation_failed"),  # no cross-vehicle derivation
        ({"based_on_snapshot_id": 5}, 422, "request_validation_failed"),
        ({"corners": [{"corner": "FL"}]}, 422, "request_validation_failed"),
        (
            {"corners": [{"corner": "FL", "static_camber_deg": "-1"}], "remove_corners": ["FL"]},
            422,
            "request_validation_failed",
        ),
        ({"remove_corners": ["RR"]}, 422, "setup_corner_not_present"),
        ({"corners": [{"corner": "FL", "static_camber_deg": None}]}, 422, "invalid_setup_value"),
        ({}, 422, "setup_derivation_without_changes"),
        ({"power_limit_kw": "80"}, 422, "setup_derivation_without_changes"),  # same value
    ],
)
def test_invalid_derivations_are_rejected_and_persist_nothing(
    client, app, vehicle, changes, status_code, code
):
    source = snapshot_ok(
        client,
        vehicle["id"],
        power_limit_kw="80.00",
        corners=[{"corner": "FL", "static_camber_deg": "-1.50"}],
    )
    before = table_counts(app)
    assert_error(derive(client, source["id"], **changes), status_code, code)
    assert table_counts(app) == before


def test_derive_rolls_back_snapshot_and_corners_when_commit_fails(client, app, vehicle):
    source = snapshot_ok(client, vehicle["id"], power_limit_kw="80", corners=FOUR_CORNERS)
    before = table_counts(app)

    def fail_commit(session):
        raise RuntimeError("simulated")

    event.listen(app.state.session_factory, "before_commit", fail_commit)
    try:
        response = derive(client, source["id"], power_limit_kw="70")
    finally:
        event.remove(app.state.session_factory, "before_commit", fail_commit)

    assert_error(response, 500, "internal_error")
    assert table_counts(app) == before == (1, 4)


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_snapshots_cannot_be_modified_or_deleted_through_the_api(client, vehicle, method):
    snapshot = snapshot_ok(client, vehicle["id"], power_limit_kw="80")
    response = getattr(client, method)(f"{API}/setup-snapshots/{snapshot['id']}")
    assert_error(response, 405, "method_not_allowed")
    assert client.get(f"{API}/setup-snapshots/{snapshot['id']}").json() == snapshot


# --- Diff ---------------------------------------------------------------------------


def test_root_without_target_has_empty_diff(client, vehicle):
    root = snapshot_ok(client, vehicle["id"], power_limit_kw="80")
    result = diff(client, root["id"])
    assert result == {
        "setup_snapshot_id": root["id"],
        "against_snapshot_id": None,
        "baseline": "NONE",
        "vehicle_changes": [],
        "corner_changes": [],
        "corners_added": [],
        "corners_removed": [],
        "has_changes": False,
    }


def test_derived_snapshot_diff_against_its_source(client, vehicle):
    source = snapshot_ok(
        client, vehicle["id"], power_limit_kw="80.00", control_map="A", corners=FOUR_CORNERS
    )
    derived = derive(
        client,
        source["id"],
        control_map="B",
        power_limit_kw="70.00",
        corners=[
            {"corner": "RR", "static_camber_deg": "-1.00", "spring_rate_n_per_mm": "45.00"},
            {"corner": "FL", "static_toe_deg": "0.000"},
        ],
    ).json()
    result = diff(client, derived["id"])
    assert (result["baseline"], result["against_snapshot_id"]) == ("BASED_ON", source["id"])
    assert result["vehicle_changes"] == [
        {"field": "power_limit_kw", "previous": "80.00", "current": "70.00"},
        {"field": "control_map", "previous": "A", "current": "B"},
    ]
    assert result["corner_changes"] == [
        {"corner": "FL", "field": "static_toe_deg", "previous": "0.050", "current": "0.000"},
        {"corner": "RR", "field": "static_camber_deg", "previous": "-1.20", "current": "-1.00"},
        {"corner": "RR", "field": "spring_rate_n_per_mm", "previous": "40.00", "current": "45.00"},
    ]
    assert result["has_changes"] is True


def test_diff_reports_added_and_removed_corners(client, vehicle):
    source = snapshot_ok(
        client, vehicle["id"], corners=[{"corner": "FL", "static_camber_deg": "-1"}]
    )
    derived = derive(
        client,
        source["id"],
        corners=[{"corner": "RR", "static_camber_deg": "-1"}],
        remove_corners=["FL"],
    ).json()
    result = diff(client, derived["id"])
    assert (result["corners_added"], result["corners_removed"]) == (["RR"], ["FL"])
    assert result["corner_changes"] == []


def test_explicit_diff_between_roots_and_identical_setups(client, vehicle):
    a = snapshot_ok(client, vehicle["id"], power_limit_kw="80", rpm_limit_rpm=18000)
    b = snapshot_ok(client, vehicle["id"], power_limit_kw="80.00", rpm_limit_rpm=18000)
    c = snapshot_ok(client, vehicle["id"], power_limit_kw="75", rpm_limit_rpm=18000)

    same = diff(client, b["id"], against_snapshot_id=a["id"])
    assert (same["baseline"], same["has_changes"]) == ("EXPLICIT", False)

    changed = diff(client, c["id"], against_snapshot_id=a["id"])
    assert changed["vehicle_changes"] == [
        {"field": "power_limit_kw", "previous": "80.00", "current": "75.00"}
    ]
    assert diff(client, c["id"], against_snapshot_id=a["id"]) == changed  # deterministic


def test_diff_across_vehicles_or_against_missing_snapshot_is_rejected(client, vehicle):
    other = create_vehicle(client, "VEH-B", "Vehicle B")
    a = snapshot_ok(client, vehicle["id"], power_limit_kw="80")
    b = snapshot_ok(client, other["id"], power_limit_kw="80")
    response = client.get(
        f"{API}/setup-snapshots/{a['id']}/diff", params={"against_snapshot_id": b["id"]}
    )
    assert_error(response, 422, "setup_snapshot_vehicle_mismatch")
    response = client.get(
        f"{API}/setup-snapshots/{a['id']}/diff", params={"against_snapshot_id": 999}
    )
    error = assert_error(response, 422, "referenced_resource_not_found")
    assert error["details"][0]["field"] == "against_snapshot_id"
