from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from types import SimpleNamespace
from typing import Any
import uuid

import pytest

sqlmodel = pytest.importorskip("sqlmodel")
pytest.importorskip("passlib")

from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from service1.auth import get_password_hash
from service1.client_domain_models import (
    ClientCommand,
    ClientDomainCredential,
    ClientDomainStatus,
    DisplayDesiredConfiguration,
)
from service1.models import Client
from service1.remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from service1.shared_domain import utcnow
from service1.terminal_v2_models import TerminalClient, TerminalCredential
from service1.routers import client_auth_compat
from service1.routers import clients
from service1.routers import shared_domain as shared_domain_router


class _ASGIResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self._body.decode("utf-8"))


class _ASGITestClient:
    """Minimal in-process ASGI client using only the runtime's existing stack."""

    def __init__(self, app: FastAPI):
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> _ASGIResponse:
        body = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        header_items = [(b"host", b"testserver")]
        if json_body is not None:
            header_items.extend(
                [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ]
            )
        if headers:
            header_items.extend(
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            )

        async def invoke() -> _ASGIResponse:
            messages: list[dict[str, Any]] = []
            request_sent = False

            async def receive() -> dict[str, Any]:
                nonlocal request_sent
                if not request_sent:
                    request_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any]) -> None:
                messages.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": method.upper(),
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "root_path": "",
                "headers": header_items,
                "client": ("127.0.0.1", 50000),
                "server": ("testserver", 80),
            }
            await self.app(scope, receive, send)
            starts = [message for message in messages if message["type"] == "http.response.start"]
            assert len(starts) == 1, messages
            response_body = b"".join(
                message.get("body", b"")
                for message in messages
                if message["type"] == "http.response.body"
            )
            return _ASGIResponse(int(starts[0]["status"]), response_body)

        return asyncio.run(invoke())

    def get(self, path: str, *, headers: dict[str, str] | None = None) -> _ASGIResponse:
        return self.request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> _ASGIResponse:
        return self.request("POST", path, headers=headers, json_body=json)

    def put(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> _ASGIResponse:
        return self.request("PUT", path, headers=headers, json_body=json)


CLIENT_ID = 4242
SECRET_BY_DOMAIN = {
    "status": "cf_status_" + "s" * 48,
    "display": "cf_display_" + "d" * 48,
    "system": "cf_system_" + "y" * 48,
}


def _credential_id(domain: str) -> str:
    values = {
        "status": "11111111-1111-4111-8111-111111111111",
        "display": "22222222-2222-4222-8222-222222222222",
        "system": "33333333-3333-4333-8333-333333333333",
    }
    return values[domain]


@pytest.fixture
def operational_http(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            Client.__table__,
            ClientDomainCredential.__table__,
            ClientDomainStatus.__table__,
            DisplayDesiredConfiguration.__table__,
            ClientCommand.__table__,
            TerminalClient.__table__,
            TerminalCredential.__table__,
            RemoteDesktopClient.__table__,
            RemoteDesktopCredential.__table__,
        ],
    )

    monkeypatch.setattr(client_auth_compat, "engine", engine)
    monkeypatch.setattr(shared_domain_router, "engine", engine)
    monkeypatch.setattr(clients, "current_and_next_seasons", lambda: [])
    monkeypatch.setattr(clients, "add_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clients, "_prepare_full_client_read", lambda _session, client: client)

    def session_override():
        with Session(engine) as session:
            yield session

    superadmin = SimpleNamespace(
        id=1,
        username="integration-superadmin",
        role="superadmin",
        organization_id=None,
        is_superadmin=True,
        is_admin=True,
    )

    app = FastAPI()
    app.include_router(clients.router, prefix="/api")
    app.include_router(client_auth_compat.router, prefix="/api")
    app.include_router(shared_domain_router.router, prefix="/api")
    app.dependency_overrides[clients.get_session] = session_override
    app.dependency_overrides[clients.get_current_superadmin_user] = lambda: superadmin
    app.dependency_overrides[clients.get_current_user_or_client] = lambda: superadmin

    with Session(engine) as session:
        now = utcnow()
        session.add(Client(id=CLIENT_ID, name="Synthetic ClientFlow", status="pending"))
        for domain, secret in SECRET_BY_DOMAIN.items():
            session.add(
                ClientDomainCredential(
                    id=_credential_id(domain),
                    client_id=CLIENT_ID,
                    domain=domain,
                    secret_hash=get_password_hash(secret),
                    token_version=0,
                    created_at=now,
                )
            )
        terminal_credential_id = "44444444-4444-4444-8444-444444444444"
        remote_credential_id = "55555555-5555-4555-8555-555555555555"
        session.add(TerminalClient(id=CLIENT_ID, display_name="Synthetic ClientFlow", status="disabled", created_at=now))
        session.add(
            TerminalCredential(
                id=terminal_credential_id,
                client_id=CLIENT_ID,
                secret_hash=get_password_hash("terminal-secret-for-integration"),
                token_version=0,
                created_at=now,
            )
        )
        session.add(
            RemoteDesktopClient(
                id=CLIENT_ID,
                display_name="Synthetic ClientFlow",
                status="disabled",
                created_at=now,
            )
        )
        session.add(
            RemoteDesktopCredential(
                id=remote_credential_id,
                client_id=CLIENT_ID,
                secret_hash=get_password_hash("remote-desktop-secret-for-integration"),
                token_version=0,
                created_at=now,
            )
        )
        session.commit()

    yield _ASGITestClient(app), engine


def _token(http: _ASGITestClient, domain: str):
    return http.post(
        "/api/client-auth/token",
        json={
            "client_id": CLIENT_ID,
            "credential_id": _credential_id(domain),
            "domain": domain,
            "client_secret": SECRET_BY_DOMAIN[domain],
        },
    )


def _put_status(http: _ASGITestClient, domain: str, token: str, *, boot_id: str):
    return http.put(
        f"/api/{domain}-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {"integration": True},
            "agent_version": "1.3.9",
            "boot_id": boot_id,
        },
    )


def test_pending_approval_runtime_protocol_presence_reconnect_and_command_roundtrip(operational_http):
    http, engine = operational_http

    # Claim-created credentials exist, but backend lifecycle is still pending.
    pending = _token(http, "status")
    assert pending.status_code == 401

    approved = http.post(f"/api/clients/{CLIENT_ID}/approve")
    assert approved.status_code == 200, approved.text

    tokens = {}
    for domain in ("status", "display", "system"):
        response = _token(http, domain)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["client_id"] == CLIENT_ID
        assert payload["credential_id"] == _credential_id(domain)
        assert payload["domain"] == domain
        tokens[domain] = payload["access_token"]

    for domain in ("status", "display", "system"):
        response = _put_status(http, domain, tokens[domain], boot_id="boot-a")
        assert response.status_code == 200, response.text
        assert response.json()["observed_state"] == "online"

    presence = http.get(f"/api/clients/{CLIENT_ID}/presence")
    assert presence.status_code == 200, presence.text
    presence_payload = presence.json()
    assert presence_payload["is_online"] is True
    assert presence_payload["status"]["boot_id"] == "boot-a"
    assert presence_payload["display"]["boot_id"] == "boot-a"
    assert presence_payload["system"]["boot_id"] == "boot-a"

    now = utcnow()
    with Session(engine) as session:
        for domain in ("display", "system"):
            session.add(
                ClientCommand(
                    id=str(uuid.uuid4()),
                    client_id=CLIENT_ID,
                    domain=domain,
                    command_type="integration_probe",
                    schema_version=1,
                    payload={"domain": domain},
                    idempotency_key=f"integration-{domain}",
                    requested_at=now,
                    available_at=now,
                    expires_at=now + timedelta(minutes=5),
                    status="queued",
                    attempt_count=0,
                    max_attempts=3,
                )
            )
        session.commit()
        command_ids = {
            row.domain: row.id
            for row in session.exec(
                select(ClientCommand).where(ClientCommand.client_id == CLIENT_ID)
            ).all()
        }

    for domain in ("display", "system"):
        claim = http.post(
            f"/api/{domain}-agent/clients/{CLIENT_ID}/commands/claim",
            headers={"Authorization": f"Bearer {tokens[domain]}"},
            json={"lease_seconds": 60},
        )
        assert claim.status_code == 200, claim.text
        claimed = claim.json()["claimed"]
        assert claimed is not None
        assert claimed["command"]["id"] == command_ids[domain]
        complete = http.post(
            f"/api/{domain}-agent/clients/{CLIENT_ID}/commands/{command_ids[domain]}/complete",
            headers={"Authorization": f"Bearer {tokens[domain]}"},
            json={"claim_token": claimed["claim_token"], "result": {"ok": True}},
        )
        assert complete.status_code == 200, complete.text
        assert complete.json()["completed"] is True

    # A reconnect after reboot updates the canonical boot identity without new credentials.
    reconnect = _put_status(http, "status", tokens["status"], boot_id="boot-b")
    assert reconnect.status_code == 200, reconnect.text
    presence = http.get(f"/api/clients/{CLIENT_ID}/presence")
    assert presence.status_code == 200
    assert presence.json()["status"]["boot_id"] == "boot-b"

    with Session(engine) as session:
        client = session.get(Client, CLIENT_ID)
        assert client is not None and client.status == "approved"
        for domain in ("status", "display", "system"):
            status = session.exec(
                select(ClientDomainStatus).where(
                    ClientDomainStatus.client_id == CLIENT_ID,
                    ClientDomainStatus.domain == domain,
                )
            ).one()
            assert status.observed_state == "online"
        commands = session.exec(
            select(ClientCommand).where(ClientCommand.client_id == CLIENT_ID)
        ).all()
        assert {row.status for row in commands} == {"succeeded"}
