"""Tyre compounds, sets, physical tyres and run fitment."""

import pytest
from sqlalchemy import event, func, select

from app.models import RunTireAssignment, Tire, TireSet
from tests.api_helpers import API, assert_error, test_context
from tests.tyre_helpers import (
    CORNERS,
    add_run,
    assign,
    create_compound,
    create_set,
    fit_four,
    tire_set_with_four,
)


def count(app, model) -> int:
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def ctx(client):
    return test_context(client)


@pytest.fixture
def compound(client):
    return create_compound(client)


# --- Compounds --------------------------------------------------------------------------


def test_create_get_and_list_compounds(client):
    created = create_compound(client, "  Hoosier ", " R25B ")
    assert created == {
        "id": created["id"],
        "manufacturer": "Hoosier",
        "name": "R25B",
        "notes": None,
    }
    assert client.get(f"{API}/tire-compounds/{created['id']}").json() == created
    create_compound(client, "Continental", "C19")
    create_compound(client, "Hoosier", "LC0")
    page = client.get(f"{API}/tire-compounds").json()
    assert [(c["manufacturer"], c["name"]) for c in page["items"]] == [
        ("Continental", "C19"),
        ("Hoosier", "LC0"),
        ("Hoosier", "R25B"),
    ]
    assert page["order_by"] == ["manufacturer asc", "name asc", "id asc"]


def test_compound_unique_per_manufacturer(client):
    create_compound(client, "Hoosier", "R25B")
    response = client.post(
        f"{API}/tire-compounds", json={"manufacturer": "Hoosier", "name": "R25B"}
    )
    assert_error(response, 409, "tire_compound_conflict")
    assert (
        client.post(
            f"{API}/tire-compounds", json={"manufacturer": "Avon", "name": "R25B"}
        ).status_code
        == 201
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"manufacturer": " ", "name": "X"},
        {"manufacturer": "X"},
        {"manufacturer": "X", "name": "Y", "category": "soft"},
    ],
)
def test_invalid_compound_payloads(client, payload):
    assert_error(
        client.post(f"{API}/tire-compounds", json=payload), 422, "request_validation_failed"
    )


def test_missing_compound(client):
    assert_error(client.get(f"{API}/tire-compounds/9"), 404, "tire_compound_not_found")


# --- Sets and tyres ------------------------------------------------------------------------


def test_create_set_with_tyres_atomically(client, compound):
    tire_set = create_set(client, compound["id"], "SET-01", serials=["S1", "S2"])
    assert tire_set["compound"] == compound
    assert [t["serial_number"] for t in tire_set["tires"]] == ["S1", "S2"]
    assert client.get(f"{API}/tire-sets/{tire_set['id']}").json() == tire_set
    for tire in client.get(f"{API}/tires", params={"tire_set_id": tire_set["id"]}).json()["items"]:
        assert tire["compound_id"] == compound["id"]  # tyres take the set's compound


def test_set_with_missing_compound_or_duplicate_code(client, compound):
    response = client.post(f"{API}/tire-sets", json={"set_code": "X", "compound_id": 99})
    error = assert_error(response, 422, "referenced_resource_not_found")
    assert error["details"][0]["field"] == "compound_id"
    create_set(client, compound["id"], "SET-01")
    response = client.post(
        f"{API}/tire-sets", json={"set_code": "SET-01", "compound_id": compound["id"]}
    )
    assert_error(response, 409, "tire_set_code_taken")


def test_set_creation_rolls_back_when_a_tyre_serial_is_taken(client, app, compound):
    client.post(f"{API}/tires", json={"serial_number": "DUP", "compound_id": compound["id"]})
    response = client.post(
        f"{API}/tire-sets",
        json={
            "set_code": "SET-X",
            "compound_id": compound["id"],
            "tires": [{"serial_number": "NEW"}, {"serial_number": "DUP"}],
        },
    )
    assert_error(response, 409, "tire_identifier_taken")
    assert (count(app, TireSet), count(app, Tire)) == (0, 1)


def test_filter_sets_by_compound(client, compound):
    other = create_compound(client, "Avon", "A1")
    create_set(client, compound["id"], "B-SET")
    create_set(client, other["id"], "A-SET")
    page = client.get(f"{API}/tire-sets", params={"compound_id": other["id"]}).json()
    assert [s["set_code"] for s in page["items"]] == ["A-SET"]
    assert "tires" not in page["items"][0]


def test_standalone_tyre_requires_compound(client, compound):
    response = client.post(f"{API}/tires", json={"serial_number": "SPARE"})
    assert_error(response, 422, "tire_compound_required")
    created = client.post(
        f"{API}/tires", json={"serial_number": "SPARE", "compound_id": compound["id"]}
    ).json()
    assert (created["tire_set_id"], created["compound"]) == (None, compound)


def test_tyre_in_set_inherits_compound_and_rejects_a_different_one(client, compound):
    other = create_compound(client, "Avon", "A1")
    tire_set = create_set(client, compound["id"])
    inherited = client.post(
        f"{API}/tires", json={"serial_number": "T1", "tire_set_id": tire_set["id"]}
    ).json()
    assert inherited["compound_id"] == compound["id"]
    response = client.post(
        f"{API}/tires",
        json={"serial_number": "T2", "tire_set_id": tire_set["id"], "compound_id": other["id"]},
    )
    assert_error(response, 422, "tire_compound_mismatch")


def test_serial_numbers_are_globally_unique(client, compound):
    other_set = create_set(client, compound["id"], "SET-02")
    client.post(f"{API}/tires", json={"serial_number": "SN-1", "compound_id": compound["id"]})
    response = client.post(
        f"{API}/tires", json={"serial_number": "SN-1", "tire_set_id": other_set["id"]}
    )
    error = assert_error(response, 409, "tire_identifier_taken")
    assert error["details"][0]["field"] == "serial_number"


def test_missing_set_and_missing_tyre(client):
    response = client.post(f"{API}/tires", json={"serial_number": "X", "tire_set_id": 77})
    assert_error(response, 422, "referenced_resource_not_found")
    assert_error(client.get(f"{API}/tires/77"), 404, "tire_not_found")
    assert_error(client.get(f"{API}/tire-sets/77"), 404, "tire_set_not_found")


def test_list_tyres_with_exact_serial_and_pagination(client, compound):
    for serial in ("C", "A", "B", "AB"):
        client.post(f"{API}/tires", json={"serial_number": serial, "compound_id": compound["id"]})
    page = client.get(f"{API}/tires", params={"limit": 2}).json()
    assert [t["serial_number"] for t in page["items"]] == ["A", "AB"]
    assert page["total"] == 4
    exact = client.get(f"{API}/tires", params={"serial_number": "A"}).json()
    assert [t["serial_number"] for t in exact["items"]] == ["A"]  # exact, not prefix


# --- Fitment -------------------------------------------------------------------------------


def test_assign_four_corners_atomically_in_fixed_order(client, ctx, compound):
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    assignments = fit_four(client, run["id"], reversed(tires))
    assert [a["corner"] for a in assignments] == list(CORNERS)
    assert assignments[0]["tire"]["compound"] == compound
    assert client.get(f"{API}/runs/{run['id']}/tire-assignments").json() == assignments


def test_partial_assignment_then_remaining_corners(client, ctx, compound):
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    assert assign(client, run["id"], [("FL", tires[0]["id"])]).status_code == 201
    response = assign(client, run["id"], [("FR", tires[1]["id"]), ("RL", tires[2]["id"])])
    assert [a["corner"] for a in response.json()] == ["FL", "FR", "RL"]


@pytest.mark.parametrize(
    ("make_pairs", "code"),
    [
        (lambda t: [("FL", t[0]["id"]), ("FL", t[1]["id"])], "duplicate_tire_corner"),
        (lambda t: [("FL", t[0]["id"]), ("FR", t[0]["id"])], "duplicate_tire_assignment"),
    ],
)
def test_in_request_duplicates_are_rejected(client, app, ctx, compound, make_pairs, code):
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    error = assert_error(assign(client, run["id"], make_pairs(tires)), 422, code)
    assert len(error["details"]) == 2
    assert count(app, RunTireAssignment) == 0


def test_collision_with_existing_assignment_rejects_whole_request(client, app, ctx, compound):
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    assign(client, run["id"], [("FL", tires[0]["id"])])
    corner_taken = assign(client, run["id"], [("FR", tires[1]["id"]), ("FL", tires[2]["id"])])
    error = assert_error(corner_taken, 409, "tire_assignment_conflict")
    assert error["details"] == [
        {"field": "assignments.1.corner", "issue": "Corner FL already has a tyre."}
    ]
    tyre_used = assign(client, run["id"], [("RR", tires[0]["id"])])
    assert_error(tyre_used, 409, "tire_assignment_conflict")
    assert count(app, RunTireAssignment) == 1


def test_one_missing_tyre_rolls_back_the_batch(client, app, ctx, compound):
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    error = assert_error(
        assign(client, run["id"], [("FL", tires[0]["id"]), ("FR", 999)]),
        422,
        "referenced_resource_not_found",
    )
    assert error["details"][0]["field"] == "assignments.1.tire_id"
    assert count(app, RunTireAssignment) == 0


def test_database_backstop_rolls_back_the_batch(client, app, ctx, compound, monkeypatch):
    """Even if the service pre-check is bypassed, the PK makes the batch fail as a whole."""
    from app.services import tyres as tyre_service

    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    assign(client, run["id"], [("RR", tires[3]["id"])])
    original_select = tyre_service.select

    def no_existing(*args, **kwargs):
        statement = original_select(*args, **kwargs)
        if args and args[0] is RunTireAssignment:
            return statement.where(RunTireAssignment.run_id == -1)
        return statement

    monkeypatch.setattr(tyre_service, "select", no_existing)
    response = assign(client, run["id"], [("FL", tires[0]["id"]), ("RR", tires[1]["id"])])
    error = assert_error(response, 409, "tire_assignment_conflict")
    # Field "corner" (not "assignments.1.corner") proves the primary key, not the pre-check, fired.
    assert error["details"][0]["field"] == "corner"
    assert count(app, RunTireAssignment) == 1


def test_assignment_commit_failure_persists_nothing(client, app, ctx, compound):
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)

    def fail(session):
        raise RuntimeError("simulated")

    event.listen(app.state.session_factory, "before_commit", fail)
    try:
        response = assign(client, run["id"], [("FL", tires[0]["id"])])
    finally:
        event.remove(app.state.session_factory, "before_commit", fail)
    assert_error(response, 500, "internal_error")
    assert count(app, RunTireAssignment) == 0


def test_same_tyre_across_runs_including_unexpected_runs(client, ctx, compound):
    _, tires = tire_set_with_four(client, compound["id"])
    plan = client.post(
        f"{API}/tests/{ctx['test']['id']}/planned-runs", json={"sequence_number": 1}
    ).json()
    planned = add_run(client, ctx, 1, planned_run_id=plan["id"])
    retry = add_run(client, ctx, 2, planned_run_id=plan["id"])
    unexpected = add_run(client, ctx, 3)
    for run in (planned, retry, unexpected):
        fit_four(client, run["id"], tires)


def test_assignment_validation_errors(client, ctx, compound):
    run = add_run(client, ctx)
    assert_error(assign(client, 999, [("FL", 1)]), 404, "run_not_found")
    assert_error(assign(client, run["id"], []), 422, "empty_tire_assignment_batch")
    assert_error(assign(client, run["id"], [("XX", 1)]), 422, "request_validation_failed")
    too_many = [(c, i) for i, c in enumerate(CORNERS * 2, start=1)]
    assert_error(assign(client, run["id"], too_many), 422, "request_validation_failed")
    assert_error(client.get(f"{API}/runs/999/tire-assignments"), 404, "run_not_found")


def test_fitment_has_no_update_or_delete(client, ctx, compound):
    run = add_run(client, ctx)
    for method in ("patch", "put", "delete"):
        response = getattr(client, method)(f"{API}/runs/{run['id']}/tire-assignments")
        assert_error(response, 405, "method_not_allowed")


def test_listing_assignments_uses_a_fixed_number_of_queries(app, client, ctx, compound):
    _, tires = tire_set_with_four(client, compound["id"])
    run = add_run(client, ctx)
    fit_four(client, run["id"], tires)
    statements = []

    def record(*args):
        statements.append(args[2])

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        client.get(f"{API}/runs/{run['id']}/tire-assignments")
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)
    assert len(statements) == 2  # run existence + assignments joined with tyre and compound
