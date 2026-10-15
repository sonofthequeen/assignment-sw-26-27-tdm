import pytest

from tests.api_helpers import (
    API,
    assert_error,
    create_driver,
    create_season,
    create_vehicle,
)


def test_create_and_get_season(client):
    created = create_season(client, "2026/27", starts_on="2026-09-01", ends_on="2027-08-31")
    assert created == {
        "id": created["id"],
        "name": "2026/27",
        "starts_on": "2026-09-01",
        "ends_on": "2027-08-31",
    }
    assert client.get(f"{API}/seasons/{created['id']}").json() == created


def test_season_names_are_trimmed(client):
    assert create_season(client, "  2025/26  ")["name"] == "2025/26"


def test_seasons_are_ordered_by_start_date_with_undated_last(client):
    undated = create_season(client, "Undated")
    later = create_season(client, "Later", starts_on="2026-09-01")
    earlier = create_season(client, "Earlier", starts_on="2025-09-01")
    page = client.get(f"{API}/seasons").json()
    assert [s["id"] for s in page["items"]] == [earlier["id"], later["id"], undated["id"]]
    assert page["order_by"] == ["starts_on asc nulls last", "id asc"]


def test_season_date_order_is_validated_before_persistence(client):
    response = client.post(
        f"{API}/seasons", json={"name": "Bad", "starts_on": "2026-09-01", "ends_on": "2026-01-01"}
    )
    assert_error(response, 422, "request_validation_failed")


def test_duplicate_season_name_returns_409_without_database_details(client):
    create_season(client, "2026/27")
    response = client.post(f"{API}/seasons", json={"name": "2026/27"})
    error = assert_error(response, 409, "season_name_taken")
    assert error["details"] == [{"field": "name", "issue": "A season with this name exists."}]
    for leaked in ("UNIQUE", "INSERT", "season.name", "uq_", "sqlite", "Traceback"):
        assert leaked not in response.text


def test_vehicle_and_driver_create_get_and_conflict(client):
    vehicle = create_vehicle(client, "RUP-E26", "Electric 2026")
    assert client.get(f"{API}/vehicles/{vehicle['id']}").json() == vehicle
    assert_error(
        client.post(f"{API}/vehicles", json={"code": "RUP-E26", "name": "Other"}),
        409,
        "vehicle_code_taken",
    )

    driver = create_driver(client, "MR", "Mario Rossi")
    assert client.get(f"{API}/drivers/{driver['id']}").json() == driver
    assert_error(
        client.post(f"{API}/drivers", json={"code": "MR", "full_name": "Maria Rosa"}),
        409,
        "driver_code_taken",
    )


def test_vehicles_ordered_by_code_and_drivers_by_code(client):
    create_vehicle(client, "B-CAR", "B")
    create_vehicle(client, "A-CAR", "A")
    create_driver(client, "ZZ", "Z")
    create_driver(client, "AA", "A")
    assert [v["code"] for v in client.get(f"{API}/vehicles").json()["items"]] == ["A-CAR", "B-CAR"]
    assert [d["code"] for d in client.get(f"{API}/drivers").json()["items"]] == ["AA", "ZZ"]


def test_list_pagination_is_bounded_and_deterministic(client):
    for index in range(5):
        create_driver(client, f"D{index}", f"Driver {index}")
    first = client.get(f"{API}/drivers", params={"limit": 2}).json()
    second = client.get(f"{API}/drivers", params={"limit": 2, "offset": 2}).json()
    last = client.get(f"{API}/drivers", params={"limit": 2, "offset": 4}).json()

    assert (first["limit"], first["offset"], first["total"]) == (2, 0, 5)
    assert [d["code"] for d in first["items"] + second["items"] + last["items"]] == [
        "D0",
        "D1",
        "D2",
        "D3",
        "D4",
    ]
    assert client.get(f"{API}/drivers").json()["limit"] == 50


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "many"}, {"page": 2}]
)
def test_invalid_pagination_parameters_are_rejected(client, params):
    error = assert_error(
        client.get(f"{API}/drivers", params=params), 422, "request_validation_failed"
    )
    assert error["details"]


@pytest.mark.parametrize("resource", ["seasons", "vehicles", "drivers"])
def test_missing_reference_resource_returns_404(client, resource):
    singular = resource[:-1]
    error = assert_error(client.get(f"{API}/{resource}/999"), 404, f"{singular}_not_found")
    assert error["details"] == []


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", "99999999999"])
def test_invalid_path_ids_are_rejected(client, bad_id):
    assert_error(client.get(f"{API}/seasons/{bad_id}"), 422, "request_validation_failed")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"code": "", "name": "X"},
        {"code": "   ", "name": "X"},
        {"code": "X" * 33, "name": "X"},
        {"code": "X", "name": "X", "id": 5},
    ],
)
def test_invalid_vehicle_payloads_are_rejected(client, payload):
    assert_error(client.post(f"{API}/vehicles", json=payload), 422, "request_validation_failed")
    assert client.get(f"{API}/vehicles").json()["total"] == 0


def test_validation_error_details_name_the_field(client):
    error = assert_error(
        client.post(f"{API}/drivers", json={"code": "OK"}), 422, "request_validation_failed"
    )
    assert {"field": "full_name", "issue": "Field required"} in error["details"]
