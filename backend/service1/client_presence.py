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
from sqlalchemy.orm import load_only

from .client_domain_models import ClientDomainCredential, ClientDomainStatus
from .models import Client

PRESENCE_DOMAINS = ("status", "display", "system")
ONLINE_OBSERVED_STATE = "online"
SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 15
# Presence is deliberately code-owned: a deployment-time environment override would let
# server freshness drift away from the client runtime cadence without changing either
# side's reviewed protocol. Eight missed nominal reports is the canonical liveness
# policy for shared Status/Display/System presence.
SHARED_DOMAIN_MISSED_REPORT_LIMIT = 8
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


def _evaluate_client_presence_from_loaded_rows(
    client: Client,
    *,
    row_by_key: dict[tuple[int, str], ClientDomainStatus],
    credential_by_key: dict[tuple[int, str], ClientDomainCredential | None],
    now: datetime | None = None,
) -> ClientPresence:
    """Evaluate one client's canonical presence from rows already loaded."""
    if client.id is None:
        return ClientPresence(
            status=_offline("status", "client_has_no_id"),
            display=_offline("display", "client_has_no_id"),
            system=_offline("system", "client_has_no_id"),
        )

    current = _as_naive_utc(now) if now is not None else utcnow()
    evaluated: dict[str, DomainPresence] = {}
    for domain in PRESENCE_DOMAINS:
        key = (int(client.id), domain)
        evaluated[domain] = evaluate_domain_presence(
            client,
            domain=domain,
            status=row_by_key.get(key),
            credential=credential_by_key.get(key),
            now=current,
        )
    return ClientPresence(
        status=evaluated["status"],
        display=evaluated["display"],
        system=evaluated["system"],
    )


def load_client_with_presence_rows(
    session: Session,
    client_id: int,
    *,
    now: datetime | None = None,
) -> tuple[Client | None, ClientPresence | None, dict[tuple[int, str], ClientDomainStatus]]:
    """Load one Client plus all shared-domain presence evidence in one SELECT.

    Detail/hot-state endpoints need the Client row for authorization and the
    Status/Display/System rows for canonical presence. Loading them separately
    costs one avoidable database round-trip on every poll. The outer joins keep
    a Client with no domain status rows visible so 404 semantics stay unchanged.
    """
    rows = session.exec(
        select(Client, ClientDomainStatus, ClientDomainCredential)
        .join(
            ClientDomainStatus,
            (ClientDomainStatus.client_id == Client.id)
            & ClientDomainStatus.domain.in_(PRESENCE_DOMAINS),
            isouter=True,
        )
        .join(
            ClientDomainCredential,
            ClientDomainCredential.id == ClientDomainStatus.credential_id,
            isouter=True,
        )
        .options(
            load_only(
                ClientDomainCredential.id,
                ClientDomainCredential.client_id,
                ClientDomainCredential.domain,
                ClientDomainCredential.revoked_at,
            )
        )
        .where(Client.id == int(client_id))
    ).all()
    if not rows:
        return None, None, {}

    client = rows[0][0]
    row_by_key: dict[tuple[int, str], ClientDomainStatus] = {}
    credential_by_key: dict[tuple[int, str], ClientDomainCredential | None] = {}
    for _client, status_row, credential in rows:
        if status_row is None:
            continue
        key = (int(status_row.client_id), status_row.domain)
        row_by_key[key] = status_row
        credential_by_key[key] = credential

    presence = _evaluate_client_presence_from_loaded_rows(
        client,
        row_by_key=row_by_key,
        credential_by_key=credential_by_key,
        now=now,
    )
    return client, presence, row_by_key


def _load_client_presence_batch(
    session: Session,
    clients: Iterable[Client],
    *,
    now: datetime | None = None,
) -> tuple[dict[int, ClientPresence], dict[tuple[int, str], ClientDomainStatus]]:
    """Load presence plus the exact status rows in a bounded query batch.

    The raw rows are returned for read projections that need canonical payload
    data even when presence evaluates offline (for example because a credential
    was revoked). Keeping them in this batch avoids re-reading the same
    ``client_domain_status`` row once per client.
    """
    client_list = [client for client in clients if getattr(client, "id", None) is not None]
    client_ids = [int(client.id) for client in client_list]
    if not client_ids:
        return {}, {}

    rows = session.exec(
        select(ClientDomainStatus, ClientDomainCredential)
        .join(
            ClientDomainCredential,
            ClientDomainCredential.id == ClientDomainStatus.credential_id,
            isouter=True,
        )
        .options(
            load_only(
                ClientDomainCredential.id,
                ClientDomainCredential.client_id,
                ClientDomainCredential.domain,
                ClientDomainCredential.revoked_at,
            )
        )
        .where(
            ClientDomainStatus.client_id.in_(client_ids),
            ClientDomainStatus.domain.in_(PRESENCE_DOMAINS),
        )
    ).all()
    row_by_key: dict[tuple[int, str], ClientDomainStatus] = {}
    credential_by_key: dict[tuple[int, str], ClientDomainCredential | None] = {}
    for status_row, credential in rows:
        key = (int(status_row.client_id), status_row.domain)
        row_by_key[key] = status_row
        credential_by_key[key] = credential

    result: dict[int, ClientPresence] = {}
    for client in client_list:
        result[int(client.id)] = _evaluate_client_presence_from_loaded_rows(
            client,
            row_by_key=row_by_key,
            credential_by_key=credential_by_key,
            now=now,
        )
    return result, row_by_key


def load_client_presences(
    session: Session,
    clients: Iterable[Client],
    *,
    now: datetime | None = None,
) -> dict[int, ClientPresence]:
    """Load all shared-domain evidence for a client batch without N+1 queries."""
    presences, _ = _load_client_presence_batch(session, clients, now=now)
    return presences


def load_client_presences_with_status_rows(
    session: Session,
    clients: Iterable[Client],
    *,
    now: datetime | None = None,
) -> tuple[dict[int, ClientPresence], dict[tuple[int, str], ClientDomainStatus]]:
    """Return evaluated presence and already-loaded canonical status rows."""
    return _load_client_presence_batch(session, clients, now=now)

def load_client_presence(session: Session, client: Client, *, now: datetime | None = None) -> ClientPresence:
    if client.id is None:
        return ClientPresence(
            status=_offline("status", "client_has_no_id"),
            display=_offline("display", "client_has_no_id"),
            system=_offline("system", "client_has_no_id"),
        )
    return load_client_presences(session, [client], now=now)[int(client.id)]
