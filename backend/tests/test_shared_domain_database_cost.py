from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientDomainCredential
from service1.models import Client, utcnow
from service1.routers import shared_domain as shared_domain_router
from service1.shared_domain import (
    create_shared_domain_token,
    require_shared_agent_token,
    upsert_shared_status,
)


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


@pytest.mark.parametrize(
    ("status", "deleted"),
    [
        ("pending", False),
        ("approved", True),
    ],
)
def test_shared_agent_token_revalidates_parent_client_lifecycle(status: str, deleted: bool):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, token = _seed_credential(engine, domain="system")

    with Session(engine) as session:
        client = session.get(Client, client_id)
        assert client is not None
        client.status = status
        if deleted:
            client.deleted_at = utcnow()
        session.add(client)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc_info:
            require_shared_agent_token(
                session,
                f"Bearer {token}",
                client_id=client_id,
                domain="system",
            )

    assert exc_info.value.status_code == 401


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


def test_shared_status_upsert_uses_no_select_on_sqlite_insert_or_update():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, _token = _seed_credential(engine, domain="status")

    with Session(engine) as session:
        credential = session.exec(
            select(ClientDomainCredential).where(
                ClientDomainCredential.client_id == client_id,
                ClientDomainCredential.domain == "status",
            )
        ).one()

        counter, listener = _count_selects(engine)
        try:
            first = upsert_shared_status(
                session,
                credential=credential,
                schema_version=1,
                observed_state="online",
                status_payload={"sample": 1},
                agent_version="1.3.24",
                boot_id="boot-a",
            )
            second = upsert_shared_status(
                session,
                credential=credential,
                schema_version=1,
                observed_state="online",
                status_payload={"sample": 2},
                agent_version="1.3.24",
                boot_id="boot-a",
            )
            session.commit()
        finally:
            event.remove(engine, "before_cursor_execute", listener)

    assert first.client_id == client_id
    assert second.client_id == client_id
    assert counter["count"] == 0


def test_status_heartbeat_uses_one_select_for_authorization_only(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, token = _seed_credential(engine, domain="status")
    monkeypatch.setattr(shared_domain_router, "engine", engine)

    counter, listener = _count_selects(engine)
    try:
        payload = shared_domain_router._status(
            "status",
            client_id,
            shared_domain_router.StatusBody(
                schema_version=1,
                observed_state="online",
                status_payload={},
                agent_version="1.3.24",
                boot_id="boot-a",
            ),
            f"Bearer {token}",
        )
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert payload["ok"] is True
    assert payload["client_identity"]["client_id"] == client_id
    # The only SELECT is the joined credential + parent-client authorization.
    assert counter["count"] == 1


@pytest.mark.parametrize(
    ("domain", "expected_selects"),
    [
        ("system", 2),
        ("display", 3),
    ],
)
def test_due_status_can_piggyback_on_command_claim_without_second_authorization(
    monkeypatch, domain: str, expected_selects: int
):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    client_id, token = _seed_credential(engine, domain=domain)
    monkeypatch.setattr(shared_domain_router, "engine", engine)

    counter, listener = _count_selects(engine)
    try:
        payload = shared_domain_router._claim(
            domain,
            client_id,
            shared_domain_router.ClaimBody(
                lease_seconds=60,
                status_report=shared_domain_router.StatusBody(
                    schema_version=1,
                    observed_state="online",
                    status_payload={},
                    agent_version="1.3.24",
                    boot_id="boot-piggyback",
                ),
            ),
            f"Bearer {token}",
        )
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert payload == {"claimed": None, "status_reported": True}
    # One joined credential/client authorization is shared by status + claim.
    # System then needs only the active-command SELECT. Display additionally
    # checks its durable desired configuration before the same command claim.
    assert counter["count"] == expected_selects

    from service1.client_domain_models import ClientDomainStatus

    with Session(engine) as session:
        status = session.exec(
            select(ClientDomainStatus).where(
                ClientDomainStatus.client_id == client_id,
                ClientDomainStatus.domain == domain,
            )
        ).one()
        assert status.observed_state == "online"
        assert status.boot_id == "boot-piggyback"
