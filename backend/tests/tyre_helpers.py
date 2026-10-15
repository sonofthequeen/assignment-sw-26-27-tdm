"""Builders for tyre inventory and fitment (synthetic test data)."""

from tests.api_helpers import API, post_ok

CORNERS = ("FL", "FR", "RL", "RR")


def create_compound(client, manufacturer="Hoosier", name="R25B") -> dict:
    return post_ok(client, "/tire-compounds", {"manufacturer": manufacturer, "name": name})


def create_set(client, compound_id, set_code="SET-01", serials=()) -> dict:
    return post_ok(
        client,
        "/tire-sets",
        {
            "set_code": set_code,
            "compound_id": compound_id,
            "tires": [{"serial_number": s} for s in serials],
        },
    )


def tire_set_with_four(client, compound_id, set_code="SET-01") -> tuple[dict, list[dict]]:
    tire_set = create_set(
        client, compound_id, set_code, serials=[f"{set_code}-{c}" for c in CORNERS]
    )
    tires = client.get(f"{API}/tires", params={"tire_set_id": tire_set["id"]}).json()["items"]
    return tire_set, tires


def add_run(client, ctx, run_number=1, **extra) -> dict:
    return post_ok(
        client,
        f"/tests/{ctx['test']['id']}/runs",
        {
            "run_number": run_number,
            "driver_id": ctx["driver"]["id"],
            "track_layout_id": ctx["layout"]["id"],
            **extra,
        },
    )


def assign(client, run_id, pairs):
    """pairs: [(corner, tire_id), ...]"""
    return client.post(
        f"{API}/runs/{run_id}/tire-assignments",
        json={"assignments": [{"corner": c, "tire_id": t} for c, t in pairs]},
    )


def fit_four(client, run_id, tires) -> list[dict]:
    by_serial = {t["serial_number"].rsplit("-", 1)[1]: t for t in tires}
    response = assign(client, run_id, [(c, by_serial[c]["id"]) for c in CORNERS])
    assert response.status_code == 201, response.json()
    return response.json()
