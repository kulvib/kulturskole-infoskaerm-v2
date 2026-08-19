"""Mappings for the reviewed Remote Desktop session/audit tables.

These tables predate the reviewed repository baseline. Step 46A re-homes their
Remote Desktop-owned foreign keys, and Step 49A adopts the physically observed
production catalog shape into the exact runtime schema contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, JSON, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _jsonb_type():
    return JSON().with_variant(JSONB(), "postgresql")


class RemoteDesktopSession(SQLModel, table=True):
    __tablename__ = "remote_desktop_session"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_remote_desktop_session_expiry_order"),
        CheckConstraint(
            "status IN ('requested','authorized','connected','disconnected','expired','revoked','failed')",
            name="ck_remote_desktop_session_status",
        ),
        Index("ix_remote_desktop_session_client_id", "client_id"),
        Index("ix_remote_desktop_session_client_status", "client_id", "status"),
        Index("ix_remote_desktop_session_expires_at", "expires_at"),
        Index("ix_remote_desktop_session_expiry", "status", "expires_at"),
        Index("ix_remote_desktop_session_requested_by_user_id", "requested_by_user_id"),
        Index("ix_remote_desktop_session_status", "status"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="remote_desktop_client.id")
    requested_by_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    source_ip: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime
    connected_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    expires_at: datetime
    disconnected_at: Optional[datetime] = None
    status: str = Field(
        default="authorized",
        sa_column=Column(String(30), nullable=False, server_default=text("'authorized'")),
    )
    close_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


class RemoteDesktopSessionEvent(SQLModel, table=True):
    __tablename__ = "remote_desktop_session_event"
    __table_args__ = (
        Index("ix_remote_desktop_session_event_created_at", "created_at"),
        Index("ix_remote_desktop_session_event_event_type", "event_type"),
        Index("ix_remote_desktop_session_event_timeline", "remote_desktop_session_id", "created_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    remote_desktop_session_id: str = Field(foreign_key="remote_desktop_session.id", max_length=36)
    event_type: str = Field(max_length=80)
    actor_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    credential_id: Optional[str] = Field(default=None, foreign_key="remote_desktop_credential.id", max_length=36)
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_jsonb_type(), nullable=False))
