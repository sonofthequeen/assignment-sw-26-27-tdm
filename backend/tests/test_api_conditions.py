import pytest
from sqlalchemy import event, func, select

from app.models import RunCondition
from tests.api_helpers import API, assert_error, test_context


@pytest.fixture
def run(client):
    ctx = test_context(client)
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs",
        json={
            "run_number": 1,
            "driver_id": ctx["driver"]["id"],
            "track_layout_id": ctx["layout"]["id"],
        },
    )
    assert response.status_code == 201
    return response.json()


def post_conditions(client, run_id, **payload):
    return client.post(f"{API}/runs/{run_id}/conditions", json=payload)


def test_create_and_get_conditions(client, run):
    response = post_conditions(
        client,
        run["id"],
        ambient_temperature_c="21.5",
        asphalt_temperature_c="34.0",
        conditions_source="MEASURED",
        weather="CLEAR",
        track_state="DRY",
        notes="  Light wind  ",
    )
    assert response.status_code == 201, response.json()
    created = response.json()
    assert created == {
        "run_id": run["id"],
        "ambient_temperature_c": "21.5",
        "asphalt_temperature_c": "34.0",
        "conditions_source": "MEASURED",
        "weather": "CLEAR",
        "track_state": "DRY",
        "notes": "Light wind",
    }
    assert client.get(f"{API}/runs/{run['id']}/conditions").json() == created


def test_unavailable_values_stay_null(client, run):
    created = post_conditions(client, run["id"], track_state="WET").json()
    assert created["ambient_temperature_c"] is None
    assert created["asphalt_temperature_c"] is None
    assert created["conditions_source"] is None
    assert created["weather"] is None


def test_conditions_are_write_once(client, app, run):
    post_conditions(client, run["id"], weather="CLEAR")
    response = post_conditions(client, run["id"], weather="RAIN")
    assert_error(response, 409, "run_condition_already_exists")
    assert client.get(f"{API}/runs/{run['id']}/conditions").json()["weather"] == "CLEAR"


def test_missing_run_and_missing_conditions(client, run):
    assert_error(post_conditions(client, 999, weather="CLEAR"), 404, "run_not_found")
    assert_error(client.get(f"{API}/runs/999/conditions"), 404, "run_not_found")
    assert_error(client.get(f"{API}/runs/{run['id']}/conditions"), 404, "run_condition_not_found")


def test_temperature_requires_a_source(client, run):
    response = post_conditions(client, run["id"], asphalt_temperature_c="30.0")
    error = assert_error(response, 422, "request_validation_failed")
    assert "conditions_source" in error["details"][0]["issue"]


@pytest.mark.parametrize(
    ("field", "value", "accepted"),
    [
        ("ambient_temperature_c", "-30.0", True),
        ("ambient_temperature_c", "60.0", True),
        ("ambient_temperature_c", "-30.1", False),
        ("ambient_temperature_c", "60.1", False),
        ("asphalt_temperature_c", "-30.0", True),
        ("asphalt_temperature_c", "90.0", True),
        ("asphalt_temperature_c", "-30.1", False),
        ("asphalt_temperature_c", "90.1", False),
    ],
)
def test_temperature_policy_ranges(client, run, field, value, accepted):
    response = post_conditions(
        client, run["id"], **{field: value, "conditions_source": "ESTIMATED"}
    )
    if accepted:
        assert response.status_code == 201
        assert response.json()[field] == value
    else:
        error = assert_error(response, 422, "invalid_condition_value")
        assert error["details"][0]["field"] == field


@pytest.mark.parametrize(
    "payload",
    [
        {"ambient_temperature_c": "21.25", "conditions_source": "MEASURED"},  # precision
        {"ambient_temperature_c": "1000.0", "conditions_source": "MEASURED"},  # digits
        {"conditions_source": "GUESSED"},
        {"weather": "SNOW"},
        {"track_state": "ICY"},
        {"humidity_pct": 40},
        {"notes": "   "},
    ],
)
def test_invalid_condition_payloads_are_rejected(client, app, run, payload):
    assert_error(post_conditions(client, run["id"], **payload), 422, "request_validation_failed")
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(RunCondition)) == 0


def test_condition_write_rolls_back_on_commit_failure(client, app, run):
    def fail(session):
        raise RuntimeError("simulated")

    event.listen(app.state.session_factory, "before_commit", fail)
    try:
        response = post_conditions(client, run["id"], weather="CLEAR")
    finally:
        event.remove(app.state.session_factory, "before_commit", fail)
    assert_error(response, 500, "internal_error")
    assert_error(client.get(f"{API}/runs/{run['id']}/conditions"), 404, "run_condition_not_found")
