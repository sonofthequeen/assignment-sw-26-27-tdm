"""Objective traceability and the telemetry/log file index."""

import hashlib

import pytest
from sqlalchemy import func, inspect, select

from app.models import RunObjective, TelemetryFile, TestObjective
from tests.api_helpers import API, assert_error, create_season, create_test, post_ok, test_context


@pytest.fixture
def ctx(client):
    context = test_context(client)
    context["run"] = post_ok(
        client,
        f"/tests/{context['test']['id']}/runs",
        {
            "run_number": 1,
            "driver_id": context["driver"]["id"],
            "track_layout_id": context["layout"]["id"],
        },
    )
    return context


def count(app, model) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def objective(client, season_id, description="Validate cooling", priority="HIGH", reps=3) -> dict:
    return post_ok(
        client,
        f"/seasons/{season_id}/objectives",
        {"description": description, "priority": priority, "desired_repetitions": reps},
    )


# --- Objectives -------------------------------------------------------------------------


def test_create_and_list_objectives_by_priority(client, ctx):
    season_id = ctx["season"]["id"]
    low = objective(client, season_id, "Low", "LOW")
    critical = objective(client, season_id, "Critical", "CRITICAL")
    high = objective(client, season_id, "High", "HIGH")
    assert critical["status"] == "OPEN"
    page = client.get(f"{API}/seasons/{season_id}/objectives").json()
    assert [o["id"] for o in page["items"]] == [critical["id"], high["id"], low["id"]]
    assert page["order_by"] == ["priority (CRITICAL first)", "id asc"]


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "X", "priority": "HIGH", "desired_repetitions": 0},
        {"description": "X", "priority": "URGENT", "desired_repetitions": 1},
        {"description": "X", "priority": "HIGH", "desired_repetitions": 1, "status": "DONE"},
        {"description": " ", "priority": "HIGH", "desired_repetitions": 1},
        {"description": "X", "priority": "HIGH", "desired_repetitions": 1, "achieved": 2},
    ],
)
def test_invalid_objectives_are_rejected(client, ctx, payload):
    response = client.post(f"{API}/seasons/{ctx['season']['id']}/objectives", json=payload)
    assert_error(response, 422, "request_validation_failed")


def test_objective_detail_derives_progress_from_linked_runs(client, ctx):
    obj = objective(client, ctx["season"]["id"], reps=3)
    post_ok(client, f"/tests/{ctx['test']['id']}/objectives", {"objective_ids": [obj["id"]]})
    post_ok(client, f"/runs/{ctx['run']['id']}/objectives", {"objective_ids": [obj["id"]]})
    detail = client.get(f"{API}/objectives/{obj['id']}").json()
    assert (detail["linked_test_count"], detail["linked_run_count"]) == (1, 1)
    assert detail["remaining_repetitions"] == 2


def test_link_lists_are_ordered_and_links_are_create_once(client, app, ctx):
    a = objective(client, ctx["season"]["id"], "A", "LOW")
    b = objective(client, ctx["season"]["id"], "B", "CRITICAL")
    linked = post_ok(
        client, f"/tests/{ctx['test']['id']}/objectives", {"objective_ids": [a["id"], b["id"]]}
    )
    assert [o["id"] for o in linked] == [b["id"], a["id"]]
    assert client.get(f"{API}/tests/{ctx['test']['id']}/objectives").json() == linked
    response = client.post(
        f"{API}/tests/{ctx['test']['id']}/objectives", json={"objective_ids": [a["id"]]}
    )
    assert_error(response, 409, "objective_link_conflict")
    assert count(app, TestObjective) == 2


def test_objectives_must_belong_to_the_season_and_batches_are_atomic(client, app, ctx):
    own = objective(client, ctx["season"]["id"])
    other_season = create_season(client, "Other season")
    foreign = objective(client, other_season["id"])
    for path in (f"/tests/{ctx['test']['id']}/objectives", f"/runs/{ctx['run']['id']}/objectives"):
        error = assert_error(
            client.post(f"{API}{path}", json={"objective_ids": [own["id"], foreign["id"]]}),
            422,
            "objective_season_mismatch",
        )
        assert error["details"][0]["field"] == "objective_ids.1"
    assert (count(app, TestObjective), count(app, RunObjective)) == (0, 0)


def test_run_objective_uses_the_parent_test_season(client, ctx):
    other_season = create_season(client, "Other season")
    other_test = create_test(
        client, other_season["id"], ctx["vehicle"]["id"], ctx["location"]["id"]
    )
    other_run = post_ok(
        client,
        f"/tests/{other_test['id']}/runs",
        {"run_number": 1, "driver_id": ctx["driver"]["id"], "track_layout_id": ctx["layout"]["id"]},
    )
    own = objective(client, ctx["season"]["id"])
    response = client.post(
        f"{API}/runs/{other_run['id']}/objectives", json={"objective_ids": [own["id"]]}
    )
    assert_error(response, 422, "objective_season_mismatch")


def test_objective_link_validation(client, ctx):
    path = f"{API}/tests/{ctx['test']['id']}/objectives"
    assert_error(client.post(path, json={"objective_ids": []}), 422, "request_validation_failed")
    assert_error(
        client.post(path, json={"objective_ids": [1, 1]}), 422, "request_validation_failed"
    )
    assert_error(
        client.post(path, json={"objective_ids": [999]}), 422, "referenced_resource_not_found"
    )
    assert_error(client.get(f"{API}/objectives/999"), 404, "objective_not_found")
    assert_error(client.get(f"{API}/seasons/999/objectives"), 404, "season_not_found")
    assert_error(client.get(f"{API}/runs/999/objectives"), 404, "run_not_found")


# --- Telemetry file index -----------------------------------------------------------------


def checksum(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def file_payload(label="log-1", **overrides) -> dict:
    values = {
        "file_type": "DATA_LOG",
        "original_filename": f"{label}.ld",
        "storage_uri": f"demo://logs/{label}.ld",
        "checksum_sha256": checksum(label),
        "size_bytes": 1_048_576,
        "metadata": {"logger": "demo", "channels": 128, "sample_rate_hz": 200.0, "complete": True},
    }
    values.update(overrides)
    return values


def test_register_test_and_run_level_files(client, ctx):
    test_file = post_ok(client, f"/tests/{ctx['test']['id']}/files", file_payload("test-log"))
    assert test_file["run_id"] is None
    assert test_file["metadata"]["channels"] == 128
    assert test_file["imported_at"].endswith("Z")
    run_file = post_ok(
        client,
        f"/tests/{ctx['test']['id']}/files",
        file_payload("run-telemetry", file_type="TELEMETRY", run_id=ctx["run"]["id"]),
    )
    assert client.get(f"{API}/files/{run_file['id']}").json() == run_file

    listed = client.get(f"{API}/tests/{ctx['test']['id']}/files").json()
    assert [f["id"] for f in listed["items"]] == [run_file["id"], test_file["id"]]
    by_run = client.get(
        f"{API}/tests/{ctx['test']['id']}/files", params={"run_id": ctx["run"]["id"]}
    )
    assert [f["id"] for f in by_run.json()["items"]] == [run_file["id"]]
    by_type = client.get(f"{API}/tests/{ctx['test']['id']}/files", params={"file_type": "DATA_LOG"})
    assert [f["id"] for f in by_type.json()["items"]] == [test_file["id"]]


def test_checksum_is_normalised_and_unique(client, app, ctx):
    upper = file_payload(checksum_sha256=checksum("log-1").upper())
    created = post_ok(client, f"/tests/{ctx['test']['id']}/files", upper)
    assert created["checksum_sha256"] == checksum("log-1")
    again = file_payload("log-1", original_filename="copy.ld")
    assert_error(
        client.post(f"{API}/tests/{ctx['test']['id']}/files", json=again),
        409,
        "file_checksum_taken",
    )
    assert count(app, TelemetryFile) == 1


def test_run_must_belong_to_the_test(client, ctx):
    other_test = create_test(
        client, ctx["season"]["id"], ctx["vehicle"]["id"], ctx["location"]["id"], "2026-03-02"
    )
    response = client.post(
        f"{API}/tests/{other_test['id']}/files", json=file_payload(run_id=ctx["run"]["id"])
    )
    assert_error(response, 422, "run_not_in_test")


@pytest.mark.parametrize(
    "overrides",
    [
        {"checksum_sha256": "abc"},
        {"checksum_sha256": "z" * 64},
        {"size_bytes": -1},
        {"original_filename": "  "},
        {"storage_uri": ""},
        {"file_type": "BINARY"},
        {"metadata": {"Bad Key": 1}},
        {"metadata": {"nested": {"a": 1}}},
        {"metadata": {"items": [1, 2]}},
        {"metadata": {"text": "x" * 501}},
        {"metadata": {f"k{i}": i for i in range(51)}},
        {"metadata": {f"k{i}": "x" * 400 for i in range(25)}},  # > 8 KB serialised
        {"content": "AAAA"},  # binary payloads are not accepted
    ],
)
def test_invalid_file_entries_are_rejected(client, app, ctx, overrides):
    response = client.post(f"{API}/tests/{ctx['test']['id']}/files", json=file_payload(**overrides))
    assert_error(response, 422, "request_validation_failed")
    assert count(app, TelemetryFile) == 0


def test_file_table_has_no_binary_column(engine):
    columns = {c["name"]: str(c["type"]) for c in inspect(engine).get_columns("telemetry_file")}
    assert not any("BLOB" in kind or "BINARY" in kind for kind in columns.values())


def test_missing_test_and_file(client):
    assert_error(client.post(f"{API}/tests/999/files", json=file_payload()), 404, "test_not_found")
    assert_error(client.get(f"{API}/files/999"), 404, "file_not_found")
