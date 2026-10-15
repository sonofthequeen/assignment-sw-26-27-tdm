"""Derived mileage across every scope, with exact expected distances."""

from decimal import Decimal

import pytest

from tests.api_helpers import (
    API,
    assert_error,
    create_driver,
    create_layout,
    create_location,
    create_season,
    create_test,
    create_vehicle,
)

AUTOCROSS_M = Decimal("1000.000")
SKIDPAD_M = Decimal("56.549")


def lap(n, **overrides) -> dict:
    values = {
        "lap_number": n,
        "lap_classification": "FLYING",
        "raw_time_ms": 65_000,
        "timing_valid": True,
        "physically_completed": True,
    }
    values.update(overrides)
    return values


def invalid(n, **overrides) -> dict:
    return lap(n, timing_valid=False, invalidation_reason="Invalid", **overrides)


def add_run(client, test_id, run_number, driver_id, layout_id, laps, **extra) -> dict:
    response = client.post(
        f"{API}/tests/{test_id}/runs",
        json={
            "run_number": run_number,
            "driver_id": driver_id,
            "track_layout_id": layout_id,
            **extra,
        },
    )
    assert response.status_code == 201, response.json()
    run = response.json()
    if laps:
        bulk = client.post(f"{API}/runs/{run['id']}/laps/bulk", json={"laps": laps})
        assert bulk.status_code == 201, bulk.json()
    return run


def mileage(client, scope: str, resource_id: int) -> dict:
    response = client.get(f"{API}/{scope}/{resource_id}/mileage")
    assert response.status_code == 200, response.json()
    return response.json()


def metres(result: dict) -> Decimal:
    return Decimal(result["distance_m"])


@pytest.fixture
def history(client):
    """Two seasons, two vehicles, two drivers, two layouts with exact lengths.

    Counted laps (physically completed only):
      run A1 (season 1, car 1, driver 1, autocross): 6 of 7 laps -> 6 x 1000.000
      run A2 (same test, unexpected, driver 2, skidpad): 3 laps   -> 3 x 56.549
      run A3 (same test, retry of the same plan, driver 1, autocross): 1 lap
      run B1 (season 2, car 2, driver 2, autocross): 2 of 3 laps -> 2 x 1000.000
    """
    season_1 = create_season(client, "Season 1")
    season_2 = create_season(client, "Season 2")
    car_1 = create_vehicle(client, "CAR-1", "Car 1")
    car_2 = create_vehicle(client, "CAR-2", "Car 2")
    driver_1 = create_driver(client, "D1", "Driver 1")
    driver_2 = create_driver(client, "D2", "Driver 2")
    location = create_location(client, "Circuit")
    autocross = create_layout(client, location["id"], "Autocross", verified_length_m="1000.000")
    skidpad = create_layout(
        client, location["id"], "Skidpad", activity_type="SKIDPAD", verified_length_m="56.549"
    )
    test_a = create_test(client, season_1["id"], car_1["id"], location["id"], "2026-03-01")
    test_b = create_test(client, season_2["id"], car_2["id"], location["id"], "2027-03-01")

    plan = client.post(
        f"{API}/tests/{test_a['id']}/planned-runs", json={"sequence_number": 1}
    ).json()
    # A planned run that is cancelled contributes nothing by itself.
    cancelled = client.post(
        f"{API}/tests/{test_a['id']}/planned-runs", json={"sequence_number": 2}
    ).json()
    client.post(
        f"{API}/planned-runs/{cancelled['id']}/cancel", json={"cancellation_reason": "Rain"}
    )

    run_a1 = add_run(
        client,
        test_a["id"],
        1,
        driver_1["id"],
        autocross["id"],
        [
            lap(1, lap_classification="OUT_LAP"),  # counts
            lap(2),  # counts
            lap(3, penalty_duration_ms=2_000),  # penalised: counts once, unchanged distance
            invalid(4),  # timing-invalid but completed: counts
            invalid(5, raw_time_ms=None),  # untimed but completed: counts
            lap(6, lap_classification="ABORTED", physically_completed=False),  # does not count
            lap(7, lap_classification="IN_LAP"),  # counts
        ],
        planned_run_id=plan["id"],
    )
    run_a2 = add_run(
        client,
        test_a["id"],
        2,
        driver_2["id"],
        skidpad["id"],
        [lap(n, raw_time_ms=5_200) for n in (1, 2, 3)],
    )
    run_a3 = add_run(
        client,
        test_a["id"],
        3,
        driver_1["id"],
        autocross["id"],
        [lap(1, lap_classification="ABORTED", timing_valid=False, invalidation_reason="Lifted")],
        planned_run_id=plan["id"],
    )
    run_b1 = add_run(
        client,
        test_b["id"],
        1,
        driver_2["id"],
        autocross["id"],
        [lap(1), lap(2, physically_completed=False), lap(3)],
    )
    return {
        "seasons": (season_1, season_2),
        "cars": (car_1, car_2),
        "drivers": (driver_1, driver_2),
        "tests": (test_a, test_b),
        "runs": {"a1": run_a1, "a2": run_a2, "a3": run_a3, "b1": run_b1},
        "location": location,
    }


def test_run_mileage_counts_physically_completed_laps_only(client, history):
    result = mileage(client, "runs", history["runs"]["a1"]["id"])
    assert result["scope"] == "RUN"
    assert result["counted_lap_count"] == 6
    assert metres(result) == 6 * AUTOCROSS_M
    assert result["distance_m"] == "6000.000"
    assert result["distance_km"] == "6.000000"
    assert result["contributing_run_count"] == 1
    assert "physically completed" in result["policy"]


def test_aborted_lap_that_completed_the_loop_counts_one_layout(client, history):
    result = mileage(client, "runs", history["runs"]["a3"]["id"])
    assert (result["counted_lap_count"], metres(result)) == (1, AUTOCROSS_M)


def test_mileage_uses_exact_verified_layout_length(client, history):
    result = mileage(client, "runs", history["runs"]["a2"]["id"])
    assert result["distance_m"] == "169.647"  # 3 x 56.549, no float rounding
    assert result["distance_km"] == "0.169647"


def test_test_mileage_includes_unexpected_runs_and_repeated_attempts(client, history):
    result = mileage(client, "tests", history["tests"][0]["id"])
    # a1: 6 x 1000 + a2: 3 x 56.549 + a3: 1 x 1000
    assert metres(result) == 7 * AUTOCROSS_M + 3 * SKIDPAD_M
    assert (result["counted_lap_count"], result["contributing_run_count"]) == (10, 3)


def test_season_mileage_is_limited_to_the_season(client, history):
    season_1, season_2 = history["seasons"]
    assert metres(mileage(client, "seasons", season_1["id"])) == 7 * AUTOCROSS_M + 3 * SKIDPAD_M
    assert metres(mileage(client, "seasons", season_2["id"])) == 2 * AUTOCROSS_M


def test_vehicle_lifetime_mileage(client, history):
    car_1, car_2 = history["cars"]
    assert metres(mileage(client, "vehicles", car_1["id"])) == 7 * AUTOCROSS_M + 3 * SKIDPAD_M
    result = mileage(client, "vehicles", car_2["id"])
    assert (result["scope"], metres(result)) == ("VEHICLE", 2 * AUTOCROSS_M)


def test_driver_lifetime_mileage_spans_seasons_and_vehicles(client, history):
    driver_1, driver_2 = history["drivers"]
    assert metres(mileage(client, "drivers", driver_1["id"])) == 7 * AUTOCROSS_M
    result = mileage(client, "drivers", driver_2["id"])
    # skidpad run in season 1 (car 1) + autocross run in season 2 (car 2)
    assert metres(result) == 3 * SKIDPAD_M + 2 * AUTOCROSS_M
    assert result["contributing_run_count"] == 2


def test_penalties_do_not_change_distance(client, history):
    # Run a1 contains a 2 s penalty; distance is still 6 full layouts.
    assert mileage(client, "runs", history["runs"]["a1"]["id"])["distance_m"] == "6000.000"


def test_existing_resources_without_laps_report_zero(client, history):
    empty_season = create_season(client, "Empty season")
    idle_driver = create_driver(client, "D3", "Driver 3")
    car_3 = create_vehicle(client, "CAR-3", "Car 3")
    empty_test = create_test(
        client, empty_season["id"], car_3["id"], history["location"]["id"], "2027-05-01"
    )
    for scope, resource_id in (
        ("seasons", empty_season["id"]),
        ("drivers", idle_driver["id"]),
        ("vehicles", car_3["id"]),
        ("tests", empty_test["id"]),
    ):
        result = mileage(client, scope, resource_id)
        assert (result["distance_m"], result["counted_lap_count"]) == ("0.000", 0)
        assert result["contributing_run_count"] == 0


@pytest.mark.parametrize(
    ("scope", "code"),
    [
        ("runs", "run_not_found"),
        ("tests", "test_not_found"),
        ("seasons", "season_not_found"),
        ("vehicles", "vehicle_not_found"),
        ("drivers", "driver_not_found"),
    ],
)
def test_missing_resource_returns_404(client, scope, code):
    assert_error(client.get(f"{API}/{scope}/999/mileage"), 404, code)
