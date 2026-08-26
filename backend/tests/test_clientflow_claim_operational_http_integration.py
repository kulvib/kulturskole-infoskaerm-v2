from __future__ import annotations

import asyncio
import base64
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
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Exercise the client-side derivation contract against the real backend claim route.
ROOT = Path(__file__).resolve().parents[2]
CLIENT_RELEASE_LIB = ROOT / "client" / "release" / "lib"
if str(CLIENT_RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(CLIENT_RELEASE_LIB))

from clientflow_release.enrollment import derive_domain_secret, derive_resume_proof
from clientflow_release.update_auth import build_client_assertion, build_dpop_proof, generate_update_key
from clientflow_release.updater_transport import CLIENT_ASSERTION_TYPE, UPDATE_SCOPES

from service1.client_domain_models import (
    ClientCommand,
    ClientDomainCredential,
    ClientDomainStatus,
    DisplayDesiredConfiguration,
)
from service1.clientflow_update_models import (
    ClientFlowDeployment,
    ClientFlowUpdateCredential,
    ClientFlowUpdateReplay,
)
from service1.enrollment_models import ClientEnrollmentReceipt, ClientSystemEncryptionKey
from service1.livestream_v2_models import LivestreamV2Credential
from service1.models import Client, EnrollmentToken
from service1.remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from service1.terminal_v2_models import TerminalClient, TerminalCredential
from service1.routers import client_auth_compat
from service1.routers import clients
from service1.routers import clientflow_update
from service1.routers import enrollment as enrollment_router
from service1.routers import remote_desktop_auth
from service1.routers import shared_domain as shared_domain_router
from service1.routers import terminal_auth


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


TEST_SYSTEM_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAoia5/Qqkv6PJidOyW+5i
loeFlY0cp4BWfI0i2jagFRvtp9KYULb13koJGzjK9/rLdHLn2/91bKcXQnZKY6CP
ICfH5jXoscWXVCxC1DL6pQ/+R9F+lFJ1o5t2Scz52DhyWRY2XnppZ1kICniYc5yX
KVyrnYG5xNrRMTrb8r7BtDm7I3QwlYl9V96XqdrEEZRAgyZCML9ZbSjHIiI29Hu+
6q4NSY7CoxAp7oGdNsfhhPqF+Am2AtD8IJALQHWduZK0C74amXPaYNuE+Bl+x25M
TEHLgOQgYQ07E74f2bpXS9uCQciDLDSgmyGOQkAwrud1nlyYclVY9BafgeSE4nbp
eQIDAQAB
-----END PUBLIC KEY-----
"""

TEST_RELEASE_SNAPSHOT = {
    "target_release_id": "clientflow-9.8.7-seq-6543",
    "target_version": "9.8.7",
    "target_release_sequence": 6543,
    "bundle_sha256": "a" * 64,
    "bundle_size": 80_123_456,
    "release_approval_reference": "operational-integration/approved",
    "release_candidate_sha256": "b" * 64,
    "source_commit": "c" * 40,
}

DOMAIN_NAMES = ("status", "display", "livestream", "remote_desktop", "terminal", "system")


def _binding_from_capability(capability: dict[str, Any]) -> dict[str, Any]:
    return {
        "release_id": capability["release_id"],
        "version": capability["version"],
        "release_sequence": capability["release_sequence"],
        "bundle_sha256": capability["bundle_sha256"],
        "bundle_size": capability["bundle_size"],
        "release_approval_reference": capability["release_approval_reference"],
        "release_candidate_sha256": capability["release_candidate_sha256"],
        "source_commit": capability["source_commit"],
    }


def _auth_path(domain: str) -> str:
    if domain == "terminal":
        return "/api/terminal-auth/token"
    if domain == "remote_desktop":
        return "/api/remote-desktop-auth/token"
    return "/api/client-auth/token"


def _domain_token(
    http: _ASGITestClient,
    *,
    client_id: int,
    domain: str,
    credential_id: str,
    client_secret: str,
) -> _ASGIResponse:
    return http.post(
        _auth_path(domain),
        json={
            "client_id": client_id,
            "credential_id": credential_id,
            "domain": domain,
            "client_secret": client_secret,
        },
    )


def _put_status(
    http: _ASGITestClient,
    *,
    client_id: int,
    domain: str,
    token: str,
    boot_id: str,
) -> _ASGIResponse:
    return http.put(
        f"/api/{domain}-agent/clients/{client_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {"claim_integration": True},
            "agent_version": TEST_RELEASE_SNAPSHOT["target_version"],
            "boot_id": boot_id,
        },
    )


def _new_system_public_key_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


@pytest.fixture
def claimed_operational_http(monkeypatch, tmp_path):
    # Test-only trust material; all keys are exactly 32 bytes after URL-safe decoding.
    key_b64 = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64", key_b64)
    monkeypatch.setenv("CLIENTFLOW_ROOT_TERMINAL_KEY_B64", key_b64)
    monkeypatch.setenv("CLIENTFLOW_ROOT_TERMINAL_KEY_ID", "claim-integration-root-key")
    monkeypatch.setenv("CLIENTFLOW_TERMINAL_AUTH_KEY_B64", key_b64)
    monkeypatch.setenv("CLIENTFLOW_REMOTE_DESKTOP_AUTH_KEY_B64", key_b64)
    monkeypatch.setenv(
        "LIVESTREAM_V2_CREDENTIAL_PEPPER",
        "claim-integration-livestream-pepper-with-at-least-thirty-two-chars",
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            Client.__table__,
            EnrollmentToken.__table__,
            ClientEnrollmentReceipt.__table__,
            ClientSystemEncryptionKey.__table__,
            ClientFlowUpdateCredential.__table__,
            ClientFlowUpdateReplay.__table__,
            ClientFlowDeployment.__table__,
            ClientDomainCredential.__table__,
            LivestreamV2Credential.__table__,
            TerminalClient.__table__,
            TerminalCredential.__table__,
            RemoteDesktopClient.__table__,
            RemoteDesktopCredential.__table__,
            ClientDomainStatus.__table__,
            DisplayDesiredConfiguration.__table__,
            ClientCommand.__table__,
        ],
    )

    monkeypatch.setattr(enrollment_router, "fresh_install_release_snapshot", lambda: dict(TEST_RELEASE_SNAPSHOT))
    monkeypatch.setattr(enrollment_router, "add_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client_auth_compat, "engine", engine)
    monkeypatch.setattr(clientflow_update, "add_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(shared_domain_router, "engine", engine)
    monkeypatch.setattr(terminal_auth, "engine", engine)
    monkeypatch.setattr(remote_desktop_auth, "engine", engine)
    monkeypatch.setattr(clients, "current_and_next_seasons", lambda: [])
    monkeypatch.setattr(clients, "add_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clients, "_prepare_full_client_read", lambda _session, client: client)

    def session_override():
        with Session(engine) as session:
            yield session

    superadmin = SimpleNamespace(
        id=1,
        username="claim-integration-superadmin",
        role="superadmin",
        organization_id=None,
        is_superadmin=True,
        is_admin=True,
    )

    app = FastAPI()
    app.include_router(enrollment_router.router, prefix="/api")
    app.include_router(clients.router, prefix="/api")
    app.include_router(client_auth_compat.router, prefix="/api")
    app.include_router(clientflow_update.router, prefix="/api")
    app.include_router(shared_domain_router.router, prefix="/api")
    app.include_router(terminal_auth.router, prefix="/api")
    app.include_router(remote_desktop_auth.router, prefix="/api")
    app.dependency_overrides[enrollment_router.get_session] = session_override
    app.dependency_overrides[enrollment_router.get_current_superadmin_user] = lambda: superadmin
    app.dependency_overrides[clients.get_session] = session_override
    app.dependency_overrides[clientflow_update.get_session] = session_override
    app.dependency_overrides[clients.get_current_superadmin_user] = lambda: superadmin
    app.dependency_overrides[clients.get_current_user_or_client] = lambda: superadmin

    update_private_key = tmp_path / "update-private-key.pem"
    update_public_pem, update_key_id, _jwk, _jkt = generate_update_key(update_private_key)

    yield _ASGITestClient(app), engine, update_private_key, update_public_pem, update_key_id


def test_fresh_authorization_claim_resume_approval_and_runtime_roundtrip(claimed_operational_http):
    http, engine, update_private_key, update_public_pem, expected_update_key_id = claimed_operational_http

    # 1. The real admin route creates the one-time capability and signed exact release binding.
    capability_response = http.post(
        "/api/admin/enrollment-tokens",
        json={"expires_in_hours": 1, "note": "claim integration"},
    )
    assert capability_response.status_code == 201, capability_response.text
    capability = capability_response.json()
    binding = _binding_from_capability(capability)
    assert binding == {
        "release_id": TEST_RELEASE_SNAPSHOT["target_release_id"],
        "version": TEST_RELEASE_SNAPSHOT["target_version"],
        "release_sequence": TEST_RELEASE_SNAPSHOT["target_release_sequence"],
        "bundle_sha256": TEST_RELEASE_SNAPSHOT["bundle_sha256"],
        "bundle_size": TEST_RELEASE_SNAPSHOT["bundle_size"],
        "release_approval_reference": TEST_RELEASE_SNAPSHOT["release_approval_reference"],
        "release_candidate_sha256": TEST_RELEASE_SNAPSHOT["release_candidate_sha256"],
        "source_commit": TEST_RELEASE_SNAPSHOT["source_commit"],
    }

    # 2. The request uses the actual client implementation for resume-proof and domain-secret derivation.
    install_id = str(uuid.uuid4())
    seed = bytes(reversed(range(32)))
    seed_b64 = base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii")
    resume_proof = derive_resume_proof(seed, install_id)
    claim_request = {
        "enrollment_code": capability["code"],
        "fresh_install_authorization": capability["fresh_install_authorization"],
        "fresh_install_binding": binding,
        "install_id": install_id,
        "credential_seed_b64": seed_b64,
        "resume_proof": resume_proof,
        "system_encryption_public_key_pem": TEST_SYSTEM_PUBLIC_KEY_PEM,
        "update_auth_public_key_pem": update_public_pem,
        "name": "Claim Integration Client",
        "hostname": "claim-integration-client",
        "machine_id": "claim-integration-machine-id",
        "ubuntu_version": "26.04",
    }
    claim_response = http.post("/api/enrollment/claim", json=claim_request)
    assert claim_response.status_code == 200, claim_response.text
    claim = claim_response.json()
    client_id = int(claim["client_id"])
    assert claim["status"] == "pending"
    assert claim["update_auth"]["key_id"] == expected_update_key_id

    credential_rows = claim["credentials"]
    assert [row["domain"] for row in credential_rows] == list(DOMAIN_NAMES)
    credential_ids = {row["domain"]: row["credential_id"] for row in credential_rows}
    assert len(set(credential_ids.values())) == len(DOMAIN_NAMES)
    secrets_by_domain = {
        domain: derive_domain_secret(
            seed,
            client_id=client_id,
            credential_id=credential_ids[domain],
            domain=domain,
        )
        for domain in DOMAIN_NAMES
    }

    # 3. A lost response after committed claim can resume without the consumed one-time capability,
    # but only with the exact original binding, seed/resume proof and key material.
    resume_request = dict(claim_request)
    resume_request["enrollment_code"] = None
    resume_request["fresh_install_authorization"] = None
    resumed_response = http.post("/api/enrollment/claim", json=resume_request)
    assert resumed_response.status_code == 200, resumed_response.text
    resumed = resumed_response.json()
    assert resumed["client_id"] == client_id
    assert resumed["system_encryption_key_id"] == claim["system_encryption_key_id"]
    assert resumed["update_auth"] == claim["update_auth"]
    assert resumed["credentials"] == credential_rows

    complete = http.post(
        "/api/enrollment/complete",
        json={
            "install_id": install_id,
            "resume_proof": resume_proof,
            "fresh_install_binding": binding,
        },
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["client_id"] == client_id

    # 4. Every provisioned domain identity is fail-closed while the main client is pending.
    for domain in DOMAIN_NAMES:
        pending = _domain_token(
            http,
            client_id=client_id,
            domain=domain,
            credential_id=credential_ids[domain],
            client_secret=secrets_by_domain[domain],
        )
        assert pending.status_code == 401, (domain, pending.text)

    # The separately provisioned asymmetric update identity is also fail-closed while pending.
    pending_update_assertion = build_client_assertion(
        update_private_key,
        credential_id=claim["update_auth"]["credential_id"],
        key_id=claim["update_auth"]["key_id"],
    )
    pending_update_dpop = build_dpop_proof(
        update_private_key,
        method="POST",
        url="http://testserver/api/clientflow-update/token",
    )
    pending_update = http.post(
        "/api/clientflow-update/token",
        headers={"DPoP": pending_update_dpop},
        json={
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": pending_update_assertion,
            "scope": " ".join(sorted(UPDATE_SCOPES)),
        },
    )
    assert pending_update.status_code == 401, pending_update.text

    # 5. Backend approval enables those exact same six identities; no rotation/reprovisioning occurs.
    approved = http.post(f"/api/clients/{client_id}/approve")
    assert approved.status_code == 200, approved.text

    tokens: dict[str, str] = {}
    for domain in DOMAIN_NAMES:
        accepted = _domain_token(
            http,
            client_id=client_id,
            domain=domain,
            credential_id=credential_ids[domain],
            client_secret=secrets_by_domain[domain],
        )
        assert accepted.status_code == 200, (domain, accepted.text)
        payload = accepted.json()
        assert payload["client_id"] == client_id
        assert payload["credential_id"] == credential_ids[domain]
        assert payload["domain"] == domain
        tokens[domain] = payload["access_token"]

    # The same claim-created update key can now authenticate and access the updater control plane.
    update_assertion = build_client_assertion(
        update_private_key,
        credential_id=claim["update_auth"]["credential_id"],
        key_id=claim["update_auth"]["key_id"],
    )
    update_dpop = build_dpop_proof(
        update_private_key,
        method="POST",
        url="http://testserver/api/clientflow-update/token",
    )
    update_token_response = http.post(
        "/api/clientflow-update/token",
        headers={"DPoP": update_dpop},
        json={
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": update_assertion,
            "scope": " ".join(sorted(UPDATE_SCOPES)),
        },
    )
    assert update_token_response.status_code == 200, update_token_response.text
    update_token_payload = update_token_response.json()
    assert update_token_payload["token_type"].lower() == "dpop"
    assert frozenset(update_token_payload["scope"].split()) == UPDATE_SCOPES
    update_access_token = update_token_payload["access_token"]

    active_dpop = build_dpop_proof(
        update_private_key,
        method="GET",
        url="http://testserver/api/clientflow-update/deployments/active",
        access_token=update_access_token,
    )
    active_deployment_response = http.get(
        "/api/clientflow-update/deployments/active",
        headers={
            "Authorization": f"DPoP {update_access_token}",
            "DPoP": active_dpop,
        },
    )
    assert active_deployment_response.status_code == 200, active_deployment_response.text
    assert active_deployment_response.json() is None

    # 6. Shared runtime protocols use the claim-created credentials and produce canonical presence.
    for domain in ("status", "display", "system"):
        response = _put_status(
            http,
            client_id=client_id,
            domain=domain,
            token=tokens[domain],
            boot_id="claim-boot-a",
        )
        assert response.status_code == 200, response.text
        assert response.json()["observed_state"] == "online"

    presence = http.get(f"/api/clients/{client_id}/presence")
    assert presence.status_code == 200, presence.text
    presence_payload = presence.json()
    assert presence_payload["is_online"] is True
    assert presence_payload["status"]["boot_id"] == "claim-boot-a"
    assert presence_payload["display"]["boot_id"] == "claim-boot-a"
    assert presence_payload["system"]["boot_id"] == "claim-boot-a"

    # 7. Display/System command lease + completion roundtrip is bound to those same claim credentials.
    from service1.shared_domain import utcnow
    from datetime import timedelta

    now = utcnow()
    with Session(engine) as session:
        for domain in ("display", "system"):
            session.add(
                ClientCommand(
                    id=str(uuid.uuid4()),
                    client_id=client_id,
                    domain=domain,
                    command_type="claim_integration_probe",
                    schema_version=1,
                    payload={"domain": domain},
                    idempotency_key=f"claim-integration-{domain}",
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
            for row in session.exec(select(ClientCommand).where(ClientCommand.client_id == client_id)).all()
        }

    for domain in ("display", "system"):
        claim_command = http.post(
            f"/api/{domain}-agent/clients/{client_id}/commands/claim",
            headers={"Authorization": f"Bearer {tokens[domain]}"},
            json={"lease_seconds": 60},
        )
        assert claim_command.status_code == 200, claim_command.text
        claimed = claim_command.json()["claimed"]
        assert claimed is not None
        assert claimed["command"]["id"] == command_ids[domain]
        completed = http.post(
            f"/api/{domain}-agent/clients/{client_id}/commands/{command_ids[domain]}/complete",
            headers={"Authorization": f"Bearer {tokens[domain]}"},
            json={"claim_token": claimed["claim_token"], "result": {"ok": True}},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["completed"] is True

    # 8. Reboot/reconnect preserves identity and updates canonical boot evidence.
    reconnect = _put_status(
        http,
        client_id=client_id,
        domain="status",
        token=tokens["status"],
        boot_id="claim-boot-b",
    )
    assert reconnect.status_code == 200, reconnect.text
    presence = http.get(f"/api/clients/{client_id}/presence")
    assert presence.status_code == 200
    assert presence.json()["status"]["boot_id"] == "claim-boot-b"

    # 9. Persistence proves one client identity, one receipt, six isolated credentials,
    # separate system/update identities, and one-time token consumption.
    with Session(engine) as session:
        client = session.get(Client, client_id)
        assert client is not None and client.status == "approved"
        receipt = session.get(ClientEnrollmentReceipt, install_id)
        assert receipt is not None and receipt.client_id == client_id and receipt.completed_at is not None
        enrollment_token = session.get(EnrollmentToken, int(capability["id"]))
        assert enrollment_token is not None
        assert enrollment_token.used_by_client_id == client_id
        assert enrollment_token.used_at is not None

        system_key = session.exec(
            select(ClientSystemEncryptionKey).where(ClientSystemEncryptionKey.client_id == client_id)
        ).one()
        update_credential = session.exec(
            select(ClientFlowUpdateCredential).where(ClientFlowUpdateCredential.client_id == client_id)
        ).one()
        assert system_key.id == claim["system_encryption_key_id"]
        assert update_credential.id == claim["update_auth"]["credential_id"]
        assert update_credential.key_id == claim["update_auth"]["key_id"]
        assert system_key.id != update_credential.key_id
        assert update_credential.id not in set(credential_ids.values())

        shared = session.exec(
            select(ClientDomainCredential).where(ClientDomainCredential.client_id == client_id)
        ).all()
        assert {row.domain for row in shared} == {"status", "display", "system"}
        livestream = session.exec(
            select(LivestreamV2Credential).where(LivestreamV2Credential.client_id == client_id)
        ).one()
        terminal = session.exec(
            select(TerminalCredential).where(TerminalCredential.client_id == client_id)
        ).one()
        remote_desktop = session.exec(
            select(RemoteDesktopCredential).where(RemoteDesktopCredential.client_id == client_id)
        ).one()
        persisted_ids = {row.id for row in shared} | {livestream.id, terminal.id, remote_desktop.id}
        assert persisted_ids == set(credential_ids.values())



def test_two_fresh_installations_have_disjoint_identities_and_cross_client_auth_fails_closed(
    claimed_operational_http,
    tmp_path,
):
    http, engine, update_private_a, update_public_a, update_key_id_a = claimed_operational_http
    update_private_b = tmp_path / "update-private-key-b.pem"
    update_public_b, update_key_id_b, _jwk_b, _jkt_b = generate_update_key(update_private_b)
    system_public_a = _new_system_public_key_pem()
    system_public_b = _new_system_public_key_pem()
    assert system_public_a != system_public_b
    assert update_public_a != update_public_b
    assert update_key_id_a != update_key_id_b

    def claim_one(label: str, seed: bytes, update_public: str, system_public: str) -> dict[str, Any]:
        capability_response = http.post(
            "/api/admin/enrollment-tokens",
            json={"expires_in_hours": 1, "note": f"multiclient {label}"},
        )
        assert capability_response.status_code == 201, capability_response.text
        capability = capability_response.json()
        binding = _binding_from_capability(capability)
        install_id = str(uuid.uuid4())
        seed_b64 = base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii")
        resume_proof = derive_resume_proof(seed, install_id)
        response = http.post(
            "/api/enrollment/claim",
            json={
                "enrollment_code": capability["code"],
                "fresh_install_authorization": capability["fresh_install_authorization"],
                "fresh_install_binding": binding,
                "install_id": install_id,
                "credential_seed_b64": seed_b64,
                "resume_proof": resume_proof,
                "system_encryption_public_key_pem": system_public,
                "update_auth_public_key_pem": update_public,
                "name": f"Multi {label}",
                "hostname": f"multi-{label.lower()}",
                "machine_id": f"machine-{label.lower()}-{uuid.uuid4()}",
                "ubuntu_version": "26.04",
            },
        )
        assert response.status_code == 200, response.text
        claim = response.json()
        complete = http.post(
            "/api/enrollment/complete",
            json={
                "install_id": install_id,
                "resume_proof": resume_proof,
                "fresh_install_binding": binding,
            },
        )
        assert complete.status_code == 200, complete.text
        return {
            "claim": claim,
            "capability": capability,
            "binding": binding,
            "install_id": install_id,
            "seed": seed,
        }

    install_a = claim_one("A", bytes(range(32)), update_public_a, system_public_a)
    install_b = claim_one("B", bytes(reversed(range(32))), update_public_b, system_public_b)
    claim_a = install_a["claim"]
    claim_b = install_b["claim"]
    client_a = int(claim_a["client_id"])
    client_b = int(claim_b["client_id"])
    assert client_a != client_b

    credentials_a = {row["domain"]: row["credential_id"] for row in claim_a["credentials"]}
    credentials_b = {row["domain"]: row["credential_id"] for row in claim_b["credentials"]}
    assert set(credentials_a) == set(DOMAIN_NAMES)
    assert set(credentials_b) == set(DOMAIN_NAMES)
    assert set(credentials_a.values()).isdisjoint(credentials_b.values())
    assert claim_a["system_encryption_key_id"] != claim_b["system_encryption_key_id"]
    assert claim_a["update_auth"]["credential_id"] != claim_b["update_auth"]["credential_id"]
    assert claim_a["update_auth"]["key_id"] != claim_b["update_auth"]["key_id"]

    approved_a = http.post(f"/api/clients/{client_a}/approve")
    approved_b = http.post(f"/api/clients/{client_b}/approve")
    assert approved_a.status_code == 200, approved_a.text
    assert approved_b.status_code == 200, approved_b.text

    secrets_a = {
        domain: derive_domain_secret(
            install_a["seed"],
            client_id=client_a,
            credential_id=credentials_a[domain],
            domain=domain,
        )
        for domain in DOMAIN_NAMES
    }
    secrets_b = {
        domain: derive_domain_secret(
            install_b["seed"],
            client_id=client_b,
            credential_id=credentials_b[domain],
            domain=domain,
        )
        for domain in DOMAIN_NAMES
    }

    tokens_a: dict[str, str] = {}
    tokens_b: dict[str, str] = {}
    for domain in DOMAIN_NAMES:
        accepted_a = _domain_token(
            http,
            client_id=client_a,
            domain=domain,
            credential_id=credentials_a[domain],
            client_secret=secrets_a[domain],
        )
        accepted_b = _domain_token(
            http,
            client_id=client_b,
            domain=domain,
            credential_id=credentials_b[domain],
            client_secret=secrets_b[domain],
        )
        assert accepted_a.status_code == 200, (domain, accepted_a.text)
        assert accepted_b.status_code == 200, (domain, accepted_b.text)
        tokens_a[domain] = accepted_a.json()["access_token"]
        tokens_b[domain] = accepted_b.json()["access_token"]

        # A credential/secret pair cannot be relabelled as installation B.
        wrong_client = _domain_token(
            http,
            client_id=client_b,
            domain=domain,
            credential_id=credentials_a[domain],
            client_secret=secrets_a[domain],
        )
        assert wrong_client.status_code in {401, 403}, (domain, wrong_client.text)

    # Bearer tokens for the shared domains are also route-bound to their exact
    # installation, not only to the credential ID used when issuing the token.
    cross_status = http.put(
        f"/api/status-agent/clients/{client_b}/status",
        headers={"Authorization": f"Bearer {tokens_a['status']}"},
        json={
            "schema_version": 1,
            "observed_state": "online",
            "status_payload": {"cross_client": True},
            "agent_version": TEST_RELEASE_SNAPSHOT["target_version"],
            "boot_id": "wrong-client-boot",
        },
    )
    assert cross_status.status_code == 403, cross_status.text

    for domain in ("display", "system"):
        cross_claim = http.post(
            f"/api/{domain}-agent/clients/{client_b}/commands/claim",
            headers={"Authorization": f"Bearer {tokens_a[domain]}"},
            json={"lease_seconds": 60},
        )
        assert cross_claim.status_code == 403, (domain, cross_claim.text)

    # The asymmetric update identity cannot impersonate installation B by
    # substituting B's credential metadata while signing with A's private key.
    wrong_update_assertion = build_client_assertion(
        update_private_a,
        credential_id=claim_b["update_auth"]["credential_id"],
        key_id=claim_b["update_auth"]["key_id"],
    )
    wrong_update_dpop = build_dpop_proof(
        update_private_a,
        method="POST",
        url="http://testserver/api/clientflow-update/token",
    )
    wrong_update = http.post(
        "/api/clientflow-update/token",
        headers={"DPoP": wrong_update_dpop},
        json={
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": wrong_update_assertion,
            "scope": " ".join(sorted(UPDATE_SCOPES)),
        },
    )
    assert wrong_update.status_code == 401, wrong_update.text

    with Session(engine) as session:
        receipts = session.exec(select(ClientEnrollmentReceipt)).all()
        assert {row.client_id for row in receipts} == {client_a, client_b}
        assert len({row.install_id for row in receipts}) == 2

        system_keys = session.exec(select(ClientSystemEncryptionKey)).all()
        assert len(system_keys) == 2
        assert len({row.id for row in system_keys}) == 2
        assert len({row.public_key_pem for row in system_keys}) == 2

        update_credentials = session.exec(select(ClientFlowUpdateCredential)).all()
        assert len(update_credentials) == 2
        assert len({row.id for row in update_credentials}) == 2
        assert len({row.key_id for row in update_credentials}) == 2
        assert len({row.public_key_pem for row in update_credentials}) == 2

        enrollment_tokens = session.exec(select(EnrollmentToken)).all()
        used_by = {row.used_by_client_id for row in enrollment_tokens if row.used_at is not None}
        assert used_by == {client_a, client_b}
