"""A small deterministic history used by the search and analytics tests.

    test  season vehicle location date        status     runs
    T1    S1     C1      L1       2026-03-01  COMPLETED  r1 (D1, AX, plan P1)
                                                         r2 (D2, SK, unexpected)
                                                         r3 (D1, AX, P1 retry; no
                                                             conditions, no laps)
    T2    S1     C1      L1       2026-03-15  PLANNED    r4 (D1, AX, plan P2)
    T3    S2     C2      L2       2027-04-10  PLANNED    r5 (D2, ACC, unexpected)
    T4    S2     C1      L1       2027-05-01  PLANNED    r6 (D2, AX, plan P3)

    conditions  ambient  asphalt
    r1          20.0     30.0
    r2          22.5     40.0
    r3          -        -        (no conditions row)
    r4          null     35.0
    r5          15.0     null
    r6          30.0     45.5

Layouts: AX autocross 1000.000 m and SK skidpad 56.549 m at L1; ACC acceleration
75.000 m at L2. All values are synthetic test data.
"""

from tests.api_helpers import (
    API,
    create_driver,
    create_layout,
    create_location,
    create_season,
    create_test,
    create_vehicle,
    post_ok,
)


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


def _run(client, test, number, driver, layout, laps=(), conditions=None, plan=None, **extra):
    payload = {
        "run_number": number,
        "driver_id": driver["id"],
        "track_layout_id": layout["id"],
        **extra,
    }
    if plan:
        payload["planned_run_id"] = plan["id"]
    run = post_ok(client, f"/tests/{test['id']}/runs", payload)
    if conditions is not None:
        post_ok(client, f"/runs/{run['id']}/conditions", conditions)
    if laps:
        post_ok(client, f"/runs/{run['id']}/laps/bulk", {"laps": list(laps)})
    return run


def build_history(client) -> dict:
    s1, s2 = create_season(client, "S1"), create_season(client, "S2")
    c1, c2 = create_vehicle(client, "C1", "Car 1"), create_vehicle(client, "C2", "Car 2")
    d1, d2 = create_driver(client, "D1", "Driver 1"), create_driver(client, "D2", "Driver 2")
    l1, l2 = create_location(client, "L1"), create_location(client, "L2")
    ax = create_layout(client, l1["id"], "AX", verified_length_m="1000.000")
    sk = create_layout(client, l1["id"], "SK", activity_type="SKIDPAD", verified_length_m="56.549")
    acc = create_layout(
        client, l2["id"], "ACC", activity_type="ACCELERATION", verified_length_m="75.000"
    )
    t1 = create_test(client, s1["id"], c1["id"], l1["id"], "2026-03-01", status="COMPLETED")
    t2 = create_test(client, s1["id"], c1["id"], l1["id"], "2026-03-15")
    t3 = create_test(client, s2["id"], c2["id"], l2["id"], "2027-04-10")
    t4 = create_test(client, s2["id"], c1["id"], l1["id"], "2027-05-01")

    p1 = post_ok(
        client, f"/tests/{t1['id']}/planned-runs", {"sequence_number": 1, "expected_lap_count": 5}
    )
    p2 = post_ok(client, f"/tests/{t2['id']}/planned-runs", {"sequence_number": 1})
    p3 = post_ok(client, f"/tests/{t4['id']}/planned-runs", {"sequence_number": 1})

    def measured(ambient, asphalt):
        return {
            "ambient_temperature_c": ambient,
            "asphalt_temperature_c": asphalt,
            "conditions_source": "MEASURED",
        }

    r1 = _run(
        client, t1, 1, d1, ax,
        laps=[
            lap(1, lap_classification="OUT_LAP", raw_time_ms=80_000),
            lap(2, raw_time_ms=65_000),
            lap(3, raw_time_ms=62_000, penalty_duration_ms=2_000),  # effective 64 000
            invalid(4, raw_time_ms=61_000),  # faster, but timing-invalid
            invalid(5, raw_time_ms=None),  # untimed, completed
            lap(6, lap_classification="IN_LAP", raw_time_ms=90_000),
        ],
        conditions=measured("20.0", "30.0"),
        plan=p1,
    )  # fmt: skip
    r2 = _run(
        client, t1, 2, d2, sk,
        laps=[lap(n, raw_time_ms=t) for n, t in ((1, 5_200), (2, 5_100), (3, 5_300))],
        conditions=measured("22.5", "40.0"),
        deviation_reason="Extra skidpad check",
    )  # fmt: skip
    r3 = _run(client, t1, 3, d1, ax, plan=p1, deviation_reason="Retry")
    r4 = _run(
        client, t2, 1, d1, ax,
        laps=[lap(1, raw_time_ms=66_000)],
        conditions={"asphalt_temperature_c": "35.0", "conditions_source": "MEASURED"},
        plan=p2,
    )  # fmt: skip
    r5 = _run(
        client, t3, 1, d2, acc,
        laps=[lap(1, raw_time_ms=4_000)],
        conditions={"ambient_temperature_c": "15.0", "conditions_source": "ESTIMATED"},
    )  # fmt: skip
    r6 = _run(
        client, t4, 1, d2, ax,
        laps=[lap(1, raw_time_ms=63_000), lap(2, raw_time_ms=63_500)],
        conditions=measured("30.0", "45.5"),
        plan=p3,
    )  # fmt: skip
    return {
        "seasons": {"S1": s1, "S2": s2},
        "vehicles": {"C1": c1, "C2": c2},
        "drivers": {"D1": d1, "D2": d2},
        "locations": {"L1": l1, "L2": l2},
        "layouts": {"AX": ax, "SK": sk, "ACC": acc},
        "tests": {"T1": t1, "T2": t2, "T3": t3, "T4": t4},
        "plans": {"P1": p1, "P2": p2, "P3": p3},
        "runs": {"r1": r1, "r2": r2, "r3": r3, "r4": r4, "r5": r5, "r6": r6},
    }


def search(client, **params) -> dict:
    response = client.get(f"{API}/runs", params=params)
    assert response.status_code == 200, response.json()
    return response.json()
