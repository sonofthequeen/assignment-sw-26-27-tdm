"""Deterministic demonstration seed (scripts/seed.py)."""

import pytest
from sqlalchemy import func, select

from app.models import Base
from scripts import seed as seed_module
from tests.api_helpers import API


def counts(app) -> dict[str, int]:
    with app.state.session_factory() as session:
        return {
            name: session.scalar(select(func.count()).select_from(table))
            for name, table in Base.metadata.tables.items()
        }


@pytest.fixture
def seeded(app):
    with app.state.session_factory.begin() as session:
        report = seed_module.seed(session)
    assert report.status == "created"
    return report


def ids(client, path, key="code", **params) -> dict:
    items = client.get(f"{API}{path}", params={"limit": 100, **params}).json()["items"]
    return {item[key]: item["id"] for item in items}


def test_seed_populates_every_table(app, seeded):
    totals = counts(app)
    assert all(totals[name] > 0 for name in totals), {k: v for k, v in totals.items() if not v}
    assert seeded.created == totals  # empty database: created == present
    assert totals["season"] == 2 and totals["vehicle"] == 2 and totals["driver"] == 3


def test_seed_is_deterministic(app, seeded, client):
    first = client.get(f"{API}/runs", params={"limit": 100}).json()
    assert [item["distance_m"] for item in first["items"]] == [
        item["distance_m"]
        for item in client.get(f"{API}/runs", params={"limit": 100}).json()["items"]
    ]
    assert first["total"] == 6


def test_repeat_seed_writes_nothing(app, seeded):
    before = counts(app)
    with app.state.session_factory.begin() as session:
        assert seed_module.seed(session).status == "already_present"
    assert counts(app) == before


def test_failed_seed_rolls_back_completely(app, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure half-way")

    monkeypatch.setattr(seed_module.files, "register_file", boom)  # the last step
    with pytest.raises(RuntimeError), app.state.session_factory.begin() as session:
        seed_module.seed(session)
    assert set(counts(app).values()) == {0}


def test_cli_seed_and_repeat(db_url, capsys):
    assert seed_module.main(["--database-url", db_url]) == 0
    assert "Demo data created" in capsys.readouterr().out
    assert seed_module.main(["--database-url", db_url]) == 0
    assert "already present" in capsys.readouterr().out


# --- The dataset demonstrates the required scenarios -----------------------------------


def test_official_query_season_driver_compound_asphalt(client, seeded):
    season = ids(client, "/seasons", "name")["DEMO 2025/26"]
    driver = ids(client, "/drivers")["DEMO-ADA"]
    soft = ids(client, "/tire-compounds", "name")["SOFT-D"]
    page = client.get(
        f"{API}/runs",
        params={
            "season_id": season,
            "driver_id": driver,
            "tire_compound_id": soft,
            "asphalt_temperature_min_c": "30",
            "asphalt_temperature_max_c": "40",
        },
    ).json()
    # Runs 1, 3 (aborted attempt, mixed soft/medium) and 4 (retry) of the autocross day.
    assert [item["run_number"] for item in page["items"]] == [1, 3, 4]
    assert page["items"][0]["fastest_lap"]["effective_time_ms"] == 62_450


def test_edge_cases_are_present(client, seeded):
    tests = client.get(f"{API}/tests").json()["items"]
    autocross_day = next(t for t in tests if t["test_date"] == "2025-10-12")
    summary = client.get(f"{API}/tests/{autocross_day['id']}/plan-vs-actual").json()
    assert summary["counts"] == {
        "planned_runs": 5,
        "executed": 2,
        "not_executed": 1,
        "cancelled": 1,
        "replaced": 1,
        "with_repeated_attempts": 1,
        "actual_runs": 4,
        "unexpected_runs": 1,
    }
    runs = client.get(f"{API}/tests/{autocross_day['id']}/runs").json()["items"]
    laps = client.get(f"{API}/runs/{runs[0]['id']}/laps").json()["items"]
    kinds = {
        (lap["lap_classification"], lap["timing_valid"], lap["raw_time_ms"] is None) for lap in laps
    }
    assert ("OUT_LAP", True, False) in kinds and ("IN_LAP", True, False) in kinds
    assert ("FLYING", False, True) in kinds  # untimed but completed
    assert any(lap["penalty_duration_ms"] for lap in laps)
    aborted = client.get(f"{API}/runs/{runs[2]['id']}/laps").json()["items"]
    assert {(lap["lap_classification"], lap["physically_completed"]) for lap in aborted} >= {
        ("ABORTED", True),
        ("ABORTED", False),
    }


def test_mileage_at_every_scope_is_deterministic(client, seeded):
    driver = ids(client, "/drivers")["DEMO-ADA"]
    season = ids(client, "/seasons", "name")["DEMO 2025/26"]
    vehicle = ids(client, "/vehicles")["DEMO-E25"]
    results = {
        scope: client.get(f"{API}/{scope}/{rid}/mileage").json()["distance_m"]
        for scope, rid in (("drivers", driver), ("seasons", season), ("vehicles", vehicle))
    }
    # Ada: run 1 (7 completed x 1150) + run 3 (2 completed) + run 4 (6 completed) = 15 laps
    assert results["drivers"] == "17250.000"
    # Season 1: Ada 15 x 1150 + skidpad 4 x 56.549 + endurance 9 x 1180.5 (exact decimals)
    assert results["seasons"] == "28100.696"
    assert results["vehicles"] == results["seasons"]  # season 1 used only DEMO-E25


def test_setup_derivation_measurements_objectives_and_files(client, seeded):
    snapshots = client.get(f"{API}/setup-snapshots", params={"limit": 100}).json()["items"]
    derived = next(s for s in snapshots if s["name"] == "E25 autocross rear toe +")
    diff = client.get(f"{API}/setup-snapshots/{derived['id']}/diff").json()
    assert [c["corner"] for c in diff["corner_changes"]] == ["RL", "RR"]

    runs = client.get(f"{API}/runs", params={"limit": 100}).json()["items"]
    first = next(r for r in runs if r["test"]["test_date"] == "2025-10-12" and r["run_number"] == 1)
    assert len(client.get(f"{API}/runs/{first['id']}/tire-measurements").json()) == 8
    assert len(client.get(f"{API}/runs/{first['id']}/alignment-measurements").json()) == 4
    assert client.get(f"{API}/runs/{first['id']}/objectives").json()[0]["priority"] == "HIGH"
    files = client.get(f"{API}/tests/{first['test']['id']}/files").json()
    assert files["total"] == 3
    assert all(
        f["storage_uri"].startswith("demo://") and f["metadata"]["synthetic"]
        for f in files["items"]
    )
