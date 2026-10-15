"""Lap-derived planned-versus-actual comparison (lap count, target lap time)."""

import pytest

from tests.api_helpers import API, test_context


@pytest.fixture
def ctx(client):
    return test_context(client)


def lap(n, **overrides) -> dict:
    values = {
        "lap_number": n,
        "lap_classification": "FLYING",
        "raw_time_ms": 62_000,
        "timing_valid": True,
        "physically_completed": True,
    }
    values.update(overrides)
    return values


def run_with_laps(client, ctx, laps, plan=None, run_number=1) -> dict:
    payload = {
        "run_number": run_number,
        "driver_id": ctx["driver"]["id"],
        "track_layout_id": ctx["layout"]["id"],
    }
    if plan:
        payload["planned_run_id"] = plan["id"]
    run = client.post(f"{API}/tests/{ctx['test']['id']}/runs", json=payload).json()
    if laps:
        response = client.post(f"{API}/runs/{run['id']}/laps/bulk", json={"laps": laps})
        assert response.status_code == 201, response.json()
    return run


def plan(client, ctx, sequence_number=1, **extra) -> dict:
    return client.post(
        f"{API}/tests/{ctx['test']['id']}/planned-runs",
        json={"sequence_number": sequence_number, **extra},
    ).json()


def comparison(client, run_id) -> dict:
    body = client.get(f"{API}/runs/{run_id}/plan-comparison").json()
    body["by_aspect"] = {item["aspect"]: item for item in body["items"]}
    return body


def test_lap_count_compares_expected_with_physically_completed_laps(client, ctx):
    planned = plan(client, ctx, expected_lap_count=4)
    run = run_with_laps(
        client,
        ctx,
        [
            lap(1, lap_classification="OUT_LAP"),
            lap(2),
            lap(3, timing_valid=False, invalidation_reason="Cone"),
            lap(4, physically_completed=False, lap_classification="ABORTED"),
        ],
        plan=planned,
    )
    result = comparison(client, run["id"])
    assert (result["recorded_lap_count"], result["physically_completed_lap_count"]) == (4, 3)
    item = result["by_aspect"]["lap_count"]
    assert (item["expected"], item["actual"], item["status"]) == (4, 3, "DIFFERENT")
    assert item["note"] == "4 lap(s) recorded, 3 physically completed."


def test_lap_count_match(client, ctx):
    planned = plan(client, ctx, expected_lap_count=2)
    run = run_with_laps(client, ctx, [lap(1), lap(2)], plan=planned)
    assert comparison(client, run["id"])["by_aspect"]["lap_count"]["status"] == "MATCH"


def test_target_time_uses_fastest_eligible_effective_lap(client, ctx):
    planned = plan(client, ctx, target_lap_time_ms=61_000)
    run = run_with_laps(
        client,
        ctx,
        [
            lap(1, raw_time_ms=59_000, penalty_duration_ms=2_500),  # effective 61 500
            lap(2, raw_time_ms=60_500),  # effective 60 500 -> fastest eligible
            lap(3, raw_time_ms=58_000, timing_valid=False, invalidation_reason="Cut"),
            lap(4, raw_time_ms=57_000, lap_classification="IN_LAP"),
        ],
        plan=planned,
    )
    result = comparison(client, run["id"])
    item = result["by_aspect"]["target_lap_time_ms"]
    assert (item["expected"], item["actual"], item["status"]) == (61_000, 60_500, "TARGET_MET")
    assert item["note"] == "Fastest eligible lap 2: -500 ms."
    laps = client.get(f"{API}/runs/{run['id']}/laps").json()["items"]
    assert result["fastest_eligible_lap_id"] == laps[1]["id"]


def test_target_missed_because_of_penalty(client, ctx):
    planned = plan(client, ctx, target_lap_time_ms=61_000)
    run = run_with_laps(
        client, ctx, [lap(1, raw_time_ms=60_000, penalty_duration_ms=2_000)], plan=planned
    )
    item = comparison(client, run["id"])["by_aspect"]["target_lap_time_ms"]
    assert (item["actual"], item["status"], item["note"]) == (
        62_000,
        "TARGET_MISSED",
        "Fastest eligible lap 1: +1000 ms.",
    )


def test_no_eligible_lap_means_target_actual_not_recorded(client, ctx):
    planned = plan(client, ctx, target_lap_time_ms=61_000, expected_lap_count=2)
    run = run_with_laps(
        client,
        ctx,
        [
            lap(1, lap_classification="OUT_LAP"),
            lap(2, raw_time_ms=None, timing_valid=False, invalidation_reason="Untimed"),
        ],
        plan=planned,
    )
    items = comparison(client, run["id"])["by_aspect"]
    assert items["target_lap_time_ms"]["status"] == "ACTUAL_NOT_RECORDED"
    assert items["target_lap_time_ms"]["actual"] is None
    # Laps exist, so the lap count is a real comparison (2 completed).
    assert (items["lap_count"]["actual"], items["lap_count"]["status"]) == (2, "MATCH")


def test_unexpected_run_reports_lap_values_without_expectations(client, ctx):
    run = run_with_laps(
        client, ctx, [lap(1, raw_time_ms=63_000), lap(2, physically_completed=False)]
    )
    result = comparison(client, run["id"])
    assert result["unexpected"] is True
    items = result["by_aspect"]
    assert items["lap_count"] == {
        "aspect": "lap_count",
        "expected": None,
        "actual": 1,
        "status": "NO_PLAN",
        "note": None,
    }
    assert (items["target_lap_time_ms"]["actual"], items["target_lap_time_ms"]["status"]) == (
        63_000,
        "NO_PLAN",
    )


def test_energy_stays_not_yet_supported_and_unplanned_aspects_stay_not_planned(client, ctx):
    planned = plan(client, ctx, expected_energy_limit_kwh="5.000")
    run = run_with_laps(client, ctx, [lap(1)], plan=planned)
    items = comparison(client, run["id"])["by_aspect"]
    assert items["energy_limit_kwh"]["status"] == "NOT_YET_SUPPORTED"
    assert items["energy_limit_kwh"]["actual"] is None
    assert items["lap_count"]["status"] == "NOT_PLANNED"
    assert items["target_lap_time_ms"]["status"] == "NOT_PLANNED"
    assert items["driver_id"]["status"] == "NOT_PLANNED"


def test_repeated_attempts_are_compared_individually(client, ctx):
    planned = plan(client, ctx, expected_lap_count=3)
    aborted = run_with_laps(client, ctx, [lap(1), lap(2, physically_completed=False)], planned, 1)
    retry = run_with_laps(client, ctx, [lap(1), lap(2), lap(3)], planned, 2)
    assert comparison(client, aborted["id"])["by_aspect"]["lap_count"]["status"] == "DIFFERENT"
    assert comparison(client, retry["id"])["by_aspect"]["lap_count"]["status"] == "MATCH"
