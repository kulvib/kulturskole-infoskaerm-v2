"""Shared authenticated browser-activity lease helpers.

This module is deliberately domain-neutral. Terminal and Remote Desktop own
lease publication. Livestream reads the resulting authenticated client activity
as a lifecycle signal: any active Livestream viewer, Terminal session, or Remote
Desktop session may start/hold Livestream for the same client.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import uuid

from sqlmodel import Session, select

from .client_activity_models import ClientActivityLease
from .livestream_sweep_signal import notify_lifecycle_change

logger = logging.getLogger(__name__)

ACTIVITY_DOMAINS = frozenset({"terminal", "remote_desktop"})
ACTIVITY_LEASE_SECONDS = min(
    max(30, int(os.getenv("CLIENT_ACTIVITY_LEASE_SECONDS", "60"))),
    300,
)
ACTIVITY_RENEW_SECONDS = min(
    max(5, int(os.getenv("CLIENT_ACTIVITY_RENEW_SECONDS", "15"))),
    max(5, ACTIVITY_LEASE_SECONDS // 2),
)
ACTIVITY_RETENTION_SECONDS = max(600, int(os.getenv("CLIENT_ACTIVITY_RETENTION_SECONDS", "3600")))


# Ephemeral browser presence belongs in process memory on the current one-Render-
# instance / one-Uvicorn-worker topology. Postgres retains only open/close audit
# rows; it is no longer used as a 15-second presence heartbeat store.
_PRESENCE_LOCK = threading.Lock()
_ACTIVE_PRESENCE: set[tuple[int, str, str]] = set()
_LAST_ENDED: dict[int, datetime] = {}


def _presence_add(client_id: int, domain: str, session_id: str) -> None:
    with _PRESENCE_LOCK:
        key = (int(client_id), _domain(domain), _session_id(session_id))
        added = key not in _ACTIVE_PRESENCE
        _ACTIVE_PRESENCE.add(key)
    if added:
        notify_lifecycle_change()


def _presence_remove(client_id: int, domain: str, session_id: str) -> None:
    now = _now()
    with _PRESENCE_LOCK:
        key = (int(client_id), _domain(domain), _session_id(session_id))
        removed = key in _ACTIVE_PRESENCE
        _ACTIVE_PRESENCE.discard(key)
        _LAST_ENDED[int(client_id)] = now
    if removed:
        notify_lifecycle_change()



def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _domain(value: str) -> str:
    domain = str(value or "").strip().lower()
    if domain not in ACTIVITY_DOMAINS:
        raise ValueError("Ukendt client-activity-domæne")
    return domain


def _session_id(value: str) -> str:
    session_id = str(value or "").strip()
    if not session_id or len(session_id) > 64:
        raise ValueError("Ugyldigt client-activity session_id")
    return session_id


def expire_stale_activity_leases(
    session: Session,
    client_id: int,
    *,
    now: datetime | None = None,
) -> int:
    now = now or _now()
    cutoff = now - timedelta(seconds=ACTIVITY_LEASE_SECONDS)
    rows = session.exec(
        select(ClientActivityLease).where(
            ClientActivityLease.client_id == client_id,
            ClientActivityLease.domain.in_(tuple(ACTIVITY_DOMAINS)),
            ClientActivityLease.ended_at.is_(None),
            ClientActivityLease.last_seen_at < cutoff,
        )
    ).all()
    for row in rows:
        row.ended_at = row.last_seen_at + timedelta(seconds=ACTIVITY_LEASE_SECONDS)
        row.end_reason = "lease_expired"
        session.add(row)
    return len(rows)




def prune_old_activity_leases(
    session: Session,
    client_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """Delete old ended coordination rows; domain audit remains in domain tables."""
    now = now or _now()
    cutoff = now - timedelta(seconds=ACTIVITY_RETENTION_SECONDS)
    rows = session.exec(
        select(ClientActivityLease).where(
            ClientActivityLease.client_id == client_id,
            ClientActivityLease.ended_at.is_not(None),
            ClientActivityLease.ended_at < cutoff,
        )
    ).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def touch_activity_lease(
    session: Session,
    *,
    client_id: int,
    domain: str,
    session_id: str,
) -> ClientActivityLease:
    domain = _domain(domain)
    session_id = _session_id(session_id)
    now = _now()
    prune_old_activity_leases(session, client_id, now=now)
    row = session.exec(
        select(ClientActivityLease).where(
            ClientActivityLease.client_id == client_id,
            ClientActivityLease.domain == domain,
            ClientActivityLease.session_id == session_id,
        )
    ).first()
    if row is None:
        row = ClientActivityLease(
            id=str(uuid.uuid4()),
            client_id=client_id,
            domain=domain,
            session_id=session_id,
            created_at=now,
            last_seen_at=now,
        )
    else:
        row.last_seen_at = now
        row.ended_at = None
        row.end_reason = None
    session.add(row)
    return row


def end_activity_lease(
    session: Session,
    *,
    client_id: int,
    domain: str,
    session_id: str,
    reason: str,
) -> ClientActivityLease | None:
    domain = _domain(domain)
    session_id = _session_id(session_id)
    _presence_remove(client_id, domain, session_id)
    row = session.exec(
        select(ClientActivityLease).where(
            ClientActivityLease.client_id == client_id,
            ClientActivityLease.domain == domain,
            ClientActivityLease.session_id == session_id,
        )
    ).first()
    if row is None:
        return None
    if row.ended_at is None:
        row.ended_at = _now()
        row.end_reason = str(reason or "closed")[:32]
        session.add(row)
    return row


def active_livestream_activity_count(session: Session, client_id: int) -> int:
    del session
    with _PRESENCE_LOCK:
        return sum(1 for cid, _domain_name, _sid in _ACTIVE_PRESENCE if cid == int(client_id))


def active_livestream_activity_client_ids(
    session: Session,
    *,
    now: datetime | None = None,
) -> set[int]:
    del session, now
    with _PRESENCE_LOCK:
        return {cid for cid, _domain_name, _sid in _ACTIVE_PRESENCE}


def last_livestream_activity_ended_at(session: Session, client_id: int) -> datetime | None:
    with _PRESENCE_LOCK:
        recent = _LAST_ENDED.get(int(client_id))
    if recent is not None:
        return recent
    # Process memory is intentionally ephemeral. After a backend restart, use
    # the durable close audit once so inactivity grace remains restart-safe
    # without reintroducing periodic presence reads/writes.
    return session.exec(
        select(ClientActivityLease.ended_at)
        .where(
            ClientActivityLease.client_id == client_id,
            ClientActivityLease.domain.in_(tuple(ACTIVITY_DOMAINS)),
            ClientActivityLease.ended_at.is_not(None),
        )
        .order_by(ClientActivityLease.ended_at.desc())
        .limit(1)
    ).first()


async def maintain_activity_lease(
    engine,
    *,
    client_id: int,
    domain: str,
    session_id: str,
) -> None:
    """Publish browser presence without periodic Postgres writes.

    One durable open row is kept for compatibility/audit. The active lifecycle
    signal itself is process-local and follows the owning WebSocket lifetime.
    """
    domain = _domain(domain)
    session_id = _session_id(session_id)
    _presence_add(client_id, domain, session_id)
    try:
        try:
            with Session(engine) as session:
                touch_activity_lease(
                    session,
                    client_id=client_id,
                    domain=domain,
                    session_id=session_id,
                )
                session.commit()
        except Exception:
            logger.warning(
                "client_activity_lease_open_failed client_id=%s domain=%s session_id=%s",
                client_id, domain, session_id, exc_info=True,
            )
        await asyncio.Event().wait()
    finally:
        _presence_remove(client_id, domain, session_id)

