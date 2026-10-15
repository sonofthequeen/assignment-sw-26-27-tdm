"""GET /api/v1/runs: the paramount historical multi-filter query."""

import pytest
from sqlalchemy import event

from tests.api_helpers import API, assert_error, post_ok
from tests.historical_fixtures import build_history, lap, search


@pytest.fixture
def h(client):
    return build_history(client)


def names(h, page) -> list[str]:
    by_id = {run["id"]: name for name, run in h["runs"].items()}
    return [by_id[item["id"]] for item in page["items"]]


def found(client, h, **params) -> list[str]:
    return names(h, search(client, **params))


# --- Default ordering and pagination ---------------------------------------------


def test_default_search_returns_all_runs_newest_test_first(client, h):
    page = search(client)
    assert names(h, page) == ["r6", "r5", "r4", "r1", "r2", "r3"]
    assert (page["total"], page["limit"], page["offset"]) == (6, 50, 0)
    assert page["order_by"] == ["test_date desc", "run_number asc", "id asc"]


def test_page_boundaries_are_stable(client, h):
    pages = [found(client, h, limit=2, offset=offset) for offset in (0, 2, 4, 6)]
    assert pages == [["r6", "r5"], ["r4", "r1"], ["r2", "r3"], []]
    assert search(client, limit=2, offset=4)["total"] == 6
    assert found(client, h, limit=1) == found(client, h, limit=1)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_invalid_pagination_is_rejected(client, h, params):
    assert_error(client.get(f"{API}/runs", params=params), 422, "request_validation_failed")


def test_limit_bounds_are_inclusive(client, h):
    assert len(search(client, limit=1)["items"]) == 1
    assert len(search(client, limit=100)["items"]) == 6


# --- Individual filters -----------------------------------------------------------------


def test_filter_by_season(client, h):
    assert found(client, h, season_id=h["seasons"]["S1"]["id"]) == ["r4", "r1", "r2", "r3"]
    assert found(client, h, season_id=h["seasons"]["S2"]["id"]) == ["r6", "r5"]


def test_filter_by_vehicle(client, h):
    assert found(client, h, vehicle_id=h["vehicles"]["C2"]["id"]) == ["r5"]


def test_filter_by_driver(client, h):
    assert found(client, h, driver_id=h["drivers"]["D2"]["id"]) == ["r6", "r5", "r2"]


def test_filter_by_track_location(client, h):
    assert found(client, h, track_location_id=h["locations"]["L2"]["id"]) == ["r5"]


def test_filter_by_track_layout(client, h):
    assert found(client, h, track_layout_id=h["layouts"]["SK"]["id"]) == ["r2"]


def test_filter_by_activity_type(client, h):
    assert found(client, h, activity_type="AUTOCROSS") == ["r6", "r4", "r1", "r3"]
    assert found(client, h, activity_type="ACCELERATION") == ["r5"]


def test_inclusive_date_bounds(client, h):
    assert found(client, h, date_from="2026-03-15") == ["r6", "r5", "r4"]
    assert found(client, h, date_to="2026-03-15") == ["r4", "r1", "r2", "r3"]
    assert found(client, h, date_from="2026-03-15", date_to="2026-03-15") == ["r4"]


def test_inclusive_ambient_bounds_exclude_missing_values(client, h):
    # r3 has no conditions row; r4 has a null ambient temperature.
    assert found(client, h, ambient_temperature_min_c="20.0") == ["r6", "r1", "r2"]
    assert found(client, h, ambient_temperature_max_c="20.0") == ["r5", "r1"]


def test_inclusive_asphalt_bounds_exclude_missing_values(client, h):
    # r3 has no conditions row; r5 has a null asphalt temperature.
    assert found(client, h, asphalt_temperature_min_c="35.0") == ["r6", "r4", "r2"]
    assert found(client, h, asphalt_temperature_max_c="35.0") == ["r4", "r1"]
    assert found(client, h, asphalt_temperature_min_c="45.5", asphalt_temperature_max_c="45.5") == [
        "r6"
    ]


def test_runs_without_conditions_are_kept_when_no_condition_filter_is_used(client, h):
    assert "r3" in found(client, h, season_id=h["seasons"]["S1"]["id"])


def test_filter_by_planned_run_returns_every_attempt(client, h):
    assert found(client, h, planned_run_id=h["plans"]["P1"]["id"]) == ["r1", "r3"]


def test_has_plan_filters(client, h):
    assert found(client, h, has_plan="true") == ["r6", "r4", "r1", "r3"]
    assert found(client, h, has_plan="false") == ["r5", "r2"]


def test_filter_by_test_status(client, h):
    assert found(client, h, test_status="COMPLETED") == ["r1", "r2", "r3"]


# --- Combined filters ---------------------------------------------------------------


def test_season_and_driver(client, h):
    params = {"season_id": h["seasons"]["S1"]["id"], "driver_id": h["drivers"]["D1"]["id"]}
    assert found(client, h, **params) == ["r4", "r1", "r3"]


def test_readme_example_season_driver_and_asphalt_range(client, h):
    """README: runs from a season by driver X within an asphalt range of 30-40 °C."""
    params = {
        "season_id": h["seasons"]["S1"]["id"],
        "driver_id": h["drivers"]["D1"]["id"],
        "asphalt_temperature_min_c": "30",
        "asphalt_temperature_max_c": "40",
    }
    assert found(client, h, **params) == ["r4", "r1"]


def test_vehicle_and_track_layout(client, h):
    params = {"vehicle_id": h["vehicles"]["C1"]["id"], "track_layout_id": h["layouts"]["AX"]["id"]}
    assert found(client, h, **params) == ["r6", "r4", "r1", "r3"]


def test_date_range_and_activity_type(client, h):
    params = {"date_from": "2026-01-01", "date_to": "2026-12-31", "activity_type": "AUTOCROSS"}
    assert found(client, h, **params) == ["r4", "r1", "r3"]


def test_ambient_and_asphalt_ranges_together(client, h):
    params = {
        "ambient_temperature_min_c": "20.0",
        "ambient_temperature_max_c": "25.0",
        "asphalt_temperature_min_c": "35.0",
    }
    assert found(client, h, **params) == ["r2"]


def test_unexpected_runs_in_a_season(client, h):
    assert found(client, h, has_plan="false", season_id=h["seasons"]["S2"]["id"]) == ["r5"]


def test_combination_without_matches_is_an_empty_200(client, h):
    page = search(client, vehicle_id=h["vehicles"]["C2"]["id"], driver_id=h["drivers"]["D1"]["id"])
    assert (page["items"], page["total"]) == ([], 0)


# --- Validation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "code", "field"),
    [
        ({"date_from": "2026-05-01", "date_to": "2026-01-01"}, "invalid_date_range", "date_to"),
        (
            {"ambient_temperature_min_c": "25", "ambient_temperature_max_c": "20"},
            "invalid_ambient_temperature_range",
            "ambient_temperature_max_c",
        ),
        (
            {"asphalt_temperature_min_c": "40", "asphalt_temperature_max_c": "30"},
            "invalid_asphalt_temperature_range",
            "asphalt_temperature_max_c",
        ),
        ({"has_plan": "false", "planned_run_id": 1}, "conflicting_plan_filters", "planned_run_id"),
    ],
)
def test_contradictory_filters_are_rejected(client, h, params, code, field):
    error = assert_error(client.get(f"{API}/runs", params=params), 422, code)
    assert error["details"][0]["field"] == field


@pytest.mark.parametrize(
    "params",
    [
        {"driver": 1},  # unknown parameter: never silently ignored
        {"compound": 1},  # misspelt tire_compound_id
        {"season_id": 0},
        {"season_id": -3},
        {"activity_type": "DRAG"},
        {"asphalt_temperature_min_c": "30.25"},  # beyond recorded precision
        {"has_plan": "maybe"},
        {"date_from": "15/03/2026"},
    ],
)
def test_invalid_query_parameters_are_rejected(client, h, params):
    assert_error(client.get(f"{API}/runs", params=params), 422, "request_validation_failed")


def test_unknown_ids_simply_match_nothing(client, h):
    assert search(client, season_id=999)["total"] == 0


# --- Summary content ------------------------------------------------------------------


def run_item(client, h, name) -> dict:
    run_id = h["runs"][name]["id"]
    return next(item for item in search(client)["items"] if item["id"] == run_id)


def test_summary_carries_historical_context(client, h):
    item = run_item(client, h, "r1")
    assert item["test"] == {
        "id": h["tests"]["T1"]["id"],
        "test_date": "2026-03-01",
        "status": "COMPLETED",
        "title": None,
    }
    assert item["season"] == {"id": h["seasons"]["S1"]["id"], "name": "S1"}
    assert item["vehicle"]["code"] == "C1"
    assert item["driver"]["code"] == "D1"
    assert item["track_location"] == {"id": h["locations"]["L1"]["id"], "name": "L1"}
    assert item["track_layout"]["activity_type"] == "AUTOCROSS"
    assert (item["planned_run_id"], item["unexpected"]) == (h["plans"]["P1"]["id"], False)
    assert item["conditions"] == {
        "ambient_temperature_c": "20.0",
        "asphalt_temperature_c": "30.0",
        "conditions_source": "MEASURED",
        "weather": None,
        "track_state": None,
    }
    assert "laps" not in item and "corners" not in item


def test_summary_lap_statistics_and_mileage(client, h):
    item = run_item(client, h, "r1")
    assert (item["recorded_lap_count"], item["physically_completed_lap_count"]) == (6, 6)
    # Lap 4 (61 000, invalid) and the untimed lap 5 count for distance, not for the fastest lap.
    assert item["fastest_lap"] == {
        "lap_id": item["fastest_lap"]["lap_id"],
        "lap_number": 3,
        "raw_time_ms": 62_000,
        "penalty_duration_ms": 2_000,
        "effective_time_ms": 64_000,
    }
    assert item["distance_m"] == "6000.000"


def test_summary_mileage_precision_and_unexpected_runs(client, h):
    item = run_item(client, h, "r2")
    assert (item["unexpected"], item["planned_run_id"]) == (True, None)
    assert item["distance_m"] == "169.647"  # 3 x 56.549
    assert item["fastest_lap"]["raw_time_ms"] == 5_100


def test_run_without_laps_or_conditions(client, h):
    item = run_item(client, h, "r3")
    assert (item["conditions"], item["fastest_lap"]) == (None, None)
    assert (item["recorded_lap_count"], item["distance_m"]) == (0, "0.000")


def test_no_eligible_lap_gives_null_fastest_lap(client, h):
    run_id = h["runs"]["r3"]["id"]
    post_ok(client, f"/runs/{run_id}/laps", lap(1, lap_classification="OUT_LAP"))
    item = run_item(client, h, "r3")
    assert (item["fastest_lap"], item["distance_m"]) == (None, "1000.000")


def test_search_mileage_matches_the_mileage_endpoint(client, h):
    for item in search(client)["items"]:
        mileage = client.get(f"{API}/runs/{item['id']}/mileage").json()
        assert item["distance_m"] == mileage["distance_m"]
        assert item["physically_completed_lap_count"] == mileage["counted_lap_count"]


def test_search_fastest_lap_matches_the_fastest_lap_endpoint(client, h):
    for item in search(client)["items"]:
        fastest = client.get(f"{API}/runs/{item['id']}/fastest-lap").json()["lap"]
        expected = fastest["id"] if fastest else None
        assert (item["fastest_lap"] or {}).get("lap_id") == expected


def test_laps_and_conditions_do_not_duplicate_runs(client, h):
    page = search(client, limit=100)
    ids = [item["id"] for item in page["items"]]
    assert len(ids) == len(set(ids)) == page["total"] == 6
    filtered = search(client, asphalt_temperature_min_c="0")
    assert filtered["total"] == len(filtered["items"]) == 4


# --- Query efficiency -------------------------------------------------------------------


def count_statements(app, client, **params) -> tuple[int, int]:
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        page = search(client, **params)
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)
    return len(statements), len(page["items"])


def test_query_count_does_not_grow_with_page_size(app, client, h):
    one_query_count, one_items = count_statements(app, client, limit=1)
    all_query_count, all_items = count_statements(app, client, limit=100)
    assert (one_items, all_items) == (1, 6)
    assert one_query_count == all_query_count == 4  # count, page, lap counts, fastest lap
