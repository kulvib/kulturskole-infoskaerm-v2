"""Canonical ClientFlow client/domain presence evaluation.

ClientDomainStatus is the sole runtime presence source for the shared Status,
Display and System domains. Client.last_seen and Client.isOnline are retired
legacy fields and must never participate in this contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlmodel import Session, select

from .client_domain_models import ClientDomainCredential, ClientDomainStatus
from .models import Client

PRESENCE_DOMAINS = ("status", "display", "system")
ONLINE_OBSERVED_STATE = "online"
SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 30
# Presence is deliberately code-owned: a deployment-time environment override would let
# server freshness drift away from the client runtime cadence without changing either
# side's reviewed protocol. Three missed nominal reports is the canonical liveness
# policy for shared Status/Display/System presence.
SHARED_DOMAIN_MISSED_REPORT_LIMIT = 3
PRESENCE_TIMEOUT_SECONDS = (
    SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS * SHARED_DOMAIN_MISSED_REPORT_LIMIT
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass(frozen=True, slots=True)
class DomainPresence:
    domain: str
    is_online: bool
    reason: str
    observed_state: str | None = None
    reported_at: datetime | None = None
    expires_at: datetime | None = None
    agent_version: str | None = None
    boot_id: str | None = None
    status_payload: dict | None = None

    def public_dict(self) -> dict:
        return {
            "domain": self.domain,
            "is_online": self.is_online,
            "reason": self.reason,
            "observed_state": self.observed_state,
            "reported_at": self.reported_at,
            "expires_at": self.expires_at,
            "agent_version": self.agent_version,
            "boot_id": self.boot_id,
        }


@dataclass(frozen=True, slots=True)
class ClientPresence:
    status: DomainPresence
    display: DomainPresence
    system: DomainPresence

    @property
    def is_online(self) -> bool:
        return self.status.is_online

    def public_dict(self) -> dict:
        return {
            "is_online": self.is_online,
            "status": self.status.public_dict(),
            "display": self.display.public_dict(),
            "system": self.system.public_dict(),
        }


def _offline(domain: str, reason: str) -> DomainPresence:
    return DomainPresence(domain=domain, is_online=False, reason=reason)


def evaluate_domain_presence(
    client: Client,
    *,
    domain: str,
    status: ClientDomainStatus | None,
    credential: ClientDomainCredential | None,
    now: datetime | None = None,
) -> DomainPresence:
    """Evaluate one shared-domain presence row fail-closed.

    A domain is online only when the client is active/approved, the row belongs to
    the exact domain and active credential, the agent explicitly reports
    ``online``, and the server-stamped report is still inside the presence
    lease. Missing, future, malformed, stale or revoked evidence is offline.
    """
    if domain not in PRESENCE_DOMAINS:
        raise ValueError(f"Unsupported shared presence domain: {domain}")

    if getattr(client, "deleted_at", None) is not None:
        return _offline(domain, "client_deleted")
    if str(getattr(client, "status", "") or "").strip().lower() != "approved":
        return _offline(domain, "client_not_approved")
    if status is None:
        return _offline(domain, "missing_status")
    if int(getattr(status, "client_id", 0) or 0) != int(getattr(client, "id", 0) or 0):
        return _offline(domain, "status_client_mismatch")
    if str(getattr(status, "domain", "") or "") != domain:
        return _offline(domain, "status_domain_mismatch")
    if credential is None:
        return _offline(domain, "missing_credential")
    if (
        credential.id != status.credential_id
        or credential.client_id != client.id
        or credential.domain != domain
        or credential.revoked_at is not None
    ):
        return _offline(domain, "credential_inactive")

    observed_state = str(getattr(status, "observed_state", "") or "").strip().lower()
    reported_at = _as_naive_utc(getattr(status, "reported_at", None))
    if reported_at is None:
        return DomainPresence(
            domain=domain,
            is_online=False,
            reason="missing_reported_at",
            observed_state=observed_state or None,
            agent_version=getattr(status, "agent_version", None),
            boot_id=getattr(status, "boot_id", None),
            status_payload=dict(getattr(status, "status_payload", {}) or {}),
        )

    current = _as_naive_utc(now) if now is not None else utcnow()
    if current is None or reported_at > current:
        return DomainPresence(
            domain=domain,
            is_online=False,
            reason="future_reported_at",
            observed_state=observed_state or None,
            reported_at=reported_at,
            agent_version=getattr(status, "agent_version", None),
            boot_id=getattr(status, "boot_id", None),
            status_payload=dict(getattr(status, "status_payload", {}) or {}),
        )

    expires_at = reported_at + timedelta(seconds=PRESENCE_TIMEOUT_SECONDS)
    common = {
        "domain": domain,
        "observed_state": observed_state or None,
        "reported_at": reported_at,
        "expires_at": expires_at,
        "agent_version": getattr(status, "agent_version", None),
        "boot_id": getattr(status, "boot_id", None),
        "status_payload": dict(getattr(status, "status_payload", {}) or {}),
    }
    if observed_state != ONLINE_OBSERVED_STATE:
        return DomainPresence(is_online=False, reason="agent_not_online", **common)
    if current >= expires_at:
        return DomainPresence(is_online=False, reason="status_stale", **common)
    return DomainPresence(is_online=True, reason="fresh_online_status", **common)


def load_client_presences(
    session: Session,
    clients: Iterable[Client],
    *,
    now: datetime | None = None,
) -> dict[int, ClientPresence]:
    """Load all shared-domain evidence for a client batch without N+1 queries."""
    client_list = [client for client in clients if getattr(client, "id", None) is not None]
    client_ids = [int(client.id) for client in client_list]
    if not client_ids:
        return {}

    rows = session.exec(
        select(ClientDomainStatus).where(
            ClientDomainStatus.client_id.in_(client_ids),
            ClientDomainStatus.domain.in_(PRESENCE_DOMAINS),
        )
    ).all()
    row_by_key = {(int(row.client_id), row.domain): row for row in rows}

    credential_ids = {row.credential_id for row in rows if row.credential_id}
    credential_by_id: dict[str, ClientDomainCredential] = {}
    if credential_ids:
        credentials = session.exec(
            select(ClientDomainCredential).where(ClientDomainCredential.id.in_(credential_ids))
        ).all()
        credential_by_id = {credential.id: credential for credential in credentials}

    current = _as_naive_utc(now) if now is not None else utcnow()
    result: dict[int, ClientPresence] = {}
    for client in client_list:
        evaluated: dict[str, DomainPresence] = {}
        for domain in PRESENCE_DOMAINS:
            row = row_by_key.get((int(client.id), domain))
            credential = credential_by_id.get(row.credential_id) if row is not None else None
            evaluated[domain] = evaluate_domain_presence(
                client,
                domain=domain,
                status=row,
                credential=credential,
                now=current,
            )
        result[int(client.id)] = ClientPresence(
            status=evaluated["status"],
            display=evaluated["display"],
            system=evaluated["system"],
        )
    return result


def load_client_presence(session: Session, client: Client, *, now: datetime | None = None) -> ClientPresence:
    if client.id is None:
        return ClientPresence(
            status=_offline("status", "client_has_no_id"),
            display=_offline("display", "client_has_no_id"),
            system=_offline("system", "client_has_no_id"),
        )
    return load_client_presences(session, [client], now=now)[int(client.id)]
