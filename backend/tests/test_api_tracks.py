import pytest

from tests.api_helpers import API, assert_error, create_layout, create_location


def test_create_location_and_layout(client):
    location = create_location(client, "Vallelunga")
    layout = create_layout(
        client,
        location["id"],
        "Skidpad",
        activity_type="SKIDPAD",
        verified_length_m="56.549",
        length_verification_note="Measured with wheel",
    )
    assert layout == {
        "id": layout["id"],
        "track_location_id": location["id"],
        "name": "Skidpad",
        "activity_type": "SKIDPAD",
        "verified_length_m": "56.549",
        "length_verified_on": "2026-01-01",
        "length_verification_note": "Measured with wheel",
    }
    assert client.get(f"{API}/track-layouts/{layout['id']}").json() == layout
    assert client.get(f"{API}/track-locations/{location['id']}").json() == location


@pytest.mark.parametrize("length", ["0", "-5", "1.2345", "1234567.000", "abc"])
def test_invalid_layout_length_is_rejected(client, length):
    location = create_location(client)
    response = client.post(
        f"{API}/track-layouts",
        json={
            "track_location_id": location["id"],
            "name": "Bad",
            "activity_type": "SKIDPAD",
            "verified_length_m": length,
            "length_verified_on": "2026-01-01",
        },
    )
    error = assert_error(response, 422, "request_validation_failed")
    assert any(d["field"] == "verified_length_m" for d in error["details"])


def test_layout_requires_verification_date_and_known_activity(client):
    location = create_location(client)
    base = {"track_location_id": location["id"], "name": "X", "verified_length_m": "100"}
    for payload in (
        {**base, "activity_type": "SKIDPAD"},
        {**base, "activity_type": "DRAG", "length_verified_on": "2026-01-01"},
    ):
        assert_error(
            client.post(f"{API}/track-layouts", json=payload), 422, "request_validation_failed"
        )


def test_layout_for_missing_location_is_rejected(client):
    response = client.post(
        f"{API}/track-layouts",
        json={
            "track_location_id": 999,
            "name": "Ghost",
            "activity_type": "SKIDPAD",
            "verified_length_m": "50",
            "length_verified_on": "2026-01-01",
        },
    )
    error = assert_error(response, 422, "referenced_resource_not_found")
    assert error["details"][0]["field"] == "track_location_id"


def test_layout_name_unique_per_location(client):
    location = create_location(client, "A")
    other = create_location(client, "B")
    create_layout(client, location["id"], "Loop")
    create_layout(client, other["id"], "Loop")
    response = client.post(
        f"{API}/track-layouts",
        json={
            "track_location_id": location["id"],
            "name": "Loop",
            "activity_type": "AUTOCROSS",
            "verified_length_m": "900",
            "length_verified_on": "2026-01-01",
        },
    )
    assert_error(response, 409, "track_layout_name_taken")


def test_duplicate_location_name_conflicts(client):
    create_location(client, "Same")
    assert_error(
        client.post(f"{API}/track-locations", json={"name": "Same"}),
        409,
        "track_location_name_taken",
    )


def test_filter_layouts_by_location_and_activity_type(client):
    a = create_location(client, "A")
    b = create_location(client, "B")
    skid_a = create_layout(client, a["id"], "Skidpad", activity_type="SKIDPAD")
    auto_a = create_layout(client, a["id"], "Autocross")
    skid_b = create_layout(client, b["id"], "Skidpad", activity_type="SKIDPAD")

    def ids(**params):
        return [x["id"] for x in client.get(f"{API}/track-layouts", params=params).json()["items"]]

    assert ids(track_location_id=a["id"]) == [auto_a["id"], skid_a["id"]]
    assert ids(activity_type="SKIDPAD") == [skid_a["id"], skid_b["id"]]
    assert ids(track_location_id=a["id"], activity_type="SKIDPAD") == [skid_a["id"]]


def test_unknown_layout_filter_is_rejected_not_ignored(client):
    assert_error(
        client.get(f"{API}/track-layouts", params={"location": 1}), 422, "request_validation_failed"
    )


def test_missing_layout_and_location_return_404(client):
    assert_error(client.get(f"{API}/track-layouts/42"), 404, "track_layout_not_found")
    assert_error(client.get(f"{API}/track-locations/42"), 404, "track_location_not_found")
