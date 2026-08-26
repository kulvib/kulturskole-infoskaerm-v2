from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys
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
from service1.clientflow_update_models import ClientFlowDeployment
from service1.models import Client
from service1.remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from service1.shared_domain import utcnow
from service1.terminal_v2_models import TerminalClient, TerminalCredential
from service1.routers import client_auth_compat
from service1.routers import clients
from service1.routers import shared_domain as shared_domain_router

# Exercise the real client-side System command handler/broker boundary too.
ROOT = Path(__file__).resolve().parents[2]
CLIENT_RUNTIME_ROOT = ROOT / "client" / "runtime"
if str(CLIENT_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_RUNTIME_ROOT))

from clientflow_runtime.command_agent import CommandContext  # noqa: E402
from clientflow_runtime import system_agent, system_broker  # noqa: E402


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
            ClientFlowDeployment.__table__,
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



def test_system_reboot_roundtrip_uses_real_route_agent_broker_and_boot_evidence(
    operational_http,
    monkeypatch,
    tmp_path,
):
    http, engine = operational_http

    approved = http.post(f"/api/clients/{CLIENT_ID}/approve")
    assert approved.status_code == 200, approved.text

    tokens: dict[str, str] = {}
    for domain in ("status", "system"):
        response = _token(http, domain)
        assert response.status_code == 200, response.text
        tokens[domain] = response.json()["access_token"]

    # Canonical global boot evidence comes from Status; System separately proves
    # that its privileged fixed-function broker socket is present.
    status = _put_status(http, "status", tokens["status"], boot_id="boot-a")
    assert status.status_code == 200, status.text
    system_status = http.put(
        f"/api/system-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {tokens['system']}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {"broker_socket": True},
            "agent_version": "1.3.10",
            "boot_id": "boot-a",
        },
    )
    assert system_status.status_code == 200, system_status.text

    requested = http.post(
        f"/api/clients/{CLIENT_ID}/system-command",
        json={"action": "reboot", "source": "actionbutton"},
    )
    assert requested.status_code == 200, requested.text
    command_id = requested.json()["command_id"]

    claimed_response = http.post(
        f"/api/system-agent/clients/{CLIENT_ID}/commands/claim",
        headers={"Authorization": f"Bearer {tokens['system']}"},
        json={"lease_seconds": 60},
    )
    assert claimed_response.status_code == 200, claimed_response.text
    claimed = claimed_response.json()["claimed"]
    assert claimed is not None
    command = claimed["command"]
    assert command["id"] == command_id
    assert command["command_type"] == "reboot"
    assert command["payload"]["requested_boot_id"] == "boot-a"

    # Use the actual client System handler and fixed-function broker parser. Only
    # the final host systemctl execution is replaced; no reboot occurs in CI.
    broker_state = tmp_path / "system-broker"
    monkeypatch.setattr(system_broker, "STATE_DIR", broker_state)
    monkeypatch.setattr(system_broker, "JOURNAL_PATH", broker_state / "command-journal.json")
    monkeypatch.setattr(system_broker, "JOURNAL_LOCK_PATH", broker_state / "command-journal.lock")
    monkeypatch.setattr(system_broker, "_fixed_binary", lambda name: f"/usr/bin/{name}")
    executed: list[dict[str, Any]] = []

    def fake_execute(prepared: dict[str, Any]) -> dict[str, Any]:
        executed.append(dict(prepared))
        return {"exit_code": 0, "output": "accepted"}

    monkeypatch.setattr(system_broker, "_execute", fake_execute)
    monkeypatch.setattr(
        system_agent,
        "call",
        lambda _socket, request, timeout: system_broker.handle(request),
    )
    context = CommandContext(
        command_id=command["id"],
        client_id=command["client_id"],
        command_type=command["command_type"],
        payload=command["payload"],
        schema_version=command["schema_version"],
        claim_token=claimed["claim_token"],
    )
    result = system_agent.build_handler(SimpleNamespace())(context)
    assert result["exit_code"] == 0
    assert executed == [
        {"command": ["/usr/bin/systemctl", "--no-block", "reboot"], "timeout": 10}
    ]

    completed = http.post(
        f"/api/system-agent/clients/{CLIENT_ID}/commands/{command_id}/complete",
        headers={"Authorization": f"Bearer {tokens['system']}"},
        json={"claim_token": claimed["claim_token"], "result": result},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed"] is True

    # systemctl acceptance is not reboot completion. The backend keeps reboot
    # pending until Status reports a different canonical boot_id.
    before_reconnect = http.get(f"/api/clients/{CLIENT_ID}/chrome-status")
    assert before_reconnect.status_code == 200, before_reconnect.text
    assert before_reconnect.json()["pending_reboot"] is True
    assert before_reconnect.json()["state"] == "rebooting"

    reconnect = _put_status(http, "status", tokens["status"], boot_id="boot-b")
    assert reconnect.status_code == 200, reconnect.text
    after_reconnect = http.get(f"/api/clients/{CLIENT_ID}/chrome-status")
    assert after_reconnect.status_code == 200, after_reconnect.text
    assert after_reconnect.json()["pending_reboot"] is False
    assert after_reconnect.json()["state"] == "normal"

    with Session(engine) as session:
        row = session.get(ClientCommand, command_id)
        assert row is not None
        assert row.status == "succeeded"
        assert row.client_id == CLIENT_ID
        assert row.domain == "system"


def test_display_commissioning_uses_canonical_desired_state_and_real_apply_configuration(operational_http):
    http, engine = operational_http

    approved = http.post(f"/api/clients/{CLIENT_ID}/approve")
    assert approved.status_code == 200, approved.text

    display_token_response = _token(http, "display")
    assert display_token_response.status_code == 200, display_token_response.text
    display_token = display_token_response.json()["access_token"]

    kiosk_url = "https://infoskaerm.example.test/client/4242"
    configured = http.put(
        f"/api/clients/{CLIENT_ID}/update",
        json={"kiosk_url": kiosk_url},
    )
    assert configured.status_code == 200, configured.text

    # A capable Display agent reports no applied configuration yet. The canonical
    # backend must reconcile durable desired state into a real apply_configuration
    # command instead of relying on a synthetic transport probe.
    status = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {
                "runtime": {
                    "state": "stopped",
                    "configuration_revision": None,
                    "browser_pid": None,
                }
            },
            "agent_version": "1.3.10",
            "boot_id": "display-boot-a",
        },
    )
    assert status.status_code == 200, status.text

    claim = http.post(
        f"/api/display-agent/clients/{CLIENT_ID}/commands/claim",
        headers={"Authorization": f"Bearer {display_token}"},
        json={"lease_seconds": 60},
    )
    assert claim.status_code == 200, claim.text
    claimed = claim.json()["claimed"]
    assert claimed is not None
    command = claimed["command"]
    assert command["command_type"] == "apply_configuration"
    assert command["payload"] == {
        "schema_version": 1,
        "revision": 1,
        "kiosk_url": kiosk_url,
    }

    completed = http.post(
        f"/api/display-agent/clients/{CLIENT_ID}/commands/{command['id']}/complete",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "claim_token": claimed["claim_token"],
            "result": {"applied": True, "revision": 1},
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed"] is True

    # The next real Display status reports the exact durable revision and a running
    # browser. Reconciliation must converge without generating another command.
    observed = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {
                "runtime": {
                    "state": "running",
                    "configuration_revision": 1,
                    "browser_pid": 5101,
                }
            },
            "agent_version": "1.3.10",
            "boot_id": "display-boot-a",
        },
    )
    assert observed.status_code == 200, observed.text

    no_second_command = http.post(
        f"/api/display-agent/clients/{CLIENT_ID}/commands/claim",
        headers={"Authorization": f"Bearer {display_token}"},
        json={"lease_seconds": 60},
    )
    assert no_second_command.status_code == 200, no_second_command.text
    assert no_second_command.json()["claimed"] is None

    with Session(engine) as session:
        desired = session.get(DisplayDesiredConfiguration, CLIENT_ID)
        assert desired is not None
        assert desired.revision == 1
        assert desired.kiosk_url == kiosk_url
        display_status = session.exec(
            select(ClientDomainStatus).where(
                ClientDomainStatus.client_id == CLIENT_ID,
                ClientDomainStatus.domain == "display",
            )
        ).one()
        runtime = display_status.status_payload["runtime"]
        assert runtime["state"] == "running"
        assert runtime["configuration_revision"] == desired.revision
        assert runtime["browser_pid"] == 5101
