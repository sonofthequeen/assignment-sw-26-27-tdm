"""Planned-run lifecycle, actual-run workflow and planned-versus-actual comparison."""

import pytest
from sqlalchemy import event, func, select

from app.models import PlannedRun
from tests.api_helpers import (
    API,
    assert_error,
    create_driver,
    create_layout,
    create_location,
    create_test,
    test_context,
)


@pytest.fixture
def ctx(client):
    return test_context(client)


def add_plan(client, ctx, sequence_number=1, **extra) -> dict:
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/planned-runs",
        json={"sequence_number": sequence_number, **extra},
    )
    assert response.status_code == 201, response.json()
    return response.json()


def add_run(client, ctx, run_number=1, **extra):
    return client.post(
        f"{API}/tests/{ctx['test']['id']}/runs",
        json={
            "run_number": run_number,
            "driver_id": ctx["driver"]["id"],
            "track_layout_id": ctx["layout"]["id"],
            **extra,
        },
    )


def cancel(client, plan_id, reason="Rain"):
    return client.post(f"{API}/planned-runs/{plan_id}/cancel", json={"cancellation_reason": reason})


def replace(client, plan_id, sequence_number=2, reason="Driver unavailable", **replacement):
    return client.post(
        f"{API}/planned-runs/{plan_id}/replace",
        json={
            "replacement_reason": reason,
            "replacement": {"sequence_number": sequence_number, **replacement},
        },
    )


def complete(client, plan_id):
    return client.post(f"{API}/planned-runs/{plan_id}/complete")


def plan_count(app) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(PlannedRun))


# --- Cancel -----------------------------------------------------------------------


def test_cancel_preserves_planned_values(client, ctx):
    plan = add_plan(client, ctx, expected_lap_count=12, expected_control_map="MAP-A")
    response = cancel(client, plan["id"], "  Rain on track  ")
    assert response.status_code == 200
    cancelled = response.json()
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "Rain on track"
    unchanged = {k: v for k, v in plan.items() if k not in ("status", "cancellation_reason")}
    assert {k: cancelled[k] for k in unchanged} == unchanged
    assert client.get(f"{API}/planned-runs/{plan['id']}").json() == cancelled


@pytest.mark.parametrize("payload", [{"cancellation_reason": "   "}, {}, {"reason": "x"}])
def test_cancel_requires_a_reason(client, ctx, payload):
    plan = add_plan(client, ctx)
    response = client.post(f"{API}/planned-runs/{plan['id']}/cancel", json=payload)
    assert_error(response, 422, "request_validation_failed")
    assert client.get(f"{API}/planned-runs/{plan['id']}").json()["status"] == "PLANNED"


def test_cannot_cancel_a_cancelled_plan(client, ctx):
    plan = add_plan(client, ctx)
    cancel(client, plan["id"])
    error = assert_error(cancel(client, plan["id"]), 409, "planned_run_already_cancelled")
    assert error["details"] == [{"field": "status", "issue": "Current status is CANCELLED."}]


def test_cannot_cancel_a_replaced_plan(client, ctx):
    plan = add_plan(client, ctx)
    replace(client, plan["id"])
    assert_error(cancel(client, plan["id"]), 409, "planned_run_already_replaced")


def test_cannot_cancel_a_completed_plan(client, ctx):
    plan = add_plan(client, ctx)
    add_run(client, ctx, planned_run_id=plan["id"])
    complete(client, plan["id"])
    assert_error(cancel(client, plan["id"]), 409, "planned_run_already_completed")


def test_commands_on_missing_plan_return_404(client):
    assert_error(cancel(client, 999), 404, "planned_run_not_found")
    assert_error(replace(client, 999), 404, "planned_run_not_found")
    assert_error(complete(client, 999), 404, "planned_run_not_found")


# --- Replace ----------------------------------------------------------------------


def test_replace_creates_linked_plan_and_preserves_original(client, ctx):
    driver_b = create_driver(client, "DRV-B", "Driver B")
    original = add_plan(
        client, ctx, expected_driver_id=ctx["driver"]["id"], expected_lap_count=10, notes="Baseline"
    )
    response = replace(
        client,
        original["id"],
        sequence_number=5,
        expected_driver_id=driver_b["id"],
        expected_lap_count=8,
    )
    assert response.status_code == 201, response.json()
    replaced, replacement = response.json()["replaced"], response.json()["replacement"]

    assert replaced["status"] == "REPLACED"
    assert replaced["replaced_by_planned_run_id"] == replacement["id"]
    assert replaced["replacement_reason"] == "Driver unavailable"
    for field in ("expected_driver_id", "expected_lap_count", "notes", "sequence_number"):
        assert replaced[field] == original[field]

    assert replacement["status"] == "PLANNED"
    assert replacement["test_id"] == original["test_id"]
    assert (replacement["sequence_number"], replacement["expected_lap_count"]) == (5, 8)
    assert replacement["replaces"] == [
        {"id": original["id"], "sequence_number": 1, "status": "REPLACED"}
    ]
    assert client.get(f"{API}/planned-runs/{original['id']}").json() == replaced


def test_replacement_with_duplicate_sequence_number_rolls_back(client, app, ctx):
    plan = add_plan(client, ctx, sequence_number=1)
    add_plan(client, ctx, sequence_number=2)
    before = plan_count(app)
    assert_error(replace(client, plan["id"], sequence_number=2), 409, "planned_run_sequence_taken")
    assert plan_count(app) == before
    assert client.get(f"{API}/planned-runs/{plan['id']}").json()["status"] == "PLANNED"


def test_replacement_reusing_its_own_sequence_number_is_rejected(client, ctx):
    plan = add_plan(client, ctx, sequence_number=1)
    assert_error(replace(client, plan["id"], sequence_number=1), 409, "planned_run_sequence_taken")


@pytest.mark.parametrize("prior", ["cancel", "replace", "complete"])
def test_cannot_replace_a_terminal_plan(client, ctx, prior):
    plan = add_plan(client, ctx)
    if prior == "cancel":
        cancel(client, plan["id"])
    elif prior == "replace":
        replace(client, plan["id"], sequence_number=2)
    else:
        add_run(client, ctx, planned_run_id=plan["id"])
        complete(client, plan["id"])
    expected = {
        "cancel": "planned_run_already_cancelled",
        "replace": "planned_run_already_replaced",
        "complete": "planned_run_already_completed",
    }[prior]
    assert_error(replace(client, plan["id"], sequence_number=9), 409, expected)


def test_replacement_cannot_target_another_test_or_set_its_own_status(client, ctx):
    plan = add_plan(client, ctx)
    for extra in ({"test_id": 999}, {"status": "COMPLETED"}, {"replaced_by_planned_run_id": 1}):
        response = replace(client, plan["id"], sequence_number=2, **extra)
        assert_error(response, 422, "request_validation_failed")


def test_replacement_with_invalid_expected_references_is_rejected(client, ctx):
    plan = add_plan(client, ctx)
    elsewhere = create_layout(client, create_location(client, "Elsewhere")["id"])
    error = assert_error(
        replace(client, plan["id"], expected_track_layout_id=elsewhere["id"]),
        422,
        "track_layout_not_at_test_location",
    )
    assert error["details"][0]["field"] == "replacement.expected_track_layout_id"
    error = assert_error(
        replace(client, plan["id"], expected_driver_id=999), 422, "referenced_resource_not_found"
    )
    assert error["details"][0]["field"] == "replacement.expected_driver_id"


def test_replace_requires_reason(client, ctx):
    plan = add_plan(client, ctx)
    assert_error(replace(client, plan["id"], reason=" "), 422, "request_validation_failed")


def test_replace_is_atomic_when_the_commit_fails(client, app, ctx):
    plan = add_plan(client, ctx)
    before = plan_count(app)

    def fail_commit(session):
        raise RuntimeError("simulated")

    event.listen(app.state.session_factory, "before_commit", fail_commit)
    try:
        response = replace(client, plan["id"])
    finally:
        event.remove(app.state.session_factory, "before_commit", fail_commit)

    assert_error(response, 500, "internal_error")
    assert plan_count(app) == before
    reloaded = client.get(f"{API}/planned-runs/{plan['id']}").json()
    assert (reloaded["status"], reloaded["replaced_by_planned_run_id"]) == ("PLANNED", None)


# --- Complete ---------------------------------------------------------------------


def test_complete_requires_a_recorded_run(client, ctx):
    plan = add_plan(client, ctx)
    assert_error(complete(client, plan["id"]), 409, "planned_run_not_executed")
    add_run(client, ctx, planned_run_id=plan["id"])
    response = complete(client, plan["id"])
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert_error(complete(client, plan["id"]), 409, "planned_run_already_completed")


# --- Actual runs against plans ----------------------------------------------------


def test_multiple_attempts_are_listed_on_the_plan(client, ctx):
    plan = add_plan(client, ctx, expected_lap_count=10)
    aborted = add_run(client, ctx, 1, planned_run_id=plan["id"], deviation_reason="Aborted lap 2")
    retry = add_run(client, ctx, 2, planned_run_id=plan["id"])
    assert aborted.status_code == retry.status_code == 201
    complete(client, plan["id"])
    # A further attempt after completion stays allowed and visible.
    assert add_run(client, ctx, 3, planned_run_id=plan["id"]).status_code == 201

    detail = client.get(f"{API}/planned-runs/{plan['id']}").json()
    assert [r["run_number"] for r in detail["runs"]] == [1, 2, 3]
    assert detail["expected_lap_count"] == 10  # planned values untouched by actual runs


@pytest.mark.parametrize("prior", ["cancel", "replace"])
def test_runs_cannot_be_recorded_against_cancelled_or_replaced_plans(client, ctx, prior):
    plan = add_plan(client, ctx)
    if prior == "cancel":
        cancel(client, plan["id"])
    else:
        replace(client, plan["id"], sequence_number=2)
    error = assert_error(
        add_run(client, ctx, planned_run_id=plan["id"]), 409, "planned_run_state_conflict"
    )
    assert error["details"][0]["field"] == "planned_run_id"


def test_unexpected_run_still_allowed_alongside_plans(client, ctx):
    add_plan(client, ctx)
    response = add_run(client, ctx, deviation_reason="Extra shakedown")
    assert response.status_code == 201
    assert response.json()["planned_run_id"] is None


def test_plan_from_another_test_is_rejected_before_its_state(client, ctx):
    other = create_test(
        client, ctx["season"]["id"], ctx["vehicle"]["id"], ctx["location"]["id"], "2026-03-09"
    )
    foreign = client.post(
        f"{API}/tests/{other['id']}/planned-runs", json={"sequence_number": 1}
    ).json()
    cancel(client, foreign["id"])
    assert_error(add_run(client, ctx, planned_run_id=foreign["id"]), 422, "planned_run_not_in_test")


# --- Planned versus actual --------------------------------------------------------


def comparison(client, run_id) -> dict:
    response = client.get(f"{API}/runs/{run_id}/plan-comparison")
    assert response.status_code == 200, response.json()
    body = response.json()
    body["by_aspect"] = {item["aspect"]: item for item in body["items"]}
    return body


def create_snapshot(client, vehicle_id, **extra) -> dict:
    response = client.post(f"{API}/setup-snapshots", json={"vehicle_id": vehicle_id, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


def test_comparison_reports_matches_differences_and_unavailable_values(client, ctx):
    driver_b = create_driver(client, "DRV-B", "Driver B")
    planned_setup = create_snapshot(client, ctx["vehicle"]["id"], control_map="MAP-A")
    actual_setup = client.post(
        f"{API}/setup-snapshots/{planned_setup['id']}/derive",
        json={"change_reason": "More rear wing", "control_map": "MAP-B"},
    ).json()
    plan = add_plan(
        client,
        ctx,
        expected_driver_id=ctx["driver"]["id"],
        expected_track_layout_id=ctx["layout"]["id"],
        expected_setup_snapshot_id=planned_setup["id"],
        expected_control_map="MAP-A",
        expected_lap_count=10,
        target_lap_time_ms=61_000,
        expected_energy_limit_kwh="4.000",
    )
    run = add_run(
        client,
        ctx,
        planned_run_id=plan["id"],
        driver_id=driver_b["id"],
        setup_snapshot_id=actual_setup["id"],
        deviation_reason="Driver swap",
    ).json()

    result = comparison(client, run["id"])
    items = result["by_aspect"]
    assert (result["unexpected"], result["deviation_reason"]) == (False, "Driver swap")
    assert items["driver_id"] == {
        "aspect": "driver_id",
        "expected": ctx["driver"]["id"],
        "actual": driver_b["id"],
        "status": "DIFFERENT",
        "note": None,
    }
    assert items["track_layout_id"]["status"] == "MATCH"
    assert items["setup_snapshot_id"]["status"] == "DIFFERENT"
    assert f"/setup-snapshots/{actual_setup['id']}/diff" in items["setup_snapshot_id"]["note"]
    assert (items["control_map"]["expected"], items["control_map"]["actual"]) == ("MAP-A", "MAP-B")
    assert items["control_map"]["status"] == "DIFFERENT"
    # Actual energy use is not modelled at all.
    assert items["energy_limit_kwh"]["status"] == "NOT_YET_SUPPORTED"
    assert items["energy_limit_kwh"]["actual"] is None
    # No laps recorded yet: absence of lap data is not reported as zero laps.
    for aspect in ("lap_count", "target_lap_time_ms"):
        assert items[aspect]["status"] == "ACTUAL_NOT_RECORDED"
        assert items[aspect]["actual"] is None
    assert items["lap_count"]["expected"] == 10


def test_comparison_of_unexpected_run(client, ctx):
    run = add_run(client, ctx).json()
    result = comparison(client, run["id"])
    assert (result["unexpected"], result["planned_run_id"]) == (True, None)
    assert result["by_aspect"]["driver_id"] == {
        "aspect": "driver_id",
        "expected": None,
        "actual": ctx["driver"]["id"],
        "status": "NO_PLAN",
        "note": None,
    }


def test_comparison_without_expectations_and_without_actual_setup(client, ctx):
    plan = add_plan(client, ctx, expected_setup_snapshot_id=None)
    run = add_run(client, ctx, planned_run_id=plan["id"]).json()
    items = comparison(client, run["id"])["by_aspect"]
    assert items["driver_id"]["status"] == "NOT_PLANNED"
    assert items["setup_snapshot_id"]["status"] == "NOT_PLANNED"

    planned_setup = create_snapshot(client, ctx["vehicle"]["id"], power_limit_kw="80")
    plan2 = add_plan(client, ctx, 2, expected_setup_snapshot_id=planned_setup["id"])
    run2 = add_run(client, ctx, 2, planned_run_id=plan2["id"]).json()
    assert comparison(client, run2["id"])["by_aspect"]["setup_snapshot_id"]["status"] == (
        "ACTUAL_NOT_RECORDED"
    )


def test_identical_setup_values_in_different_snapshots_count_as_match(client, ctx):
    a = create_snapshot(client, ctx["vehicle"]["id"], power_limit_kw="80.00")
    b = create_snapshot(client, ctx["vehicle"]["id"], power_limit_kw="80")
    plan = add_plan(client, ctx, expected_setup_snapshot_id=a["id"])
    run = add_run(client, ctx, planned_run_id=plan["id"], setup_snapshot_id=b["id"]).json()
    item = comparison(client, run["id"])["by_aspect"]["setup_snapshot_id"]
    assert (item["status"], item["note"]) == (
        "MATCH",
        "Different snapshot with identical setup values.",
    )


def test_comparison_for_missing_run_returns_404(client):
    assert_error(client.get(f"{API}/runs/999/plan-comparison"), 404, "run_not_found")
