"""tire_compound_id in historical search and fastest-lap analytics."""

import pytest
from sqlalchemy import event

from tests.api_helpers import API, post_ok
from tests.historical_fixtures import build_history, search
from tests.tyre_helpers import CORNERS, create_compound, tire_set_with_four


@pytest.fixture
def h(client):
    """History from historical_fixtures plus fitment:

    r1: four soft tyres; r4: four hard tyres; r6: mixed (FL/FR soft, RL/RR hard);
    r2, r3, r5: no tyres recorded.
    """
    history = build_history(client)
    soft = create_compound(client, "Hoosier", "SOFT")
    hard = create_compound(client, "Hoosier", "HARD")
    _, soft_a = tire_set_with_four(client, soft["id"], "SOFT-A")
    _, soft_b = tire_set_with_four(client, soft["id"], "SOFT-B")
    _, hard_a = tire_set_with_four(client, hard["id"], "HARD-A")

    def fit(run, pairs):
        post_ok(
            client,
            f"/runs/{run['id']}/tire-assignments",
            {"assignments": [{"corner": c, "tire_id": t["id"]} for c, t in pairs]},
        )

    runs = history["runs"]
    fit(runs["r1"], zip(CORNERS, soft_a, strict=True))
    fit(runs["r4"], zip(CORNERS, hard_a, strict=True))
    fit(runs["r6"], [("FL", soft_b[0]), ("FR", soft_b[1]), ("RL", hard_a[2]), ("RR", hard_a[3])])
    history["compounds"] = {"soft": soft, "hard": hard}
    return history


def names(h, page) -> list[str]:
    by_id = {run["id"]: name for name, run in h["runs"].items()}
    return [by_id[item["id"]] for item in page["items"]]


def test_compound_alone_matches_any_fitted_tyre_without_duplicates(client, h):
    soft = search(client, tire_compound_id=h["compounds"]["soft"]["id"])
    # r1 has four matching corners and r6 two, yet each run appears once.
    assert names(h, soft) == ["r6", "r1"]
    assert soft["total"] == 2
    assert names(h, search(client, tire_compound_id=h["compounds"]["hard"]["id"])) == ["r6", "r4"]


def test_runs_without_fitment_are_excluded_only_under_a_compound_filter(client, h):
    assert "r2" in names(h, search(client))
    assert "r2" not in names(h, search(client, tire_compound_id=h["compounds"]["soft"]["id"]))


def test_compound_combined_with_season_and_driver(client, h):
    soft = h["compounds"]["soft"]["id"]
    assert names(h, search(client, tire_compound_id=soft, season_id=h["seasons"]["S1"]["id"])) == [
        "r1"
    ]
    assert names(h, search(client, tire_compound_id=soft, driver_id=h["drivers"]["D2"]["id"])) == [
        "r6"
    ]


def test_readme_query_season_driver_compound_and_asphalt_range(client, h):
    """README: current season, driver X, compound Y, asphalt 30-40 °C."""
    params = {
        "season_id": h["seasons"]["S1"]["id"],
        "driver_id": h["drivers"]["D1"]["id"],
        "tire_compound_id": h["compounds"]["hard"]["id"],
        "asphalt_temperature_min_c": "30",
        "asphalt_temperature_max_c": "40",
    }
    assert names(h, search(client, **params)) == ["r4"]
    params["tire_compound_id"] = h["compounds"]["soft"]["id"]
    assert names(h, search(client, **params)) == ["r1"]
    params["asphalt_temperature_min_c"] = "31"
    assert search(client, **params)["total"] == 0


def test_unknown_compound_matches_nothing(client, h):
    assert search(client, tire_compound_id=999)["total"] == 0


def test_query_count_stays_constant_with_compound_filter(app, client, h):
    statements = []

    def record(*args):
        statements.append(args[2])

    event.listen(app.state.engine, "before_cursor_execute", record)
    try:
        search(client, tire_compound_id=h["compounds"]["hard"]["id"])
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record)
    assert len(statements) == 4


def test_fastest_lap_analytics_share_the_compound_filter(client, h):
    response = client.get(
        f"{API}/analytics/fastest-laps",
        params={
            "track_layout_id": h["layouts"]["AX"]["id"],
            "tire_compound_id": h["compounds"]["soft"]["id"],
        },
    )
    times = [lap["effective_time_ms"] for lap in response.json()["items"]]
    # Soft tyres were on r1 (64 000, 65 000) and partly on r6 (63 000, 63 500).
    assert times == [63_000, 63_500, 64_000, 65_000]
