from __future__ import annotations

from datetime import timedelta
import os

from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

from service1 import livestream_v2
from service1.client_activity_models import ClientActivityLease
from service1.livestream_v2_models import LivestreamV2Generation, LivestreamV2Viewer
from service1.models import Client


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _capture_selects(engine):
    statements: list[str] = []

    def listener(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    return statements, listener


def _seed_running_viewer(engine, *, stale: bool = False) -> int:
    with Session(engine) as session:
        client = Client(name="sweeper-cost", status="approved")
        session.add(client)
        session.flush()
        client_id = int(client.id)
        session.add(
            LivestreamV2Generation(
                id="11111111-1111-1111-1111-111111111111",
                client_id=client_id,
                state="running",
                requested_action="start",
            )
        )
        last_seen_at = livestream_v2._now()
        if stale:
            last_seen_at -= timedelta(
                seconds=(
                    livestream_v2.VIEWER_LEASE_SECONDS
                    + livestream_v2.VIEWER_STOP_GRACE_SECONDS
                    + 5
                )
            )
        session.add(
            LivestreamV2Viewer(
                client_id=client_id,
                viewer_id="viewer-a",
                principal_key="admin:1",
                source="test",
                last_seen_at=last_seen_at,
            )
        )
        session.commit()
        return client_id


def test_steady_hold_uses_three_sweep_wide_selects_without_client_lock():
    engine = _engine()
    _seed_running_viewer(engine)

    statements, listener = _capture_selects(engine)
    try:
        with Session(engine) as session:
            assert livestream_v2.reconcile_all_viewer_lifecycles(session) == []
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert len(statements) == 3
    sql = "\n".join(statements).lower()
    assert "livestream_v2_generation" in sql
    assert "livestream_v2_viewer" in sql
    assert "client_activity_lease" in sql
    assert " from client " not in f" {sql} "
    assert "for update" not in sql


def test_steady_activity_hold_uses_same_sweep_wide_fast_path():
    engine = _engine()
    with Session(engine) as session:
        client = Client(name="sweeper-activity-cost", status="approved")
        session.add(client)
        session.flush()
        client_id = int(client.id)
        session.add(
            LivestreamV2Generation(
                id="22222222-2222-2222-2222-222222222222",
                client_id=client_id,
                state="running",
                requested_action="start",
            )
        )
        session.add(
            ClientActivityLease(
                id="33333333-3333-3333-3333-333333333333",
                client_id=client_id,
                domain="terminal",
                session_id="terminal-session",
            )
        )
        session.commit()

    statements, listener = _capture_selects(engine)
    try:
        with Session(engine) as session:
            assert livestream_v2.reconcile_all_viewer_lifecycles(session) == []
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert len(statements) == 3
    sql = "\n".join(statements).lower()
    assert " from client " not in f" {sql} "
    assert "for update" not in sql


def test_stale_viewer_still_enters_locked_transition_path_and_stops():
    engine = _engine()
    client_id = _seed_running_viewer(engine, stale=True)

    with Session(engine) as session:
        assert livestream_v2.reconcile_all_viewer_lifecycles(session) == [(client_id, "stop")]
        session.commit()

    with Session(engine) as session:
        viewer = session.get(LivestreamV2Viewer, 1)
        generation = session.get(
            LivestreamV2Generation,
            "11111111-1111-1111-1111-111111111111",
        )
        assert viewer is not None
        assert viewer.ended_at is not None
        assert viewer.end_reason == "lease_expired"
        assert generation is not None
        assert generation.state == "stopping"
