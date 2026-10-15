"""Canonical CSV importer: dry run, commit, validation, duplicates and atomicity."""

import csv
import shutil
from pathlib import Path

import pytest
from sqlalchemy import event, func, select

from app.models import Base, Lap, Run, Test
from app.services.csv_import import import_csv
from scripts import import_csv as cli
from scripts import seed as seed_module
from tests.api_helpers import API

SAMPLE = Path(__file__).resolve().parent.parent / "sample-data" / "historical_runs.csv"


@pytest.fixture
def seeded(app):
    with app.state.session_factory.begin() as session:
        seed_module.seed(session)
    return app


def row(**overrides) -> dict:
    values = {
        "season_name": "DEMO 2025/26",
        "vehicle_code": "DEMO-E25",
        "driver_code": "DEMO-BEN",
        "test_date": "2025-12-06",
        "test_status": "COMPLETED",
        "track_location": "Demo Circuit North",
        "track_layout": "Autocross loop",
        "run_number": "1",
        "lap_number": "1",
        "lap_classification": "FLYING",
        "raw_time_ms": "64000",
        "timing_valid": "true",
        "physically_completed": "true",
    }
    values.update(overrides)
    return values


def write_csv(tmp_path, rows: list[dict], name="input.csv") -> Path:
    path = tmp_path / name
    columns = list(dict.fromkeys(column for r in rows for column in r))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def table_counts(app) -> dict:
    with app.state.session_factory() as session:
        return {
            name: session.scalar(select(func.count()).select_from(table))
            for name, table in Base.metadata.tables.items()
        }


def run_import(app, path, commit=False):
    return import_csv(app.state.session_factory, path, commit=commit).to_dict()


def codes(summary) -> list[tuple]:
    return [(e["row"], e["field"], e["code"]) for e in summary["errors"]]


# --- Dry run and commit ------------------------------------------------------------------


def test_dry_run_reports_and_persists_nothing(seeded):
    before = table_counts(seeded)
    summary = run_import(seeded, SAMPLE)
    assert (summary["dry_run"], summary["committed"]) == (True, False)
    assert (summary["total_rows"], summary["valid_rows"], summary["invalid_rows"]) == (10, 10, 0)
    assert summary["created"] == {
        "laps": 9,
        "run_conditions": 2,
        "runs": 2,
        "tests": 1,
        "tire_assignments": 4,
    }
    assert summary["skipped"] == {"duplicate_rows_in_file": 1}
    assert table_counts(seeded) == before


def test_commit_persists_and_data_works_through_the_api(seeded, client):
    before = table_counts(seeded)
    summary = run_import(seeded, SAMPLE, commit=True)
    assert summary["committed"] is True and summary["errors"] == []
    after = table_counts(seeded)
    assert after["lap"] - before["lap"] == 9 and after["run"] - before["run"] == 2

    ben = next(d for d in client.get(f"{API}/drivers").json()["items"] if d["code"] == "DEMO-BEN")
    soft = next(
        c for c in client.get(f"{API}/tire-compounds").json()["items"] if c["name"] == "SOFT-D"
    )
    page = client.get(
        f"{API}/runs",
        params={
            "driver_id": ben["id"],
            "tire_compound_id": soft["id"],
            "date_from": "2025-11-08",
            "date_to": "2025-11-08",
        },
    ).json()
    (imported,) = page["items"]
    assert imported["conditions"]["asphalt_temperature_c"] == "29.5"
    # Lap 3: 63 120 + 2 000 = 65 120; lap 4 (62 790) is timing-invalid; lap 2 (63 850) wins.
    assert imported["fastest_lap"]["effective_time_ms"] == 63_850
    # Six physically completed autocross laps (the untimed lap 5 counts once).
    assert imported["distance_m"] == "6900.000"
    skidpad = client.get(f"{API}/runs/{imported['id'] + 1}/mileage").json()
    assert skidpad["distance_m"] == "113.098"  # aborted, incomplete lap 3 does not count


def test_reimport_reuses_and_skips_without_creating(seeded):
    run_import(seeded, SAMPLE, commit=True)
    before = table_counts(seeded)
    summary = run_import(seeded, SAMPLE, commit=True)
    assert summary["created"] == {}
    assert summary["skipped"] == {"duplicate_rows_in_file": 1, "existing_laps": 9}
    assert summary["reused"] == {"run_conditions": 2, "runs": 2, "tests": 1, "tire_assignments": 4}
    assert table_counts(seeded) == before


def test_normalisation_of_whitespace_case_booleans_and_blanks(seeded, tmp_path, client):
    path = write_csv(
        tmp_path,
        [
            row(
                lap_number=" 1 ",
                lap_classification=" out-lap ",
                timing_valid="YES",
                physically_completed="y",
                raw_time_ms=" 80000 ",
            ),
            row(
                lap_number="2",
                lap_classification="Flying",
                timing_valid="1",
                physically_completed="True",
                penalty_duration_ms="",
            ),
            row(
                lap_number="3",
                lap_classification="in lap",
                timing_valid="no",
                physically_completed="0",
                invalidation_reason="  Pit entry  ",
                raw_time_ms="",
            ),
        ],
    )
    summary = run_import(seeded, path, commit=True)
    assert summary["errors"] == [] and summary["created"]["laps"] == 3
    with seeded.state.session_factory() as session:
        laps = session.scalars(
            select(Lap)
            .join(Run)
            .join(Test)
            .where(Test.test_date == "2025-12-06")
            .order_by(Lap.lap_number)
        ).all()
        assert [
            (lap.lap_classification, lap.timing_valid, lap.physically_completed) for lap in laps
        ] == [
            ("OUT_LAP", True, True),
            ("FLYING", True, True),
            ("IN_LAP", False, False),
        ]
        assert (laps[1].penalty_duration_ms, laps[2].invalidation_reason, laps[2].raw_time_ms) == (
            0,
            "Pit entry",
            None,
        )


# --- Validation (nothing is written when anything is wrong) -----------------------------


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"test_date": "06/12/2025"}, ("test_date", "invalid_date")),
        ({"test_date": "2025-13-01"}, ("test_date", "invalid_date")),
        ({"lap_classification": "WARMUP"}, ("lap_classification", "invalid_value")),
        ({"test_status": "DONE"}, ("status", "invalid_value")),
        ({"timing_valid": "maybe"}, ("timing_valid", "invalid_boolean")),
        ({"raw_time_ms": "64,000"}, ("raw_time_ms", "invalid_integer")),
        ({"raw_time_ms": "64000.5"}, ("raw_time_ms", "invalid_integer")),
        (
            {"ambient_temperature_c": "21,5", "conditions_source": "MEASURED"},
            ("ambient_temperature_c", "invalid_decimal"),
        ),
        (
            {"ambient_temperature_c": "75.0", "conditions_source": "MEASURED"},
            ("ambient_temperature_c", "invalid_condition_value"),
        ),
        ({"raw_time_ms": "9000"}, ("raw_time_ms", "impossible_lap_time")),
        ({"raw_time_ms": ""}, ("raw_time_ms", "invalid_lap_state")),  # untimed but valid
        ({"timing_valid": "false"}, ("invalidation_reason", "invalid_lap_state")),
        ({"driver_code": "NOBODY"}, ("driver_code", "unknown_entity")),
        ({"track_layout": "Skidpad X"}, ("track_layout", "unknown_entity")),
        ({"tire_fl": "NO-SUCH-TYRE"}, ("tire_fl", "unknown_entity")),
        ({"run_number": ""}, ("run_number", "missing_value")),
        ({"season_name": "  "}, ("season_name", "missing_value")),
    ],
)
def test_invalid_values_are_reported_with_row_and_field(seeded, tmp_path, override, expected):
    # The second row is its own test, so run/test-level values are validated, not compared.
    second = row(lap_number="2", **{"test_date": "2025-12-07", **override})
    path = write_csv(tmp_path, [row(lap_number="1"), second])
    before = table_counts(seeded)
    summary = run_import(seeded, path, commit=True)
    assert summary["committed"] is False
    assert (3, *expected) in codes(summary), summary["errors"]
    assert (summary["valid_rows"], summary["invalid_rows"]) == (1, 1)
    assert summary["created"] == {}
    assert table_counts(seeded) == before


def test_missing_and_unknown_columns_reject_the_file(seeded, tmp_path):
    missing = {k: v for k, v in row().items() if k != "physically_completed"}
    summary = run_import(seeded, write_csv(tmp_path, [missing], "missing.csv"), commit=True)
    assert codes(summary) == [(None, "physically_completed", "missing_column")]
    unknown = run_import(seeded, write_csv(tmp_path, [row(sector_1_ms="20000")], "unknown.csv"))
    assert codes(unknown) == [(None, "sector_1_ms", "unknown_column")]


def test_ambiguous_setup_name_is_rejected(seeded, tmp_path, client):
    vehicle = next(
        v for v in client.get(f"{API}/vehicles").json()["items"] if v["code"] == "DEMO-E25"
    )
    for _ in range(2):
        client.post(
            f"{API}/setup-snapshots",
            json={"vehicle_id": vehicle["id"], "name": "Twin", "power_limit_kw": "70"},
        )
    summary = run_import(seeded, write_csv(tmp_path, [row(setup_name="Twin")]))
    assert (2, "setup_name", "ambiguous_entity") in codes(summary)


def test_run_level_values_must_agree_across_rows(seeded, tmp_path):
    path = write_csv(tmp_path, [row(lap_number="1"), row(lap_number="2", driver_code="DEMO-ADA")])
    assert (3, "driver_code", "inconsistent_value") in codes(run_import(seeded, path))


def test_conflicting_duplicate_rows_in_file(seeded, tmp_path):
    path = write_csv(tmp_path, [row(lap_number="1"), row(lap_number="1", raw_time_ms="65000")])
    assert (3, "lap_number", "conflicting_duplicate") in codes(run_import(seeded, path))


def test_conflicting_duplicate_against_database(seeded, tmp_path):
    run_import(seeded, SAMPLE, commit=True)
    changed = row(
        test_date="2025-11-08",
        driver_code="DEMO-BEN",
        lap_number="2",
        raw_time_ms="63000",
        setup_name="E25 autocross baseline",
    )
    summary = run_import(seeded, write_csv(tmp_path, [changed]), commit=True)
    assert (2, "lap_number", "conflicting_duplicate") in codes(summary)
    other_driver = row(
        test_date="2025-11-08",
        driver_code="DEMO-ADA",
        lap_number="9",
        setup_name="E25 autocross baseline",
    )
    assert (2, "driver_code", "conflicting_duplicate") in codes(
        run_import(seeded, write_csv(tmp_path, [other_driver], "d.csv"))
    )


def test_every_error_is_reported_not_only_the_first(seeded, tmp_path):
    path = write_csv(
        tmp_path,
        [
            row(lap_number="1", raw_time_ms="abc"),
            row(lap_number="2", timing_valid="x"),
            row(lap_number="3", driver_code="NOBODY"),
        ],
    )
    summary = run_import(seeded, path)
    assert {e["row"] for e in summary["errors"]} == {2, 3, 4}


def test_setup_lookup_is_scoped_to_the_run_vehicle(seeded, tmp_path):
    """A setup name of another vehicle does not resolve (no cross-vehicle setups)."""
    summary = run_import(seeded, write_csv(tmp_path, [row(setup_name="E26 launch baseline")]))
    assert (2, "setup_name", "unknown_entity") in codes(summary)  # looked up per vehicle


# --- Atomicity ----------------------------------------------------------------------------


def test_one_invalid_row_rolls_back_the_whole_file(seeded, tmp_path):
    rows = [row(run_number="1", lap_number=str(n)) for n in range(1, 4)]
    rows.append(row(run_number="2", lap_number="1", raw_time_ms="1000"))
    before = table_counts(seeded)
    summary = run_import(seeded, write_csv(tmp_path, rows), commit=True)
    assert summary["committed"] is False and codes(summary) == [
        (5, "raw_time_ms", "impossible_lap_time")
    ]
    assert table_counts(seeded) == before


def test_domain_failure_in_the_write_pass_rolls_back_earlier_runs(seeded, tmp_path, monkeypatch):
    from app.exceptions import ConflictError
    from app.services import csv_import

    calls = {"n": 0}
    original = csv_import.lap_service.create_laps

    def fail_on_second(session, run_id, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConflictError(code="lap_number_taken", message="simulated race condition")
        return original(session, run_id, data)

    monkeypatch.setattr(csv_import.lap_service, "create_laps", fail_on_second)
    rows = [row(run_number="1", lap_number="1"), row(run_number="2", lap_number="1")]
    before = table_counts(seeded)
    summary = run_import(seeded, write_csv(tmp_path, rows), commit=True)
    assert codes(summary) == [(3, None, "lap_number_taken")]
    assert summary["committed"] is False
    assert table_counts(seeded) == before  # run 1 was created, then rolled back


def test_commit_failure_writes_nothing(seeded):
    before = table_counts(seeded)

    def fail(session):
        raise RuntimeError("simulated commit failure")

    event.listen(seeded.state.session_factory, "before_commit", fail)
    try:
        with pytest.raises(RuntimeError):
            import_csv(seeded.state.session_factory, SAMPLE, commit=True)
    finally:
        event.remove(seeded.state.session_factory, "before_commit", fail)
    assert table_counts(seeded) == before


# --- Command line --------------------------------------------------------------------------


def test_cli_dry_run_commit_and_exit_codes(seeded, db_url, tmp_path, capsys):
    assert cli.main([str(SAMPLE), "--database-url", db_url]) == 0
    assert '"dry_run": true' in capsys.readouterr().out
    assert cli.main([str(SAMPLE), "--database-url", db_url, "--commit"]) == 0
    assert '"committed": true' in capsys.readouterr().out
    bad = shutil.copy(SAMPLE, tmp_path / "bad.csv")
    Path(bad).write_text(Path(bad).read_text().replace("79200", "1000"))
    assert cli.main([str(bad), "--database-url", db_url, "--commit"]) == 1
    assert "impossible_lap_time" in capsys.readouterr().out
    assert cli.main([str(tmp_path / "missing.csv"), "--database-url", db_url]) == 2
