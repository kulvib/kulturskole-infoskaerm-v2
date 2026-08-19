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
import uuid

from sqlmodel import Session, select

from .client_activity_models import ClientActivityLease

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
    expire_stale_activity_leases(session, client_id)
    return len(
        session.exec(
            select(ClientActivityLease.id).where(
                ClientActivityLease.client_id == client_id,
                ClientActivityLease.domain.in_(tuple(ACTIVITY_DOMAINS)),
                ClientActivityLease.ended_at.is_(None),
            )
        ).all()
    )


def active_livestream_activity_client_ids(
    session: Session,
    *,
    now: datetime | None = None,
) -> set[int]:
    """Return clients with a live Terminal/RD browser lease and expire stale rows."""
    now = now or _now()
    cutoff = now - timedelta(seconds=ACTIVITY_LEASE_SECONDS)
    rows = session.exec(
        select(ClientActivityLease).where(
            ClientActivityLease.domain.in_(tuple(ACTIVITY_DOMAINS)),
            ClientActivityLease.ended_at.is_(None),
        )
    ).all()
    active: set[int] = set()
    for row in rows:
        if row.last_seen_at < cutoff:
            row.ended_at = row.last_seen_at + timedelta(seconds=ACTIVITY_LEASE_SECONDS)
            row.end_reason = "lease_expired"
            session.add(row)
            continue
        active.add(int(row.client_id))
    return active


def last_livestream_activity_ended_at(session: Session, client_id: int) -> datetime | None:
    expire_stale_activity_leases(session, client_id)
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
    """Renew one browser-session lease until the owning WebSocket closes."""
    while True:
        try:
            with Session(engine) as session:
                touch_activity_lease(
                    session,
                    client_id=client_id,
                    domain=domain,
                    session_id=session_id,
                )
                session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Presence is auxiliary shared infrastructure: a temporary lease DB
            # failure must not tear down Terminal or Remote Desktop themselves.
            logger.warning(
                "client_activity_lease_renew_failed client_id=%s domain=%s session_id=%s",
                client_id,
                domain,
                session_id,
                exc_info=True,
            )
        await asyncio.sleep(ACTIVITY_RENEW_SECONDS)
