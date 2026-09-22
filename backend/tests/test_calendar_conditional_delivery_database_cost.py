from __future__ import annotations

import json
import uuid

from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientDomainCredential
from service1.models import CalendarMarking, Client, utcnow
from service1.routers import shared_domain as shared_domain_router
from service1.season_service import current_and_next_seasons, season_dates
from service1.shared_domain import create_shared_domain_token


def _seed(engine) -> tuple[int, str]:
    with Session(engine) as session:
        client = Client(name="calendar-cost", status="approved")
        session.add(client)
        session.flush()
        client_id = int(client.id)
        credential = ClientDomainCredential(
            id=str(uuid.uuid4()),
            client_id=client_id,
            domain="display",
            secret_hash="not-used-by-token-test",
            token_version=0,
            created_at=utcnow(),
        )
        session.add(credential)
        for season in current_and_next_seasons():
            session.add(
                CalendarMarking(
                    season=season,
                    client_id=client_id,
                    markings={day.isoformat(): {"status": "off"} for day in season_dates(season)},
                )
            )
        session.commit()
        session.refresh(credential)
        token, _ = create_shared_domain_token(credential)
        return client_id, token


def _capture_selects(engine):
    statements: list[str] = []

    def listener(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    return statements, listener


def test_unchanged_calendar_poll_uses_metadata_only_after_authorization(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, token = _seed(engine)
    monkeypatch.setattr(shared_domain_router, "engine", engine)
    auth = f"Bearer {token}"

    first = shared_domain_router.display_calendar(client_id, authorization=auth, if_none_match=None)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag.startswith('"cfcal-')

    statements, listener = _capture_selects(engine)
    try:
        unchanged = shared_domain_router.display_calendar(
            client_id,
            authorization=auth,
            if_none_match=etag,
        )
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert unchanged.status_code == 304
    # 1 joined credential/client authorization + 1 lightweight Calendar metadata query.
    assert len(statements) == 2
    metadata_sql = statements[-1].lower()
    assert "calendarmarking.updated_at" in metadata_sql
    assert "calendarmarking.markings" not in metadata_sql


def test_calendar_edit_invalidates_etag_and_full_snapshot_is_returned(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, token = _seed(engine)
    monkeypatch.setattr(shared_domain_router, "engine", engine)
    auth = f"Bearer {token}"

    first = shared_domain_router.display_calendar(client_id, authorization=auth, if_none_match=None)
    old_etag = first.headers["etag"]

    with Session(engine) as session:
        row = session.exec(
            select(CalendarMarking).where(CalendarMarking.client_id == client_id)
        ).first()
        assert row is not None
        before = row.updated_at
        changed = dict(row.markings)
        first_day = next(iter(changed))
        changed[first_day] = {"status": "on", "onTime": "09:00", "offTime": "10:00"}
        row.markings = changed
        session.add(row)
        session.commit()
        session.refresh(row)
        assert row.updated_at != before

    statements, listener = _capture_selects(engine)
    try:
        refreshed = shared_domain_router.display_calendar(
            client_id,
            authorization=auth,
            if_none_match=old_etag,
        )
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert refreshed.status_code == 200
    assert refreshed.headers["etag"] != old_etag
    payload = json.loads(refreshed.body)
    assert payload["client_id"] == client_id
    # Changed conditional fetch: auth + lightweight metadata + full two-season snapshot.
    assert len(statements) == 3
    assert "calendarmarking.markings" not in statements[1].lower()
    assert "calendarmarking.markings" in statements[2].lower()
