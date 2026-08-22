from __future__ import annotations

from datetime import datetime, timedelta

from service1.client_domain_models import ClientDomainCredential, ClientDomainStatus
from service1.client_presence import (
    PRESENCE_TIMEOUT_SECONDS,
    ClientPresence,
    DomainPresence,
    evaluate_domain_presence,
)
from service1.models import Client


def _client(**overrides) -> Client:
    values = {"id": 29, "name": "presence-client", "status": "approved"}
    values.update(overrides)
    return Client(**values)


def _credential(domain: str = "status", **overrides) -> ClientDomainCredential:
    values = {
        "id": f"cred-{domain}",
        "client_id": 29,
        "domain": domain,
        "secret_hash": "not-used-by-presence-evaluation",
        "token_version": 0,
        "created_at": datetime(2026, 8, 22, 12, 0, 0),
    }
    values.update(overrides)
    return ClientDomainCredential(**values)


def _status(domain: str = "status", **overrides) -> ClientDomainStatus:
    values = {
        "id": f"status-{domain}",
        "client_id": 29,
        "domain": domain,
        "schema_version": 1,
        "observed_state": "online",
        "status_payload": {"uptime_seconds": 123.0},
        "agent_version": "test",
        "boot_id": "boot-test",
        "credential_id": f"cred-{domain}",
        "reported_at": datetime(2026, 8, 22, 12, 0, 0),
    }
    values.update(overrides)
    return ClientDomainStatus(**values)


def test_status_presence_is_fresh_until_but_not_at_exact_lease_expiry() -> None:
    reported = datetime(2026, 8, 22, 12, 0, 0)
    client = _client()
    credential = _credential()
    status = _status(reported_at=reported)

    before_expiry = evaluate_domain_presence(
        client,
        domain="status",
        status=status,
        credential=credential,
        now=reported + timedelta(seconds=PRESENCE_TIMEOUT_SECONDS, microseconds=-1),
    )
    assert before_expiry.is_online is True
    assert before_expiry.reason == "fresh_online_status"

    at_expiry = evaluate_domain_presence(
        client,
        domain="status",
        status=status,
        credential=credential,
        now=reported + timedelta(seconds=PRESENCE_TIMEOUT_SECONDS),
    )
    assert at_expiry.is_online is False
    assert at_expiry.reason == "status_stale"


def test_presence_fails_closed_for_missing_future_or_non_online_evidence() -> None:
    now = datetime(2026, 8, 22, 12, 1, 0)
    client = _client()
    credential = _credential()

    assert evaluate_domain_presence(client, domain="status", status=None, credential=None, now=now).reason == "missing_status"
    assert evaluate_domain_presence(
        client,
        domain="status",
        status=_status(reported_at=now + timedelta(seconds=1)),
        credential=credential,
        now=now,
    ).reason == "future_reported_at"
    assert evaluate_domain_presence(
        client,
        domain="status",
        status=_status(reported_at=now, observed_state="degraded"),
        credential=credential,
        now=now,
    ).reason == "agent_not_online"


def test_presence_requires_approved_active_client_and_exact_active_credential() -> None:
    now = datetime(2026, 8, 22, 12, 0, 30)
    status = _status()

    assert evaluate_domain_presence(
        _client(status="pending"), domain="status", status=status, credential=_credential(), now=now
    ).reason == "client_not_approved"
    assert evaluate_domain_presence(
        _client(deleted_at=datetime(2026, 8, 22, 11, 0, 0)),
        domain="status",
        status=status,
        credential=_credential(),
        now=now,
    ).reason == "client_deleted"
    assert evaluate_domain_presence(
        _client(),
        domain="status",
        status=status,
        credential=_credential(id="other-credential"),
        now=now,
    ).reason == "credential_inactive"
    assert evaluate_domain_presence(
        _client(),
        domain="status",
        status=status,
        credential=_credential(revoked_at=datetime(2026, 8, 22, 11, 30, 0)),
        now=now,
    ).reason == "credential_inactive"


def test_global_client_online_is_exactly_status_domain_presence() -> None:
    online_status = DomainPresence(domain="status", is_online=True, reason="fresh_online_status")
    offline_status = DomainPresence(domain="status", is_online=False, reason="status_stale")
    online_display = DomainPresence(domain="display", is_online=True, reason="fresh_online_status")
    online_system = DomainPresence(domain="system", is_online=True, reason="fresh_online_status")
    offline_display = DomainPresence(domain="display", is_online=False, reason="missing_status")
    offline_system = DomainPresence(domain="system", is_online=False, reason="missing_status")

    assert PRESENCE_TIMEOUT_SECONDS == 90
    assert ClientPresence(status=online_status, display=offline_display, system=offline_system).is_online is True
    assert ClientPresence(status=offline_status, display=online_display, system=online_system).is_online is False
