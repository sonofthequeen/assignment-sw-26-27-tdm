"""Small builders for valid API payloads; each asserts the create succeeded."""

API = "/api/v1"


def post_ok(client, path: str, payload: dict) -> dict:
    response = client.post(f"{API}{path}", json=payload)
    assert response.status_code == 201, response.json()
    return response.json()


def create_season(client, name="Season A", **extra) -> dict:
    return post_ok(client, "/seasons", {"name": name, **extra})


def create_vehicle(client, code="VEH-A", name="Vehicle A") -> dict:
    return post_ok(client, "/vehicles", {"code": code, "name": name})


def create_driver(client, code="DRV-A", full_name="Driver A") -> dict:
    return post_ok(client, "/drivers", {"code": code, "full_name": full_name})


def create_location(client, name="Location A") -> dict:
    return post_ok(client, "/track-locations", {"name": name})


def create_layout(client, location_id: int, name="Autocross loop", **extra) -> dict:
    payload = {
        "track_location_id": location_id,
        "name": name,
        "activity_type": "AUTOCROSS",
        "verified_length_m": "1000.000",
        "length_verified_on": "2026-01-01",
        **extra,
    }
    return post_ok(client, "/track-layouts", payload)


def create_test(client, season_id, vehicle_id, location_id, test_date="2026-03-01", **extra):
    payload = {
        "season_id": season_id,
        "vehicle_id": vehicle_id,
        "track_location_id": location_id,
        "test_date": test_date,
        **extra,
    }
    return post_ok(client, "/tests", payload)


def test_context(client) -> dict:
    """A season, vehicle, driver, location with one layout, and one test there."""
    season = create_season(client)
    vehicle = create_vehicle(client)
    driver = create_driver(client)
    location = create_location(client)
    layout = create_layout(client, location["id"])
    test = create_test(client, season["id"], vehicle["id"], location["id"])
    return {
        "season": season,
        "vehicle": vehicle,
        "driver": driver,
        "location": location,
        "layout": layout,
        "test": test,
    }


test_context.__test__ = False


def assert_error(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code, response.json()
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    for detail in body["error"]["details"]:
        assert set(detail) == {"field", "issue"}
    return body["error"]
