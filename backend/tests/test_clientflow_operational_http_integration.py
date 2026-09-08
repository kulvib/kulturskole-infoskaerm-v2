from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta
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
from service1.display_control import display_read_projection
from service1.models import CalendarMarking, Client
from service1.season_service import current_and_next_seasons, season_dates
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
from clientflow_runtime import (  # noqa: E402
    calendar_agent,
    calendar_reboot_broker,
    display_agent,
    kiosk_lockdown,
    kiosk_lockdown_broker,
    power_lifecycle,
    system_agent,
    system_broker,
)


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
            CalendarMarking.__table__,
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

    # The real broker now records local-power attribution state before calling
    # systemctl. Keep that state fully inside the test sandbox; production uses
    # the root-owned /var/lib/clientflow/power-events defaults.
    power_state = tmp_path / "power-events"
    boot_id_path = tmp_path / "kernel-boot-id"
    boot_id_path.write_text("11111111-1111-4111-8111-111111111111\n", encoding="ascii")
    monkeypatch.setattr(power_lifecycle, "STATE_DIR", power_state)
    monkeypatch.setattr(power_lifecycle, "LOCAL_MARKER_PATH", power_state / "local-transition.json")
    monkeypatch.setattr(power_lifecycle, "SYSTEM_INTENT_PATH", power_state / "system-command-intent.json")
    monkeypatch.setattr(power_lifecycle, "BOOT_ID_PATH", boot_id_path)
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
        {"command": ["/usr/bin/systemctl", "--no-block", "--ignore-inhibitors", "reboot"], "timeout": 10}
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


def test_os_update_reboot_reconnect_reclaims_exact_same_command(operational_http):
    http, engine = operational_http
    first_boot = "11111111-1111-4111-8111-111111111111"
    second_boot = "22222222-2222-4222-8222-222222222222"

    approved = http.post(f"/api/clients/{CLIENT_ID}/approve")
    assert approved.status_code == 200, approved.text

    status_token_response = _token(http, "status")
    system_token_response = _token(http, "system")
    assert status_token_response.status_code == 200, status_token_response.text
    assert system_token_response.status_code == 200, system_token_response.text
    status_token = status_token_response.json()["access_token"]
    system_token = system_token_response.json()["access_token"]

    status = _put_status(http, "status", status_token, boot_id=first_boot)
    assert status.status_code == 200, status.text
    system_status = http.put(
        f"/api/system-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {system_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {"broker_socket": True},
            "agent_version": "1.3.10",
            "boot_id": first_boot,
        },
    )
    assert system_status.status_code == 200, system_status.text

    requested = http.post(f"/api/clients/{CLIENT_ID}/os-update")
    assert requested.status_code == 200, requested.text
    command_id = requested.json()["command_id"]

    first_claim = http.post(
        f"/api/system-agent/clients/{CLIENT_ID}/commands/claim",
        headers={"Authorization": f"Bearer {system_token}"},
        json={"lease_seconds": 300},
    )
    assert first_claim.status_code == 200, first_claim.text
    claimed_a = first_claim.json()["claimed"]
    assert claimed_a is not None
    assert claimed_a["command"]["id"] == command_id
    assert claimed_a["command"]["command_type"] == "update_os"
    assert claimed_a["command"]["payload"]["requested_boot_id"] == first_boot
    assert claimed_a["command"]["attempt_count"] == 1

    # A real reboot is authoritative only when canonical Status reports a new
    # boot identity. The old claim must then be invalidated and the exact same
    # durable command made available for broker-journal resume.
    reconnect = _put_status(http, "status", status_token, boot_id=second_boot)
    assert reconnect.status_code == 200, reconnect.text

    second_claim = http.post(
        f"/api/system-agent/clients/{CLIENT_ID}/commands/claim",
        headers={"Authorization": f"Bearer {system_token}"},
        json={"lease_seconds": 300},
    )
    assert second_claim.status_code == 200, second_claim.text
    claimed_b = second_claim.json()["claimed"]
    assert claimed_b is not None
    assert claimed_b["command"]["id"] == command_id
    assert claimed_b["command"]["payload"]["requested_boot_id"] == first_boot
    assert claimed_b["command"]["attempt_count"] == 2
    assert claimed_b["claim_token"] != claimed_a["claim_token"]

    recovered_result = {
        "exit_code": 0,
        "reboot_required": True,
        "reboot_requested": True,
        "recovered_after_boot_change": True,
        "previous_boot_id": first_boot,
        "observed_boot_id": second_boot,
    }
    completed = http.post(
        f"/api/system-agent/clients/{CLIENT_ID}/commands/{command_id}/complete",
        headers={"Authorization": f"Bearer {system_token}"},
        json={"claim_token": claimed_b["claim_token"], "result": recovered_result},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded"

    with Session(engine) as session:
        row = session.get(ClientCommand, command_id)
        assert row is not None
        assert row.status == "succeeded"
        assert row.attempt_count == 2
        assert row.result == recovered_result



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


def test_calendar_backend_route_agent_transition_broker_and_observed_status_roundtrip(
    operational_http,
    monkeypatch,
    tmp_path,
):
    http, engine = operational_http

    approved = http.post(f"/api/clients/{CLIENT_ID}/approve")
    assert approved.status_code == 200, approved.text
    display_token_response = _token(http, "display")
    assert display_token_response.status_code == 200, display_token_response.text
    display_token = display_token_response.json()["access_token"]

    seasons = current_and_next_seasons()
    target_now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    target_date = target_now.date().isoformat()

    with Session(engine) as session:
        for season in seasons:
            markings = {day.isoformat(): {"status": "off"} for day in season_dates(season)}
            if target_date in markings:
                markings[target_date] = {"status": "on", "onTime": "00:00", "offTime": "23:59"}
            session.add(CalendarMarking(season=season, client_id=CLIENT_ID, markings=markings))
        session.commit()

    calendar_dir = tmp_path / "calendar"
    calendar_dir.mkdir()
    monkeypatch.setattr(calendar_agent, "CACHE_PATH", calendar_dir / "schedule.json")
    monkeypatch.setattr(calendar_agent, "STATUS_PATH", calendar_dir / "status.json")
    monkeypatch.setattr(calendar_agent, "SCHEDULER_STATE_PATH", calendar_dir / "scheduler-state.json")
    monkeypatch.setattr(calendar_agent, "WAKE_REBOOT_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(calendar_agent, "display_control_lock", lambda: nullcontext())

    class _HttpCalendarTransport:
        credential = SimpleNamespace(client_id=CLIENT_ID)

        def json_request(self, method: str, path: str):
            assert method == "GET"
            response = http.get(path, headers={"Authorization": f"Bearer {display_token}"})
            assert response.status_code == 200, response.text
            return response.json()

    plan = calendar_agent._fetch_plan(_HttpCalendarTransport())
    assert plan["client_id"] == CLIENT_ID
    assert plan["revision"]
    assert plan["seasons"][seasons[0]][target_date]["status"] == "on"
    assert calendar_agent._desired_state(plan, target_now) == "on"
    assert json.loads(calendar_agent.CACHE_PATH.read_text(encoding="utf-8")) == plan

    power_actions: list[str] = []
    monkeypatch.setattr(
        calendar_agent,
        "set_display_power",
        lambda state: power_actions.append(state) or {"state": state},
    )
    runtime_actions: list[str] = []
    monkeypatch.setattr(
        calendar_agent,
        "runtime_action",
        lambda action, payload=None: runtime_actions.append(action) or {"ok": True},
    )

    reboot_commands: list[list[str]] = []

    def fake_reboot(command, **_kwargs):
        reboot_commands.append(list(command))
        return SimpleNamespace(returncode=0, stdout="accepted")

    monkeypatch.setattr(calendar_reboot_broker.subprocess, "run", fake_reboot)
    monkeypatch.setattr(
        calendar_agent,
        "call",
        lambda _socket, request, timeout: calendar_reboot_broker.handle(request),
    )

    scheduler = {
        "schema_version": 1,
        "last_schedule_state": None,
        "last_schedule_applied_at": None,
        "last_wake_reboot_at": 0.0,
    }

    # Initial ON establishes the baseline only; it must not manufacture a reboot.
    calendar_agent._apply_calendar_state(
        "on",
        state=scheduler,
        now_epoch=1_000.0,
        initial=True,
    )
    assert power_actions == []
    assert reboot_commands == []

    # OFF uses the canonical Display power path. A real OFF->ON transition then
    # crosses the fixed-function Calendar reboot broker exactly once.
    calendar_agent._apply_calendar_state("off", state=scheduler, now_epoch=1_100.0)
    calendar_agent._apply_calendar_state("on", state=scheduler, now_epoch=2_000.0)
    assert power_actions == ["off", "on"]
    assert runtime_actions == []
    assert reboot_commands == [
        ["/usr/bin/systemctl", "--no-block", "--ignore-inhibitors", "reboot"]
    ]

    calendar_agent._write_status(
        state="running",
        plan=plan,
        desired="on",
        last_fetch_at=2_000.0,
        last_transition_at=2_000.0,
        error=None,
    )
    monkeypatch.setattr(display_agent, "STATUS_PATH", tmp_path / "missing-runtime-status.json")
    monkeypatch.setattr(display_agent, "POWER_STATE_PATH", tmp_path / "missing-power-state.json")
    monkeypatch.setattr(display_agent, "CALENDAR_STATUS_PATH", calendar_agent.STATUS_PATH)
    monkeypatch.setattr(
        display_agent,
        "_lockdown_status",
        lambda: {
            "schema_version": 1,
            "desired": False,
            "status": "disabled",
            "message": "Kiosk lockdown er ikke anvendt",
        },
    )
    status_payload = display_agent._status()
    assert status_payload["calendar"]["state"] == "running"
    assert status_payload["calendar"]["calendar_revision"] == plan["revision"]

    reported = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": status_payload,
            "agent_version": "1.3.18",
            "boot_id": "calendar-boot-a",
        },
    )
    assert reported.status_code == 200, reported.text

    with Session(engine) as session:
        stored = session.exec(
            select(ClientDomainStatus).where(
                ClientDomainStatus.client_id == CLIENT_ID,
                ClientDomainStatus.domain == "display",
            )
        ).one()
        assert stored.status_payload["calendar"]["calendar_revision"] == plan["revision"]
        projection = display_read_projection(session, CLIENT_ID)
        assert projection["service_calendar_status"] == "running"
        assert projection["calendar"]["schedule_state"] == "on"


def test_kiosk_lockdown_frontend_api_backend_reconcile_agent_broker_and_observed_roundtrip(
    operational_http,
    monkeypatch,
    tmp_path,
):
    http, engine = operational_http

    approved = http.post(f"/api/clients/{CLIENT_ID}/approve")
    assert approved.status_code == 200, approved.text
    display_token_response = _token(http, "display")
    assert display_token_response.status_code == 200, display_token_response.text
    display_token = display_token_response.json()["access_token"]

    # Default is OFF. A client that has not published canonical lockdown
    # observation must not receive a manufactured disable command.
    initial_status = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {"integration": True},
            "agent_version": "1.3.18",
            "boot_id": "lockdown-boot-a",
        },
    )
    assert initial_status.status_code == 200, initial_status.text
    with Session(engine) as session:
        lockdown_commands = session.exec(
            select(ClientCommand).where(
                ClientCommand.client_id == CLIENT_ID,
                ClientCommand.command_type == "set_kiosk_lockdown",
            )
        ).all()
        assert lockdown_commands == []

    enabled = http.put(
        f"/api/clients/{CLIENT_ID}/update",
        json={"desktop_lockdown_enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["desktop_lockdown_enabled"] is True
    assert enabled.json()["desktop_lockdown_status"] == "pending"

    reconcile = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {
                "kiosk_lockdown": {
                    "schema_version": 1,
                    "desired": False,
                    "status": "disabled",
                    "message": "Kiosk lockdown er ikke anvendt",
                }
            },
            "agent_version": "1.3.18",
            "boot_id": "lockdown-boot-a",
        },
    )
    assert reconcile.status_code == 200, reconcile.text

    claim = http.post(
        f"/api/display-agent/clients/{CLIENT_ID}/commands/claim",
        headers={"Authorization": f"Bearer {display_token}"},
        json={"lease_seconds": 60},
    )
    assert claim.status_code == 200, claim.text
    claimed = claim.json()["claimed"]
    assert claimed is not None
    assert claimed["command"]["command_type"] == "set_kiosk_lockdown"
    assert claimed["command"]["payload"] == {"enabled": True}

    home = tmp_path / "home" / "clientflow-kiosk"
    home.mkdir(parents=True)
    record = SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_dir=str(home))
    monkeypatch.setattr(
        kiosk_lockdown,
        "_account",
        lambda: ("clientflow-kiosk", record, home),
    )
    monkeypatch.setattr(kiosk_lockdown, "STATE_PATH", tmp_path / "kiosk-lockdown-state.json")
    local_effects: list[tuple[str, bool | None]] = []
    monkeypatch.setattr(
        kiosk_lockdown,
        "_hide_launchers",
        lambda _home, _record: local_effects.append(("launchers", True)),
    )
    monkeypatch.setattr(
        kiosk_lockdown,
        "_restore_launchers",
        lambda _home, _record: local_effects.append(("launchers", False)),
    )
    monkeypatch.setattr(
        kiosk_lockdown,
        "_apply_acl",
        lambda _user, value: local_effects.append(("acl", value)),
    )
    monkeypatch.setattr(
        kiosk_lockdown,
        "_apply_polkit",
        lambda _user, value: local_effects.append(("polkit", value)),
    )
    monkeypatch.setattr(
        kiosk_lockdown,
        "_apply_gsettings",
        lambda _user, _record, value: local_effects.append(("gsettings", value)),
    )
    monkeypatch.setattr(
        kiosk_lockdown,
        "_set_quick_guard_running",
        lambda value: local_effects.append(("quick_guard", value)),
    )
    monkeypatch.setattr(display_agent, "display_control_lock", lambda: nullcontext())
    monkeypatch.setattr(
        display_agent,
        "call",
        lambda _socket, request, timeout: kiosk_lockdown_broker.handle(request),
    )

    def execute_claimed(command_payload: dict[str, Any], claim_token: str) -> dict[str, Any]:
        command = command_payload["command"]
        context = CommandContext(
            command_id=command["id"],
            client_id=command["client_id"],
            command_type=command["command_type"],
            payload=command["payload"],
            schema_version=command["schema_version"],
            claim_token=claim_token,
        )
        return display_agent._handle(context)

    apply_result = execute_claimed(claimed, claimed["claim_token"])
    assert apply_result["desired"] is True
    assert apply_result["status"] == "applied"
    assert apply_result["kiosk_user"] == "clientflow-kiosk"

    completed = http.post(
        f"/api/display-agent/clients/{CLIENT_ID}/commands/{claimed['command']['id']}/complete",
        headers={"Authorization": f"Bearer {display_token}"},
        json={"claim_token": claimed["claim_token"], "result": apply_result},
    )
    assert completed.status_code == 200, completed.text

    monkeypatch.setattr(display_agent, "STATUS_PATH", tmp_path / "missing-runtime-status.json")
    monkeypatch.setattr(display_agent, "POWER_STATE_PATH", tmp_path / "missing-power-state.json")
    monkeypatch.setattr(display_agent, "CALENDAR_STATUS_PATH", tmp_path / "missing-calendar-status.json")
    applied_status_payload = display_agent._status()
    assert applied_status_payload["kiosk_lockdown"]["desired"] is True
    assert applied_status_payload["kiosk_lockdown"]["status"] == "applied"

    observed_applied = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": applied_status_payload,
            "agent_version": "1.3.18",
            "boot_id": "lockdown-boot-a",
        },
    )
    assert observed_applied.status_code == 200, observed_applied.text

    with Session(engine) as session:
        client = session.get(Client, CLIENT_ID)
        assert client is not None
        assert client.desktop_lockdown_enabled is True
        assert client.desktop_lockdown_status == "applied"
        queued = session.exec(
            select(ClientCommand).where(
                ClientCommand.client_id == CLIENT_ID,
                ClientCommand.command_type == "set_kiosk_lockdown",
                ClientCommand.status == "queued",
            )
        ).all()
        assert queued == []

    disabled = http.put(
        f"/api/clients/{CLIENT_ID}/update",
        json={"desktop_lockdown_enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["desktop_lockdown_enabled"] is False
    assert disabled.json()["desktop_lockdown_status"] == "pending"

    reconcile_disable = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": applied_status_payload,
            "agent_version": "1.3.18",
            "boot_id": "lockdown-boot-a",
        },
    )
    assert reconcile_disable.status_code == 200, reconcile_disable.text

    disable_claim_response = http.post(
        f"/api/display-agent/clients/{CLIENT_ID}/commands/claim",
        headers={"Authorization": f"Bearer {display_token}"},
        json={"lease_seconds": 60},
    )
    assert disable_claim_response.status_code == 200, disable_claim_response.text
    disable_claim = disable_claim_response.json()["claimed"]
    assert disable_claim is not None
    assert disable_claim["command"]["command_type"] == "set_kiosk_lockdown"
    assert disable_claim["command"]["payload"] == {"enabled": False}

    rollback_result = execute_claimed(disable_claim, disable_claim["claim_token"])
    assert rollback_result["desired"] is False
    assert rollback_result["status"] == "disabled"
    assert rollback_result["kiosk_user"] == "clientflow-kiosk"

    completed_disable = http.post(
        f"/api/display-agent/clients/{CLIENT_ID}/commands/{disable_claim['command']['id']}/complete",
        headers={"Authorization": f"Bearer {display_token}"},
        json={"claim_token": disable_claim["claim_token"], "result": rollback_result},
    )
    assert completed_disable.status_code == 200, completed_disable.text

    disabled_status_payload = display_agent._status()
    observed_disabled = http.put(
        f"/api/display-agent/clients/{CLIENT_ID}/status",
        headers={"Authorization": f"Bearer {display_token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": disabled_status_payload,
            "agent_version": "1.3.18",
            "boot_id": "lockdown-boot-a",
        },
    )
    assert observed_disabled.status_code == 200, observed_disabled.text

    with Session(engine) as session:
        client = session.get(Client, CLIENT_ID)
        assert client is not None
        assert client.desktop_lockdown_enabled is False
        assert client.desktop_lockdown_status == "disabled"

    assert ("launchers", True) in local_effects
    assert ("acl", True) in local_effects
    assert ("polkit", True) in local_effects
    assert ("gsettings", True) in local_effects
    assert ("quick_guard", True) in local_effects
    assert ("quick_guard", False) in local_effects
    assert ("launchers", False) in local_effects
    assert ("acl", False) in local_effects
    assert ("polkit", False) in local_effects
    assert ("gsettings", False) in local_effects
