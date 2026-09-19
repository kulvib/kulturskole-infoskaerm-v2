from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine

from service1.client_domain_models import ClientDomainCredential
from service1.models import Client, utcnow
from service1.routers import shared_domain as shared_domain_router
from service1.shared_domain import create_shared_domain_token, require_shared_agent_token


def _seed_credential(engine, *, domain: str) -> tuple[int, str]:
    with Session(engine) as session:
        client = Client(name=f"db-cost-{domain}", status="approved")
        session.add(client)
        session.flush()
        client_id = int(client.id)
        credential = ClientDomainCredential(
            id=str(uuid.uuid4()),
            client_id=client_id,
            domain=domain,
            secret_hash="not-used-by-token-test",
            token_version=0,
            created_at=utcnow(),
        )
        session.add(credential)
        session.commit()
        session.refresh(credential)
        token, _expires_at = create_shared_domain_token(credential)
        return client_id, token


def _count_selects(engine):
    counter = {"count": 0}

    def listener(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter["count"] += 1

    event.listen(engine, "before_cursor_execute", listener)
    return counter, listener


def test_shared_agent_token_validation_uses_one_joined_select():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, token = _seed_credential(engine, domain="system")

    counter, listener = _count_selects(engine)
    try:
        with Session(engine) as session:
            credential = require_shared_agent_token(
                session,
                f"Bearer {token}",
                client_id=client_id,
                domain="system",
            )
            assert credential.client_id == client_id
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert counter["count"] == 1


@pytest.mark.parametrize("domain", ["display", "system"])
def test_empty_shared_command_claim_uses_two_selects_including_auth(monkeypatch, domain: str):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, token = _seed_credential(engine, domain=domain)
    monkeypatch.setattr(shared_domain_router, "engine", engine)

    counter, listener = _count_selects(engine)
    try:
        payload = shared_domain_router._claim(
            domain,
            client_id,
            shared_domain_router.ClaimBody(lease_seconds=60),
            f"Bearer {token}",
        )
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert payload == {"claimed": None}
    # 1 joined credential/client authorization SELECT + 1 locked active-queue SELECT.
    # Display must not read ClientDomainStatus when there is no command to claim.
    assert counter["count"] == 2
