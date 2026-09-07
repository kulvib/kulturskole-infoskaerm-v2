"""Shared browser-activity leases used for cross-feature client lifecycle.

Terminal and Remote Desktop publish their own authenticated browser-session
presence here. Livestream consumes that shared presence as client activity for
its own lifecycle reconciliation; no domain directly invokes another domain.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ClientActivityLease(SQLModel, table=True):
    __tablename__ = "client_activity_lease"
    __table_args__ = (
        CheckConstraint(
            "domain IN ('terminal','remote_desktop')",
            name="ck_client_activity_lease_domain",
        ),
        UniqueConstraint(
            "client_id", "domain", "session_id",
            name="uq_client_activity_lease_client_domain_session",
        ),
        Index(
            "ix_client_activity_lease_active",
            "client_id", "domain", "ended_at", "last_seen_at",
        ),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id", index=True)
    domain: str = Field(max_length=32)
    session_id: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    last_seen_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    ended_at: Optional[datetime] = Field(default=None, index=True)
    end_reason: Optional[str] = Field(default=None, max_length=32)
