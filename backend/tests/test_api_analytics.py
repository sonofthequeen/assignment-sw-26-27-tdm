"""Fastest-lap ranking and the test-level planned-versus-actual summary."""

import pytest
from sqlalchemy import event

from tests.api_helpers import API, assert_error, post_ok
from tests.historical_fixtures import build_history


@pytest.fixture
def h(client):
    return build_history(client)


def ranking(client, **params) -> dict:
    response = client.get(f"{API}/analytics/fastest-laps", params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def times(page) -> list[int]:
    return [item["effective_time_ms"] for item in page["items"]]


# --- Fastest laps -----------------------------------------------------------------------


def test_ranking_for_a_layout_uses_effective_time_and_eligibility(client, h):
    page = ranking(client, track_layout_id=h["layouts"]["AX"]["id"])
    # r6: 63 000, 63 500; r1: 64 000 (penalised), 65 000; r4: 66 000.
    # Excluded: r1 out-lap/in-lap, the invalid 61 000 lap and the untimed lap.
    assert times(page) == [63_000, 63_500, 64_000, 65_000, 66_000]
    assert [item["rank"] for item in page["items"]] == [1, 2, 3, 4, 5]
    assert page["total"] == 5
    assert page["order_by"] == [
        "effective_time_ms asc",
        "raw_time_ms asc",
        "lap_number asc",
        "lap_id asc",
    ]
    first = page["items"][0]
    assert (first["driver"]["code"], first["season"]["name"]) == ("D2", "S2")
    assert first["conditions"]["asphalt_temperature_c"] == "45.5"
    third = page["items"][2]
    assert (third["raw_time_ms"], third["penalty_duration_ms"]) == (62_000, 2_000)


def test_ranking_respects_filters(client, h):
    ax = h["layouts"]["AX"]["id"]
    assert times(ranking(client, track_layout_id=ax, driver_id=h["drivers"]["D1"]["id"])) == [
        64_000,
        65_000,
        66_000,
    ]
    assert times(ranking(client, track_layout_id=ax, season_id=h["seasons"]["S2"]["id"])) == [
        63_000,
        63_500,
    ]
    by_asphalt = ranking(
        client, track_layout_id=ax, asphalt_temperature_min_c="30", asphalt_temperature_max_c="35"
    )
    assert times(by_asphalt) == [64_000, 65_000, 66_000]
    assert times(ranking(client, activity_type="SKIDPAD")) == [5_100, 5_200, 5_300]


def test_ranking_rank_continues_across_pages(client, h):
    page = ranking(client, track_layout_id=h["layouts"]["AX"]["id"], limit=2, offset=2)
    assert [item["rank"] for item in page["items"]] == [3, 4]
    assert times(page) == [64_000, 65_000]


def test_ranking_requires_a_layout_filter(client, h):
    response = client.get(f"{API}/analytics/fastest-laps", params={"driver_id": 1})
    error = assert_error(response, 422, "invalid_search_filter")
    assert error["details"][0]["field"] == "track_layout_id"


def test_ranking_rejects_inverted_ranges_and_unknown_parameters(client, h):
    ax = h["layouts"]["AX"]["id"]
    assert_error(
        client.get(
            f"{API}/analytics/fastest-laps",
            params={"track_layout_id": ax, "date_from": "2027-01-01", "date_to": "2026-01-01"},
        ),
        422,
        "invalid_date_range",
    )
    assert_error(
        client.get(f"{API}/analytics/fastest-laps", params={"track_layout_id": ax, "has_plan": 1}),
        422,
        "request_validation_failed",
    )


def test_ranking_without_eligible_laps_is_empty(client, h):
    page = ranking(client, activity_type="ENDURANCE")
    assert (page["items"], page["total"]) == ([], 0)


# --- Test plan-vs-actual -----------------------------------------------------------


def summary(client, test_id) -> dict:
    response = client.get(f"{API}/tests/{test_id}/plan-vs-actual")
    assert response.status_code == 200, response.json()
    return response.json()


def test_plan_vs_actual_classifies_every_plan_and_run(client, h):
    test_id = h["tests"]["T1"]["id"]
    cancelled = post_ok(client, f"/tests/{test_id}/planned-runs", {"sequence_number": 2})
    client.post(
        f"{API}/planned-runs/{cancelled['id']}/cancel", json={"cancellation_reason": "Rain"}
    )
    original = post_ok(client, f"/tests/{test_id}/planned-runs", {"sequence_number": 3})
    replacement = client.post(
        f"{API}/planned-runs/{original['id']}/replace",
        json={"replacement_reason": "New aero", "replacement": {"sequence_number": 4}},
    ).json()["replacement"]

    result = summary(client, test_id)
    assert result["counts"] == {
        "planned_runs": 4,
        "executed": 1,
        "not_executed": 1,
        "cancelled": 1,
        "replaced": 1,
        "with_repeated_attempts": 1,
        "actual_runs": 3,
        "unexpected_runs": 1,
    }
    outcomes = {o["sequence_number"]: o for o in result["planned_runs"]}
    assert [o["sequence_number"] for o in result["planned_runs"]] == [1, 2, 3, 4]

    p1 = outcomes[1]
    assert (p1["category"], p1["attempt_count"], p1["repeated"]) == ("EXECUTED", 2, True)
    first, retry = p1["attempts"]
    assert (first["run_number"], first["recorded_lap_count"]) == (1, 6)
    assert first["fastest_effective_time_ms"] == 64_000
    # Plan expected 5 laps; 6 were physically completed.
    assert first["differing_aspects"] == ["lap_count"]
    assert (retry["deviation_reason"], retry["differing_aspects"]) == ("Retry", [])

    assert (outcomes[2]["category"], outcomes[2]["cancellation_reason"]) == ("CANCELLED", "Rain")
    assert outcomes[3]["category"] == "REPLACED"
    assert outcomes[3]["replaced_by_planned_run_id"] == replacement["id"]
    assert outcomes[3]["replacement_reason"] == "New aero"
    assert (outcomes[4]["category"], outcomes[4]["attempts"]) == ("NOT_EXECUTED", [])

    (unexpected,) = result["unexpected_runs"]
    assert (unexpected["run_id"], unexpected["deviation_reason"]) == (
        h["runs"]["r2"]["id"],
        "Extra skidpad check",
    )


def test_plan_vs_actual_agrees_with_the_run_comparison(client, h):
    result = summary(client, h["tests"]["T1"]["id"])
    for outcome in result["planned_runs"]:
        for attempt in outcome["attempts"]:
            detail = client.get(f"{API}/runs/{attempt['run_id']}/plan-comparison").json()
            differing = [
                i["aspect"]
                for i in detail["items"]
                if i["status"] in ("DIFFERENT", "TARGET_MISSED")
            ]
            assert attempt["differing_aspects"] == differing


def test_plan_vs_actual_for_test_without_plans_or_runs(client, h):
    empty = post_ok(
        client,
        "/tests",
        {
            "season_id": h["seasons"]["S1"]["id"],
            "vehicle_id": h["vehicles"]["C1"]["id"],
            "track_location_id": h["locations"]["L1"]["id"],
            "test_date": "2026-06-01",
        },
    )
    result = summary(client, empty["id"])
    assert result["planned_runs"] == result["unexpected_runs"] == []
    assert set(result["counts"].values()) == {0}


def test_plan_vs_actual_missing_test(client):
    assert_error(client.get(f"{API}/tests/999/plan-vs-actual"), 404, "test_not_found")


def test_plan_vs_actual_query_count_does_not_grow_with_runs(app, client, h):
    def statements_for(test_id) -> int:
        seen = []

        def record(*args):
            seen.append(args[2])

        event.listen(app.state.engine, "before_cursor_execute", record)
        try:
            summary(client, test_id)
        finally:
            event.remove(app.state.engine, "before_cursor_execute", record)
        return len(seen)

    one_run = statements_for(h["tests"]["T2"]["id"])
    three_runs = statements_for(h["tests"]["T1"]["id"])
    for number in range(4, 12):  # eight more runs on T1
        post_ok(
            client,
            f"/tests/{h['tests']['T1']['id']}/runs",
            {
                "run_number": number,
                "driver_id": h["drivers"]["D1"]["id"],
                "track_layout_id": h["layouts"]["AX"]["id"],
                "planned_run_id": h["plans"]["P1"]["id"],
            },
        )
    eleven_runs = statements_for(h["tests"]["T1"]["id"])
    assert one_run == three_runs == eleven_runs
