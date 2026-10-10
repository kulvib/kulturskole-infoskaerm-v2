"""Offline fleet-scale budgets for clients without any open admin frontend.

These tests exercise real signed presence and status control-plane paths against
local state/SQLite only.  They are not throughput claims for Render or Neon.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientDomainCredential, ClientDomainStatus
from service1.ephemeral_presence import last_seen
from service1.models import Client, utcnow
from service1.routers import shared_domain as router
from service1.shared_domain import create_shared_domain_token


DOMAINS = ("status", "display", "system")


def _signed_token(client_id: int, domain: str) -> str:
    credential = ClientDomainCredential(
        id=str(uuid.uuid4()),
        client_id=client_id,
        domain=domain,
        secret_hash="fleet-test-only",
        created_at=utcnow(),
    )
    token, _expires_at = create_shared_domain_token(credential)
    return f"Bearer {token}"


@pytest.mark.parametrize("fleet_size", [10, 100, 1000])
def test_always_online_fleet_presence_is_database_free_without_administrator(
    monkeypatch, fleet_size: int
) -> None:
    """Two successive presence pulses per domain need no SQL session.

    Presence is deliberately not cached from an unauthenticated client id: the
    real JWT validation must still reject a token for another client/domain.
    """
    def unexpected_session(*_args, **_kwargs):
        pytest.fail("A routine signed presence heartbeat opened a database session")

    monkeypatch.setattr(router, "Session", unexpected_session)
    credentials = {
        (client_id, domain): _signed_token(client_id, domain)
        for client_id in range(1, fleet_size + 1)
        for domain in DOMAINS
    }
    for _tick in range(2):
        for (client_id, domain), token in credentials.items():
            receipt = router._agent_presence(domain, client_id, token)
            assert receipt["ok"] is True
            assert receipt["client_id"] == client_id
            assert receipt["domain"] == domain

    for domain in DOMAINS:
        assert last_seen(domain, fleet_size) is not None

    # An agent's valid credential cannot impersonate a different domain or id.
    with pytest.raises(HTTPException) as mismatch:
        router._agent_presence("display", fleet_size, credentials[(fleet_size, "status")])
    assert mismatch.value.status_code == 401


@pytest.mark.parametrize("fleet_size", [10, 100, 1000])
def test_fleet_durable_status_checkpoints_use_one_authorization_read_and_one_upsert(
    monkeypatch, fleet_size: int
) -> None:
    """Status checkpoints scale linearly, not N queries per other client.

    The first round inserts and the second updates the same status rows.  No
    UI subscriptions or administrator requests are running in this scenario.
    """
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(router, "engine", engine)
    tokens: list[tuple[int, str]] = []
    with Session(engine) as session:
        for idx in range(fleet_size):
            client = Client(name=f"fleet-status-{idx}", status="approved")
            session.add(client)
            session.flush()
            client_id = int(client.id)
            credential = ClientDomainCredential(
                id=str(uuid.uuid4()),
                client_id=client_id,
                domain="status",
                secret_hash="fleet-test-only",
                created_at=utcnow(),
            )
            session.add(credential)
            token, _expires = create_shared_domain_token(credential)
            tokens.append((client_id, f"Bearer {token}"))
        session.commit()

    counts = {"select": 0, "status_upsert": 0}

    def count_statements(_conn, _cursor, statement, _params, _context, _executemany):
        normalized = statement.lstrip().upper()
        if normalized.startswith("SELECT"):
            counts["select"] += 1
        if normalized.startswith("INSERT INTO CLIENT_DOMAIN_STATUS"):
            counts["status_upsert"] += 1

    event.listen(engine, "before_cursor_execute", count_statements)
    try:
        for cycle in range(2):
            for client_id, token in tokens:
                result = router._status(
                    "status",
                    client_id,
                    router.StatusBody(
                        schema_version=1,
                        observed_state="online",
                        status_payload={"cycle": cycle},
                        agent_version="fleet-test",
                        boot_id="boot-stable",
                    ),
                    token,
                )
                assert result["ok"] is True
                assert result["client_identity"]["client_id"] == client_id
    finally:
        event.remove(engine, "before_cursor_execute", count_statements)

    # These bounds cover both INSERT and ON CONFLICT UPDATE, with no N+1.
    assert counts == {"select": 2 * fleet_size, "status_upsert": 2 * fleet_size}
    with Session(engine) as session:
        statuses = session.exec(select(ClientDomainStatus)).all()
        assert len(statuses) == fleet_size
        assert all(row.status_payload == {"cycle": 1} for row in statuses)
