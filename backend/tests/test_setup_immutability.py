"""The ORM guard keeps setup history append-only for every session, not only the API."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.exceptions import ConflictError
from app.models import Corner, Run, SetupCornerParams, SetupSnapshot


@pytest.fixture
def snapshot(session, base_graph):
    snapshot = SetupSnapshot(
        vehicle=base_graph["vehicle"],
        power_limit_kw=Decimal("80"),
        corners=[SetupCornerParams(corner=Corner.FL, static_camber_deg=Decimal("-1.5"))],
    )
    session.add(snapshot)
    session.commit()
    return snapshot


def assert_immutable(session) -> None:
    with pytest.raises(ConflictError) as raised:
        session.flush()
    assert raised.value.code == "setup_snapshot_immutable"
    session.rollback()


def test_updating_a_persisted_snapshot_is_rejected(session, snapshot):
    snapshot.power_limit_kw = Decimal("60")
    assert_immutable(session)
    assert session.get(SetupSnapshot, snapshot.id).power_limit_kw == Decimal("80")


def test_updating_a_persisted_corner_is_rejected(session, snapshot):
    snapshot.corners[0].static_camber_deg = Decimal("-2.0")
    assert_immutable(session)


def test_deleting_a_snapshot_or_corner_is_rejected(session, snapshot):
    session.delete(snapshot.corners[0])
    assert_immutable(session)
    session.delete(session.get(SetupSnapshot, snapshot.id))
    assert_immutable(session)


@pytest.mark.parametrize("via_relationship", [True, False])
def test_adding_a_corner_to_a_persisted_snapshot_is_rejected(session, snapshot, via_relationship):
    if via_relationship:
        snapshot.corners.append(SetupCornerParams(corner=Corner.RR, static_toe_deg=Decimal("0")))
    else:
        session.add(
            SetupCornerParams(setup_snapshot_id=snapshot.id, corner=Corner.RR, static_toe_deg=0)
        )
    assert_immutable(session)


def test_referencing_a_snapshot_from_a_run_is_not_a_mutation(session, base_graph, snapshot):
    session.add(
        Run(
            test=base_graph["test"],
            run_number=1,
            driver=base_graph["driver"],
            track_layout=base_graph["layout"],
            setup_snapshot=snapshot,
        )
    )
    session.commit()


def test_raw_sql_is_not_guarded_by_design(engine, snapshot):
    # Documented limitation: no database triggers; the guard covers ORM sessions only.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE setup_snapshot SET name = 'renamed' WHERE id = :id"), {"id": snapshot.id}
        )
        name = conn.execute(text("SELECT name FROM setup_snapshot")).scalar_one()
    assert name == "renamed"
