"""Deterministic demonstration data (SYNTHETIC - not real Race UP measurements).

Usage (from backend/, after `alembic upgrade head`):

    python -m scripts.seed [--database-url sqlite:///path.sqlite3]

Everything is created through the same services and Pydantic schemas as the
API, so every business rule (cross-row checks, plausibility, immutability)
applies. No randomness is used.

Repeat behaviour: the whole dataset is written in ONE transaction, keyed by the
marker season name below. If that season already exists the seed reports
"already present" and writes nothing; a failure part-way rolls everything back,
so the dataset is either fully present or absent.
"""

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import create_db_engine, create_session_factory
from app.models import Base, Season
from app.schemas.conditions import RunConditionCreate
from app.schemas.files import TelemetryFileCreate
from app.schemas.laps import LapBulkCreate, LapCreate
from app.schemas.objectives import ObjectiveLinkCreate, SeasonObjectiveCreate
from app.schemas.reference import DriverCreate, SeasonCreate, VehicleCreate
from app.schemas.setup import SetupSnapshotCreate, SetupSnapshotDerive
from app.schemas.testing import (
    PlannedRunCancel,
    PlannedRunCreate,
    PlannedRunReplace,
    RunCreate,
    TestCreate,
)
from app.schemas.tracks import TrackLayoutCreate, TrackLocationCreate
from app.schemas.tyres import (
    AlignmentMeasurementBatchCreate,
    RunTireAssignmentBatchCreate,
    TireCompoundCreate,
    TireCreate,
    TireListQuery,
    TireMeasurementBatchCreate,
    TireSetCreate,
)
from app.services import (
    conditions,
    files,
    laps,
    objectives,
    planning,
    reference,
    setup,
    tracks,
    tyres,
)
from app.services import testing as tests_service

MARKER_SEASON = "DEMO 2025/26"
CORNERS = ("FL", "FR", "RL", "RR")


@dataclass
class SeedReport:
    status: str
    created: dict[str, int] = field(default_factory=dict)


def _table_counts(session: Session) -> dict[str, int]:
    return {
        name: session.scalar(select(func.count()).select_from(table))
        for name, table in sorted(Base.metadata.tables.items())
    }


def _lap(n, kind="FLYING", raw=None, penalty=0, valid=True, completed=True, reason=None):
    return LapCreate(
        lap_number=n,
        lap_classification=kind,
        raw_time_ms=raw,
        penalty_duration_ms=penalty,
        timing_valid=valid,
        physically_completed=completed,
        invalidation_reason=reason,
    )


def _measured(ambient, asphalt, weather="CLEAR", track_state="DRY", notes=None):
    return RunConditionCreate(
        ambient_temperature_c=ambient,
        asphalt_temperature_c=asphalt,
        conditions_source="MEASURED",
        weather=weather,
        track_state=track_state,
        notes=notes,
    )


def _checksum(label: str) -> str:
    # Synthetic, deterministic checksum of a label (no real file exists).
    return hashlib.sha256(f"race-up-demo:{label}".encode()).hexdigest()


def _fit(session, run, tires_by_corner, ids):
    tyres.assign_tires(
        session,
        run.id,
        RunTireAssignmentBatchCreate(
            assignments=[{"corner": c, "tire_id": ids[tires_by_corner[c]]} for c in CORNERS]
        ),
    )


def build_demo(session: Session) -> None:
    # --- Reference data ------------------------------------------------------------
    s1 = reference.create_season(
        session,
        SeasonCreate(name=MARKER_SEASON, starts_on=date(2025, 9, 1), ends_on=date(2026, 8, 31)),
    )
    s2 = reference.create_season(
        session,
        SeasonCreate(name="DEMO 2026/27", starts_on=date(2026, 9, 1), ends_on=date(2027, 8, 31)),
    )
    e25 = reference.create_vehicle(
        session, VehicleCreate(code="DEMO-E25", name="Demo EV 2025 (synthetic)")
    )
    e26 = reference.create_vehicle(
        session, VehicleCreate(code="DEMO-E26", name="Demo EV 2026 (synthetic)")
    )
    ada = reference.create_driver(session, DriverCreate(code="DEMO-ADA", full_name="Ada Demo"))
    ben = reference.create_driver(session, DriverCreate(code="DEMO-BEN", full_name="Ben Demo"))
    cleo = reference.create_driver(session, DriverCreate(code="DEMO-CLEO", full_name="Cleo Demo"))

    circuit = tracks.create_track_location(session, TrackLocationCreate(name="Demo Circuit North"))
    airfield = tracks.create_track_location(session, TrackLocationCreate(name="Demo Airfield"))

    def layout(location, name, activity, length):
        return tracks.create_track_layout(
            session,
            TrackLayoutCreate(
                track_location_id=location.id,
                name=name,
                activity_type=activity,
                verified_length_m=length,
                length_verified_on=date(2025, 9, 15),
                length_verification_note="Synthetic demo length",
            ),
        )

    autocross = layout(circuit, "Autocross loop", "AUTOCROSS", "1150.000")
    endurance = layout(circuit, "Endurance loop", "ENDURANCE", "1180.500")
    skidpad = layout(circuit, "Skidpad", "SKIDPAD", "56.549")
    acceleration = layout(airfield, "Acceleration strip", "ACCELERATION", "75.000")

    # --- Objectives -----------------------------------------------------------------
    obj_cooling = objectives.create_objective(
        session,
        s1.id,
        SeasonObjectiveCreate(
            description="Validate inverter cooling over long runs (demo)",
            priority="CRITICAL",
            desired_repetitions=3,
            status="IN_PROGRESS",
        ),
    )
    obj_toe = objectives.create_objective(
        session,
        s1.id,
        SeasonObjectiveCreate(
            description="Compare rear toe settings on autocross (demo)",
            priority="HIGH",
            desired_repetitions=2,
        ),
    )
    objectives.create_objective(
        session,
        s1.id,
        SeasonObjectiveCreate(
            description="Wet-weather driver familiarisation (demo)",
            priority="LOW",
            desired_repetitions=1,
            status="DROPPED",
        ),
    )
    obj_launch = objectives.create_objective(
        session,
        s2.id,
        SeasonObjectiveCreate(
            description="Tune launch control on the new car (demo)",
            priority="HIGH",
            desired_repetitions=4,
        ),
    )

    # --- Setups ---------------------------------------------------------------------
    def corners(camber_front, camber_rear, toe_rear, spring_front="35.00", spring_rear="40.00"):
        return [
            {"corner": "FL", "static_camber_deg": camber_front, "static_toe_deg": "-0.050", "spring_rate_n_per_mm": spring_front},
            {"corner": "FR", "static_camber_deg": camber_front, "static_toe_deg": "-0.050", "spring_rate_n_per_mm": spring_front},
            {"corner": "RL", "static_camber_deg": camber_rear, "static_toe_deg": toe_rear, "spring_rate_n_per_mm": spring_rear},
            {"corner": "RR", "static_camber_deg": camber_rear, "static_toe_deg": toe_rear, "spring_rate_n_per_mm": spring_rear},
        ]  # fmt: skip

    e25_base = setup.create_setup_snapshot(
        session,
        SetupSnapshotCreate(
            vehicle_id=e25.id,
            name="E25 autocross baseline",
            power_limit_kw="80.00",
            rpm_limit_rpm=18000,
            torque_vectoring_mode="TV-STANDARD",
            control_map="MAP-AX",
            corners=corners("-1.50", "-1.20", "0.100"),
        ),
    )
    e25_toe = setup.derive_setup_snapshot(
        session,
        e25_base.id,
        SetupSnapshotDerive(
            change_reason="More rear toe-in for traction (toe objective)",
            name="E25 autocross rear toe +",
            corners=[
                {"corner": "RL", "static_toe_deg": "0.200"},
                {"corner": "RR", "static_toe_deg": "0.200"},
            ],
        ),
    )
    e25_endurance = setup.derive_setup_snapshot(
        session,
        e25_base.id,
        SetupSnapshotDerive(
            change_reason="Lower power limit and endurance map for energy",
            name="E25 endurance",
            power_limit_kw="60.00",
            control_map="MAP-ENDU",
        ),
    )
    e26_base = setup.create_setup_snapshot(
        session,
        SetupSnapshotCreate(
            vehicle_id=e26.id,
            name="E26 launch baseline",
            power_limit_kw="80.00",
            rpm_limit_rpm=20000,
            torque_vectoring_mode="TV-LAUNCH",
            control_map="MAP-ACC",
            corners=corners("-1.30", "-1.00", "0.150", "38.00", "42.00"),
        ),
    )

    # --- Tyres ----------------------------------------------------------------------
    soft = tyres.create_compound(
        session, TireCompoundCreate(manufacturer="DemoTyre", name="SOFT-D")
    )
    medium = tyres.create_compound(
        session, TireCompoundCreate(manufacturer="DemoTyre", name="MEDIUM-D")
    )
    tyres.create_compound(session, TireCompoundCreate(manufacturer="DemoTyre", name="WET-D"))
    for code, compound in (("SOFT-A", soft), ("SOFT-B", soft), ("MED-A", medium)):
        tyres.create_tire_set(
            session,
            TireSetCreate(
                set_code=code,
                compound_id=compound.id,
                introduced_on=date(2025, 9, 20),
                tires=[{"serial_number": f"{code}-{c}"} for c in CORNERS],
            ),
        )
    tyres.create_tire(
        session,
        TireCreate(serial_number="SPARE-MED-1", compound_id=medium.id, notes="Single spare"),
    )
    tire_ids = {
        t.serial_number: t.id for t in tyres.list_tires(session, TireListQuery(limit=100)).items
    }

    # --- Test T1: season 1 autocross day (plan with every outcome) ---------------------
    t1 = tests_service.create_test(
        session,
        TestCreate(
            season_id=s1.id,
            vehicle_id=e25.id,
            track_location_id=circuit.id,
            test_date=date(2025, 10, 12),
            title="Autocross and skidpad (demo)",
            status="COMPLETED",
            problems_encountered="Rain shower around midday cancelled one run.",
            engineering_conclusions="Rear toe-in improved traction exits (synthetic).",
            planned_runs=[
                PlannedRunCreate(
                    sequence_number=1,
                    expected_driver_id=ada.id,
                    expected_track_layout_id=autocross.id,
                    expected_setup_snapshot_id=e25_base.id,
                    expected_lap_count=6,
                    target_lap_time_ms=63_000,
                    expected_energy_limit_kwh="3.500",
                    expected_control_map="MAP-AX",
                ),
                PlannedRunCreate(
                    sequence_number=2,
                    expected_driver_id=ben.id,
                    expected_track_layout_id=autocross.id,
                ),
                PlannedRunCreate(
                    sequence_number=3,
                    expected_driver_id=ada.id,
                    expected_track_layout_id=autocross.id,
                    expected_setup_snapshot_id=e25_base.id,
                ),
                PlannedRunCreate(
                    sequence_number=5,
                    expected_driver_id=cleo.id,
                    expected_track_layout_id=skidpad.id,
                ),
            ],  # fmt: skip
        ),
    )
    plans = {p.sequence_number: p for p in t1.planned_runs}
    objectives.link_test_objectives(
        session, t1.id, ObjectiveLinkCreate(objective_ids=[obj_toe.id, obj_cooling.id])
    )

    planning.cancel_planned_run(
        session, plans[2].id, PlannedRunCancel(cancellation_reason="Rain shower; track wet")
    )
    _, toe_plan = planning.replace_planned_run(
        session,
        plans[3].id,
        PlannedRunReplace(
            replacement_reason="Test the rear toe change instead of a baseline repeat",
            replacement=PlannedRunCreate(
                sequence_number=4,
                expected_driver_id=ada.id,
                expected_track_layout_id=autocross.id,
                expected_setup_snapshot_id=e25_toe.id,
                expected_lap_count=5,
                target_lap_time_ms=62_500,
            ),
        ),
    )

    def run(
        test, number, driver, layout_, setup_snapshot=None, plan=None, deviation=None, start=None
    ):
        return tests_service.create_run(
            session,
            test.id,
            RunCreate(
                run_number=number,
                planned_run_id=plan.id if plan else None,
                driver_id=driver.id,
                track_layout_id=layout_.id,
                setup_snapshot_id=setup_snapshot.id if setup_snapshot else None,
                started_at=start,
                deviation_reason=deviation,
            ),
        )

    r1 = run(
        t1, 1, ada, autocross, e25_base, plans[1], start=datetime(2025, 10, 12, 8, 30, tzinfo=UTC)
    )
    conditions.create_run_condition(session, r1.id, _measured("19.5", "34.5"))
    laps.create_laps(session, r1.id, LapBulkCreate(laps=[
        _lap(1, "OUT_LAP", 78_400),
        _lap(2, raw=64_210),
        _lap(3, raw=62_980, penalty=2_000),  # cone: effective 64 980
        _lap(4, raw=62_450),  # fastest eligible
        _lap(5, raw=61_900, valid=False, reason="Track limits at turn 4"),
        _lap(6, raw=None, valid=False, reason="Transponder miss"),
        _lap(7, "IN_LAP", 85_100),
    ]))  # fmt: skip
    _fit(session, r1, {c: f"SOFT-A-{c}" for c in CORNERS}, tire_ids)
    tyres.record_tire_measurements(session, r1.id, TireMeasurementBatchCreate(measurements=[
        {"corner": c, "phase": "PRE_RUN", "pressure_kpa": "80.0", "temperature_inner_c": "28.0",
         "temperature_center_c": "27.5", "temperature_outer_c": "27.0"} for c in CORNERS
    ] + [
        {"corner": c, "phase": "POST_RUN", "pressure_kpa": p, "temperature_inner_c": ti,
         "temperature_center_c": tc, "temperature_outer_c": to}
        for c, p, ti, tc, to in (
            ("FL", "92.5", "71.0", "66.5", "61.0"), ("FR", "93.0", "73.5", "68.0", "62.5"),
            ("RL", "90.5", "68.0", "65.0", "60.0"), ("RR", "91.0", "69.5", "66.0", "61.5"),
        )
    ]))  # fmt: skip
    tyres.record_alignment_measurements(session, r1.id, AlignmentMeasurementBatchCreate(measurements=[
        {"corner": "FL", "phase": "PRE_RUN", "camber_deg": "-1.50", "toe_deg": "-0.050"},
        {"corner": "FL", "phase": "POST_RUN", "camber_deg": "-1.35", "toe_deg": "-0.040"},
        {"corner": "RL", "phase": "PRE_RUN", "camber_deg": "-1.20", "toe_deg": "0.100"},
        {"corner": "RL", "phase": "POST_RUN", "camber_deg": "-1.10"},
    ]))  # fmt: skip
    planning.complete_planned_run(session, plans[1].id)

    r2 = run(t1, 2, cleo, skidpad, e25_base, deviation="Unplanned skidpad check after rain")
    conditions.create_run_condition(session, r2.id, _measured("17.0", "26.0", "CLOUDY", "DAMP"))
    laps.create_laps(session, r2.id, LapBulkCreate(laps=[
        _lap(n, raw=t) for n, t in ((1, 5_480), (2, 5_390), (3, 5_420), (4, 5_510))
    ]))  # fmt: skip

    r3 = run(t1, 3, ada, autocross, e25_toe, toe_plan, deviation="Aborted: brake warning")
    conditions.create_run_condition(session, r3.id, _measured("21.0", "38.0"))
    laps.create_laps(session, r3.id, LapBulkCreate(laps=[
        _lap(1, "OUT_LAP", 79_000),
        _lap(2, "ABORTED", 70_500, valid=False, reason="Lifted: brake warning"),
        _lap(3, "ABORTED", None, valid=False, completed=False, reason="Stopped on track"),
    ]))  # fmt: skip
    _fit(
        session,
        r3,
        {"FL": "SOFT-B-FL", "FR": "SOFT-B-FR", "RL": "MED-A-RL", "RR": "MED-A-RR"},
        tire_ids,
    )

    r4 = run(t1, 4, ada, autocross, e25_toe, toe_plan, deviation="Retry after brake check")
    conditions.create_run_condition(session, r4.id, _measured("21.5", "39.5"))
    laps.create_laps(session, r4.id, LapBulkCreate(laps=[
        _lap(1, "OUT_LAP", 77_900),
        _lap(2, raw=62_310),
        _lap(3, raw=61_870),
        _lap(4, raw=62_040, penalty=2_000),
        _lap(5, raw=61_990),
        _lap(6, "IN_LAP", 84_000),
    ]))  # fmt: skip
    _fit(session, r4, {c: f"SOFT-B-{c}" for c in CORNERS}, tire_ids)
    planning.complete_planned_run(session, toe_plan.id)
    objectives.link_run_objectives(session, r1.id, ObjectiveLinkCreate(objective_ids=[obj_toe.id]))
    objectives.link_run_objectives(session, r4.id, ObjectiveLinkCreate(objective_ids=[obj_toe.id]))

    # --- Test T2: season 1 endurance (hot day, medium tyres) ----------------------------
    t2 = tests_service.create_test(
        session,
        TestCreate(
            season_id=s1.id,
            vehicle_id=e25.id,
            track_location_id=circuit.id,
            test_date=date(2026, 6, 20),
            title="Endurance simulation (demo)",
            status="COMPLETED",
            planned_runs=[
                PlannedRunCreate(
                    sequence_number=1,
                    expected_driver_id=ben.id,
                    expected_track_layout_id=endurance.id,
                    expected_setup_snapshot_id=e25_endurance.id,
                    expected_lap_count=8,
                )
            ],  # fmt: skip
        ),
    )
    objectives.link_test_objectives(
        session, t2.id, ObjectiveLinkCreate(objective_ids=[obj_cooling.id])
    )
    r5 = run(t2, 1, ben, endurance, e25_endurance, t2.planned_runs[0])
    conditions.create_run_condition(session, r5.id, _measured("31.0", "48.5"))
    laps.create_laps(session, r5.id, LapBulkCreate(laps=[_lap(1, "OUT_LAP", 90_000)] + [
        _lap(n, raw=71_000 + 150 * n) for n in range(2, 9)
    ] + [_lap(9, "IN_LAP", 95_000)]))  # fmt: skip
    _fit(
        session,
        r5,
        {"FL": "MED-A-FL", "FR": "MED-A-FR", "RL": "MED-A-RL", "RR": "SPARE-MED-1"},
        tire_ids,
    )
    objectives.link_run_objectives(
        session, r5.id, ObjectiveLinkCreate(objective_ids=[obj_cooling.id])
    )

    # --- Test T3: season 2 acceleration on the new car (plan never executed) ---------------
    t3 = tests_service.create_test(
        session,
        TestCreate(
            season_id=s2.id,
            vehicle_id=e26.id,
            track_location_id=airfield.id,
            test_date=date(2026, 10, 3),
            title="Launch control tuning (demo)",
            status="COMPLETED",
            planned_runs=[
                PlannedRunCreate(
                    sequence_number=1,
                    expected_driver_id=cleo.id,
                    expected_track_layout_id=acceleration.id,
                    expected_setup_snapshot_id=e26_base.id,
                    expected_lap_count=4,
                ),
                PlannedRunCreate(
                    sequence_number=2,
                    expected_driver_id=ben.id,
                    expected_track_layout_id=acceleration.id,
                    notes="Not run: time ran out",
                ),
            ],  # fmt: skip
        ),
    )
    objectives.link_test_objectives(
        session, t3.id, ObjectiveLinkCreate(objective_ids=[obj_launch.id])
    )
    r6 = run(t3, 1, cleo, acceleration, e26_base, t3.planned_runs[0])
    conditions.create_run_condition(
        session,
        r6.id,
        RunConditionCreate(ambient_temperature_c="14.0", conditions_source="ESTIMATED", weather="OVERCAST", track_state="DRY"),
    )  # fmt: skip
    laps.create_laps(session, r6.id, LapBulkCreate(laps=[
        _lap(1, raw=4_120), _lap(2, raw=3_980), _lap(3, raw=4_050, penalty=1_000),
        _lap(4, raw=3_900, valid=False, reason="False start"),
    ]))  # fmt: skip
    objectives.link_run_objectives(
        session, r6.id, ObjectiveLinkCreate(objective_ids=[obj_launch.id])
    )

    # --- File index (metadata only; demo:// URIs point at no real storage) -----------------
    for test, run_, kind, name, size, meta in (
        (t1, None, "DATA_LOG", "pit_notes_2025-10-12.pdf", 284_113, {"author": "Demo engineer"}),
        (t1, r1, "TELEMETRY", "run01_ada.ld", 18_432_000, {"logger": "demo-logger", "channels": 128, "sample_rate_hz": 200}),
        (t1, r4, "TELEMETRY", "run04_ada.ld", 17_920_512, {"logger": "demo-logger", "channels": 128, "sample_rate_hz": 200}),
        (t2, r5, "VIDEO", "onboard_endurance.mp4", 734_003_200, {"camera": "onboard-front", "fps": 60}),
    ):  # fmt: skip
        files.register_file(
            session,
            test.id,
            TelemetryFileCreate(
                run_id=run_.id if run_ else None,
                file_type=kind,
                original_filename=name,
                storage_uri=f"demo://race-up-demo/{test.test_date.isoformat()}/{name}",
                checksum_sha256=_checksum(f"{test.test_date}:{name}"),
                size_bytes=size,
                metadata={**meta, "synthetic": True},
            ),
        )


def seed(session: Session) -> SeedReport:
    """Writes the dataset into the caller's transaction (the caller commits)."""
    if session.scalar(select(Season.id).where(Season.name == MARKER_SEASON)) is not None:
        return SeedReport(status="already_present")
    before = _table_counts(session)
    build_demo(session)
    after = _table_counts(session)
    created = {name: after[name] - before[name] for name in after if after[name] != before[name]}
    return SeedReport(status="created", created=created)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load deterministic SYNTHETIC demo data.")
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args(argv)

    engine = create_db_engine(args.database_url)
    try:
        with create_session_factory(engine).begin() as session:
            report = seed(session)
    except Exception as exc:  # report and exit non-zero; the transaction rolled back
        print(f"Seed FAILED, nothing was written: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    if report.status == "already_present":
        print(f"Demo data already present (season {MARKER_SEASON!r}); nothing written.")
        return 0
    print("Demo data created (synthetic values):")
    for table, count in report.created.items():
        print(f"  {table:<24} {count:>4}")
    print(f"  {'total rows':<24} {sum(report.created.values()):>4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
