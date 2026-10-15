"""Lap ingestion, effective time and fastest-lap selection.

The default layout is a 1000.000 m AUTOCROSS loop (implied-speed cap 40 m/s, so
any raw time below 25 000 ms on a completed lap is impossible).
"""

import pytest
from sqlalchemy import event, func, select

from app.models import Lap
from tests.api_helpers import API, assert_error, create_layout, test_context


@pytest.fixture
def ctx(client):
    return test_context(client)


@pytest.fixture
def run(client, ctx):
    return add_run(client, ctx)


def add_run(client, ctx, run_number=1, **extra) -> dict:
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/runs",
        json={
            "run_number": run_number,
            "driver_id": ctx["driver"]["id"],
            "track_layout_id": ctx["layout"]["id"],
            **extra,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def lap(lap_number=1, **overrides) -> dict:
    values = {
        "lap_number": lap_number,
        "lap_classification": "FLYING",
        "raw_time_ms": 65_000,
        "timing_valid": True,
        "physically_completed": True,
    }
    values.update(overrides)
    return values


def invalid(lap_number=1, reason="Cone", **overrides) -> dict:
    return lap(lap_number, timing_valid=False, invalidation_reason=reason, **overrides)


def post_lap(client, run_id, payload):
    return client.post(f"{API}/runs/{run_id}/laps", json=payload)


def post_bulk(client, run_id, laps):
    return client.post(f"{API}/runs/{run_id}/laps/bulk", json={"laps": laps})


def lap_count(app) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(Lap))


def fastest(client, run_id) -> dict:
    response = client.get(f"{API}/runs/{run_id}/fastest-lap")
    assert response.status_code == 200, response.json()
    return response.json()


# --- Individual laps --------------------------------------------------------------


def test_valid_unpenalised_flying_lap(client, run):
    response = post_lap(client, run["id"], lap())
    assert response.status_code == 201, response.json()
    created = response.json()
    assert created == {
        "id": created["id"],
        "run_id": run["id"],
        "lap_number": 1,
        "lap_classification": "FLYING",
        "raw_time_ms": 65_000,
        "penalty_duration_ms": 0,
        "effective_time_ms": 65_000,
        "timing_valid": True,
        "physically_completed": True,
        "invalidation_reason": None,
        "fastest_lap_eligible": True,
        "counts_toward_mileage": True,
    }
    assert client.get(f"{API}/laps/{created['id']}").json() == created


def test_penalised_lap_stays_valid_and_eligible(client, run):
    created = post_lap(client, run["id"], lap(penalty_duration_ms=2_000)).json()
    assert (created["raw_time_ms"], created["effective_time_ms"]) == (65_000, 67_000)
    assert created["timing_valid"] and created["fastest_lap_eligible"]


def test_timing_invalid_but_completed_lap(client, run):
    created = post_lap(client, run["id"], invalid(reason="Track limits")).json()
    assert created["effective_time_ms"] == 65_000
    assert (created["fastest_lap_eligible"], created["counts_toward_mileage"]) == (False, True)


def test_untimed_but_completed_lap_has_no_effective_time(client, run):
    created = post_lap(
        client, run["id"], invalid(raw_time_ms=None, reason="Transponder miss")
    ).json()
    assert (created["raw_time_ms"], created["effective_time_ms"]) == (None, None)
    assert (created["fastest_lap_eligible"], created["counts_toward_mileage"]) == (False, True)


def test_untimed_lap_with_penalty_still_has_no_effective_time(client, run):
    payload = invalid(raw_time_ms=None, reason="No time", penalty_duration_ms=2_000)
    assert post_lap(client, run["id"], payload).json()["effective_time_ms"] is None


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (lap(raw_time_ms=None), "raw_time_ms"),  # untimed but claimed valid
        (lap(timing_valid=False), "invalidation_reason"),  # invalid without reason
        (lap(invalidation_reason="Cone"), "invalidation_reason"),  # valid with reason
    ],
)
def test_contradictory_lap_states_are_rejected(client, app, run, payload, field):
    error = assert_error(post_lap(client, run["id"], payload), 422, "invalid_lap_state")
    assert error["details"][0]["field"] == field
    assert lap_count(app) == 0


@pytest.mark.parametrize(
    ("classification", "completed", "eligible", "counts"),
    [
        ("IN_LAP", True, False, True),
        ("OUT_LAP", True, False, True),
        ("ABORTED", False, False, False),
        ("ABORTED", True, False, True),  # aborted attempt that still completed the loop
        ("FLYING", False, False, False),
    ],
)
def test_classification_and_completion_semantics(
    client, run, classification, completed, eligible, counts
):
    payload = lap(lap_classification=classification, physically_completed=completed)
    created = post_lap(client, run["id"], payload).json()
    assert (created["fastest_lap_eligible"], created["counts_toward_mileage"]) == (eligible, counts)


@pytest.mark.parametrize(
    "payload",
    [
        lap(penalty_duration_ms=-1),
        lap(raw_time_ms=0),
        lap(raw_time_ms=-5),
        lap(lap_number=0),
        lap(lap_classification="WARMUP"),
        lap(timing_valid=1),  # strict booleans
        lap(physically_completed="yes"),
        lap(effective_time_ms=60_000),  # derived values cannot be supplied
        lap(sector_1_ms=20_000),
        {k: v for k, v in lap().items() if k != "physically_completed"},
    ],
)
def test_invalid_lap_payloads_are_rejected(client, app, run, payload):
    assert_error(post_lap(client, run["id"], payload), 422, "request_validation_failed")
    assert lap_count(app) == 0


def test_duplicate_lap_number_is_rejected(client, run):
    post_lap(client, run["id"], lap(1))
    error = assert_error(
        post_lap(client, run["id"], lap(1, raw_time_ms=70_000)), 409, "lap_number_taken"
    )
    assert error["details"][0]["field"] == "lap_number"


def test_lap_for_missing_run_and_missing_lap(client):
    assert_error(post_lap(client, 999, lap()), 404, "run_not_found")
    assert_error(client.get(f"{API}/laps/999"), 404, "lap_not_found")
    assert_error(client.get(f"{API}/runs/999/laps"), 404, "run_not_found")


@pytest.mark.parametrize(
    ("raw_time_ms", "completed", "accepted"),
    [
        (25_000, True, True),  # exactly 40 m/s over 1000 m: at the limit
        (24_999, True, False),
        (5_000, True, False),  # 200 m/s
        (5_000, False, True),  # incomplete: did not cover the layout, speed unknown
    ],
)
def test_implied_speed_plausibility(client, run, raw_time_ms, completed, accepted):
    payload = lap(raw_time_ms=raw_time_ms, physically_completed=completed)
    response = post_lap(client, run["id"], payload)
    if accepted:
        assert response.status_code == 201, response.json()
    else:
        error = assert_error(response, 422, "impossible_lap_time")
        assert error["details"][0]["field"] == "raw_time_ms"
        assert "m/s" in error["message"]


def test_plausibility_uses_raw_time_not_penalised_time(client, run):
    response = post_lap(client, run["id"], lap(raw_time_ms=20_000, penalty_duration_ms=10_000))
    assert_error(response, 422, "impossible_lap_time")


def test_plausibility_is_activity_specific(client, ctx):
    skidpad = create_layout(
        client,
        ctx["location"]["id"],
        "Skidpad",
        activity_type="SKIDPAD",
        verified_length_m="56.549",
    )
    run = add_run(client, ctx, track_layout_id=skidpad["id"])
    assert post_lap(client, run["id"], lap(1, raw_time_ms=5_100)).status_code == 201  # ~11 m/s
    # 56.549 m in 2.0 s = 28.3 m/s: above the 25 m/s skidpad cap.
    assert_error(post_lap(client, run["id"], lap(2, raw_time_ms=2_000)), 422, "impossible_lap_time")


# --- Bulk ingestion -----------------------------------------------------------------


def test_bulk_ingestion_returns_laps_in_lap_number_order(client, run):
    response = post_bulk(
        client,
        run["id"],
        [lap(3, raw_time_ms=64_000), lap(1, lap_classification="OUT_LAP"), lap(2)],
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["run_id"], body["created_count"]) == (run["id"], 3)
    assert [x["lap_number"] for x in body["laps"]] == [1, 2, 3]
    listed = client.get(f"{API}/runs/{run['id']}/laps").json()
    assert [x["lap_number"] for x in listed["items"]] == [1, 2, 3]
    assert listed["order_by"] == ["lap_number asc", "id asc"]


def test_duplicate_lap_numbers_in_batch_are_rejected(client, app, run):
    response = post_bulk(client, run["id"], [lap(1), lap(2), lap(1)])
    error = assert_error(response, 422, "duplicate_lap_number_in_batch")
    assert [d["field"] for d in error["details"]] == ["laps.0.lap_number", "laps.2.lap_number"]
    assert lap_count(app) == 0


def test_collision_with_existing_lap_rejects_whole_batch(client, app, run):
    post_lap(client, run["id"], lap(2))
    error = assert_error(
        post_bulk(client, run["id"], [lap(1), lap(2), lap(3)]), 409, "lap_number_taken"
    )
    assert error["details"] == [{"field": "laps.1.lap_number", "issue": "Lap 2 exists."}]
    assert lap_count(app) == 1


@pytest.mark.parametrize(
    ("bad_lap", "code"),
    [
        (lap(2, raw_time_ms=None), "invalid_lap_state"),
        (lap(2, raw_time_ms=1_000), "impossible_lap_time"),
    ],
)
def test_one_invalid_lap_in_the_middle_rolls_back_everything(client, app, run, bad_lap, code):
    error = assert_error(post_bulk(client, run["id"], [lap(1), bad_lap, lap(3)]), 422, code)
    assert error["details"][0]["field"].startswith("laps.1.")
    assert lap_count(app) == 0


def test_schema_invalid_lap_in_batch_rolls_back(client, app, run):
    response = post_bulk(client, run["id"], [lap(1), lap(2, penalty_duration_ms=-1)])
    error = assert_error(response, 422, "request_validation_failed")
    assert error["details"][0]["field"] == "laps.1.penalty_duration_ms"
    assert lap_count(app) == 0


def test_database_failure_rolls_back_batch(client, app, run, monkeypatch):
    """Bypass the service pre-check so the UNIQUE constraint itself fails mid-flush."""
    from app.services import laps as lap_service

    post_lap(client, run["id"], lap(2))
    monkeypatch.setattr(lap_service, "_reject_existing_lap_numbers", lambda *args, **kwargs: None)
    response = post_bulk(client, run["id"], [lap(1), lap(2), lap(3)])
    assert_error(response, 409, "lap_number_taken")
    assert lap_count(app) == 1


def test_commit_failure_persists_no_laps(client, app, run):
    def fail(session):
        raise RuntimeError("simulated")

    event.listen(app.state.session_factory, "before_commit", fail)
    try:
        response = post_bulk(client, run["id"], [lap(1), lap(2)])
    finally:
        event.remove(app.state.session_factory, "before_commit", fail)
    assert_error(response, 500, "internal_error")
    assert lap_count(app) == 0


def test_empty_and_oversized_batches_are_rejected(client, app, run):
    assert_error(post_bulk(client, run["id"], []), 422, "empty_lap_batch")
    too_many = [lap(n, raw_time_ms=60_000 + n) for n in range(1, 502)]
    assert_error(post_bulk(client, run["id"], too_many), 422, "lap_batch_too_large")
    assert lap_count(app) == 0


def test_maximum_batch_size_is_accepted(client, run):
    batch = [lap(n) for n in range(1, 501)]
    response = post_bulk(client, run["id"], batch)
    assert response.status_code == 201
    assert response.json()["created_count"] == 500


def test_bulk_for_missing_run(client):
    assert_error(post_bulk(client, 999, [lap(1)]), 404, "run_not_found")


# --- Fastest lap ----------------------------------------------------------------------


def test_fastest_lap_ranks_by_effective_time_and_excludes_ineligible_laps(client, run):
    post_bulk(
        client,
        run["id"],
        [
            lap(1, lap_classification="OUT_LAP", raw_time_ms=40_000),
            lap(2, raw_time_ms=60_000, penalty_duration_ms=4_000),  # effective 64 000
            lap(3, raw_time_ms=62_000),  # effective 62 000 -> fastest
            invalid(4, raw_time_ms=58_000),  # faster but timing-invalid
            lap(5, raw_time_ms=57_000, physically_completed=False),  # faster but incomplete
            lap(6, lap_classification="ABORTED", raw_time_ms=56_000),
            lap(7, lap_classification="IN_LAP", raw_time_ms=55_000),
            invalid(8, raw_time_ms=None, reason="Transponder"),
        ],
    )
    result = fastest(client, run["id"])
    assert (result["recorded_lap_count"], result["eligible_lap_count"]) == (8, 2)
    assert result["lap"]["lap_number"] == 3
    assert result["lap"]["effective_time_ms"] == 62_000
    assert "effective_time_ms" in result["policy"]


def test_penalty_can_change_the_fastest_lap(client, run):
    post_bulk(
        client,
        run["id"],
        [lap(1, raw_time_ms=60_000, penalty_duration_ms=3_000), lap(2, raw_time_ms=62_000)],
    )
    assert fastest(client, run["id"])["lap"]["lap_number"] == 2


def test_tie_breaking_is_deterministic(client, run):
    post_bulk(
        client,
        run["id"],
        [
            lap(1, raw_time_ms=62_000, penalty_duration_ms=0),  # effective 62 000, raw 62 000
            lap(2, raw_time_ms=60_000, penalty_duration_ms=2_000),  # effective 62 000, raw 60 000
            lap(3, raw_time_ms=60_000, penalty_duration_ms=2_000),  # same as 2, higher number
        ],
    )
    assert fastest(client, run["id"])["lap"]["lap_number"] == 2


def test_no_eligible_lap_returns_null(client, ctx, run):
    post_bulk(client, run["id"], [lap(1, lap_classification="OUT_LAP"), invalid(2)])
    result = fastest(client, run["id"])
    assert (result["lap"], result["eligible_lap_count"], result["recorded_lap_count"]) == (
        None,
        0,
        2,
    )

    run_without_laps = add_run(client, ctx, run_number=2)
    result = fastest(client, run_without_laps["id"])
    assert (result["lap"], result["recorded_lap_count"]) == (None, 0)


def test_fastest_lap_for_missing_run(client):
    assert_error(client.get(f"{API}/runs/999/fastest-lap"), 404, "run_not_found")


def test_laps_have_no_update_or_delete_routes(client, run):
    created = post_lap(client, run["id"], lap()).json()
    for method in ("patch", "put", "delete"):
        assert_error(
            getattr(client, method)(f"{API}/laps/{created['id']}"), 405, "method_not_allowed"
        )
