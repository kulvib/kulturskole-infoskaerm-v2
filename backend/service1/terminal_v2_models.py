"""SQLModel mappings owned by the ClientFlow 1.2 Terminal domain."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _jsonb_type():
    return JSON().with_variant(JSONB(), "postgresql")

class TerminalClient(SQLModel, table=True):
    """Client identity owned exclusively by the Terminal domain."""

    __tablename__ = "terminal_client"
    __table_args__ = (
        CheckConstraint("status IN ('approved','disabled')", name="ck_terminal_client_status"),
        Index("ix_terminal_client_status", "status"),
    )

    id: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    display_name: Optional[str] = Field(default=None, max_length=255)
    status: str = Field(
        default="approved",
        sa_column=Column(String(32), nullable=False, server_default=text("'approved'")),
    )
    created_at: datetime

class TerminalCredential(SQLModel, table=True):
    """Credential owned exclusively by the Terminal domain."""

    __tablename__ = "terminal_credential"
    __table_args__ = (
        CheckConstraint("token_version >= 0", name="ck_terminal_credential_token_version"),
        UniqueConstraint("client_id", name="uq_terminal_credential_client"),
        Index("ix_terminal_credential_active", "client_id", "revoked_at"),
        Index("ix_terminal_credential_last_used_at", "last_used_at"),
        Index("ix_terminal_credential_revoked_at", "revoked_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="terminal_client.id")
    secret_hash: str = Field(sa_column=Column(Text, nullable=False))
    token_version: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class TerminalAgentStatus(SQLModel, table=True):
    """Latest status reported by the isolated Terminal agent."""

    __tablename__ = "terminal_agent_status"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="ck_terminal_agent_status_schema_version"),
        UniqueConstraint("client_id", name="uq_terminal_agent_status_client"),
        Index("ix_terminal_agent_status_reported_at", "reported_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="terminal_client.id")
    schema_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    observed_state: str = Field(default="unknown", sa_column=Column(String(80), nullable=False, server_default=text("'unknown'")))
    status_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_jsonb_type(), nullable=False))
    agent_version: Optional[str] = Field(default=None, max_length=80)
    boot_id: Optional[str] = Field(default=None, max_length=128)
    credential_id: str = Field(foreign_key="terminal_credential.id", max_length=36)
    reported_at: datetime


class TerminalSession(SQLModel, table=True):
    __tablename__ = "terminal_session"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_terminal_session_expiry_order"),
        CheckConstraint("privilege_level IN ('standard','root')", name="ck_terminal_session_privilege"),
        CheckConstraint(
            "status IN ('requested','authorized','connected','disconnected','expired','revoked','failed')",
            name="ck_terminal_session_status",
        ),
        Index("ix_terminal_session_client_id", "client_id"),
        Index("ix_terminal_session_client_status", "client_id", "status"),
        Index("ix_terminal_session_expires_at", "expires_at"),
        Index("ix_terminal_session_expiry", "status", "expires_at"),
        Index("ix_terminal_session_requested_by_user_id", "requested_by_user_id"),
        Index("ix_terminal_session_status", "status"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="terminal_client.id")
    requested_by_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    privilege_level: str = Field(
        default="standard",
        sa_column=Column(String(20), nullable=False, server_default=text("'standard'")),
    )
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    source_ip: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime
    authorized_at: datetime
    connected_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    expires_at: datetime
    disconnected_at: Optional[datetime] = None
    status: str = Field(
        default="authorized",
        sa_column=Column(String(30), nullable=False, server_default=text("'authorized'")),
    )
    exit_code: Optional[int] = None
    transcript_reference: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    transcript_sha256: Optional[str] = Field(default=None, max_length=64)


class RootTerminalGrant(SQLModel, table=True):
    __tablename__ = "root_terminal_grant"
    __table_args__ = (
        CheckConstraint("capability = 'terminal_root'", name="ck_root_terminal_grant_capability"),
        CheckConstraint("expires_at > created_at", name="ck_root_terminal_grant_expiry_order"),
        UniqueConstraint("grant_hash", name="root_terminal_grant_grant_hash_key"),
        UniqueConstraint("terminal_session_id", name="uq_root_terminal_grant_session"),
        Index("ix_root_terminal_grant_client_id", "client_id"),
        Index("ix_root_terminal_grant_consumed_at", "consumed_at"),
        Index("ix_root_terminal_grant_expires_at", "expires_at"),
        Index("ix_root_terminal_grant_revoked_at", "revoked_at"),
        Index("ix_root_terminal_grant_user_id", "user_id"),
        Index("ix_root_terminal_grant_valid", "client_id", "expires_at", "consumed_at", "revoked_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    terminal_session_id: str = Field(foreign_key="terminal_session.id", max_length=36)
    client_id: int = Field(foreign_key="terminal_client.id")
    user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    grant_hash: Optional[str] = Field(default=None, max_length=64)
    step_up_verified_at: datetime
    created_at: datetime
    issued_at: Optional[datetime] = None
    expires_at: datetime
    consumed_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    capability: str = Field(
        default="terminal_root",
        sa_column=Column(String(80), nullable=False, server_default=text("'terminal_root'")),
    )
    issued_to_credential_id: Optional[str] = Field(default=None, foreign_key="terminal_credential.id", max_length=36)


class TerminalSessionEvent(SQLModel, table=True):
    __tablename__ = "terminal_session_event"
    __table_args__ = (
        Index("ix_terminal_session_event_created_at", "created_at"),
        Index("ix_terminal_session_event_event_type", "event_type"),
        Index("ix_terminal_session_event_timeline", "terminal_session_id", "created_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    terminal_session_id: str = Field(foreign_key="terminal_session.id", max_length=36)
    event_type: str = Field(max_length=80)
    actor_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    credential_id: Optional[str] = Field(default=None, foreign_key="terminal_credential.id", max_length=36)
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_jsonb_type(), nullable=False))
