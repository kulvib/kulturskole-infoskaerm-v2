"""SQLModel mappings owned by the ClientFlow 1.2 Remote Desktop domain."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Column, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _jsonb_type():
    return JSON().with_variant(JSONB(), "postgresql")


class RemoteDesktopClient(SQLModel, table=True):
    """Client identity owned exclusively by Remote Desktop."""

    __tablename__ = "remote_desktop_client"
    __table_args__ = (
        CheckConstraint("status IN ('approved','disabled')", name="ck_remote_desktop_client_status"),
        Index("ix_remote_desktop_client_status", "status"),
    )

    id: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    display_name: Optional[str] = Field(default=None, max_length=255)
    status: str = Field(
        default="approved",
        sa_column=Column(String(32), nullable=False, server_default=text("'approved'")),
    )
    created_at: datetime


class RemoteDesktopCredential(SQLModel, table=True):
    """Credential owned exclusively by Remote Desktop."""

    __tablename__ = "remote_desktop_credential"
    __table_args__ = (
        CheckConstraint("token_version >= 0", name="ck_remote_desktop_credential_token_version"),
        UniqueConstraint("client_id", name="uq_remote_desktop_credential_client"),
        Index("ix_remote_desktop_credential_active", "client_id", "revoked_at"),
        Index("ix_remote_desktop_credential_last_used_at", "last_used_at"),
        Index("ix_remote_desktop_credential_revoked_at", "revoked_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="remote_desktop_client.id")
    secret_hash: str = Field(sa_column=Column(Text, nullable=False))
    token_version: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class RemoteDesktopAgentStatus(SQLModel, table=True):
    """Latest status reported by the isolated Remote Desktop agent."""

    __tablename__ = "remote_desktop_agent_status"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="ck_remote_desktop_agent_status_schema_version"),
        UniqueConstraint("client_id", name="uq_remote_desktop_agent_status_client"),
        Index("ix_remote_desktop_agent_status_reported_at", "reported_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="remote_desktop_client.id")
    schema_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    observed_state: str = Field(default="unknown", sa_column=Column(String(80), nullable=False, server_default=text("'unknown'")))
    status_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_jsonb_type(), nullable=False))
    agent_version: Optional[str] = Field(default=None, max_length=80)
    boot_id: Optional[str] = Field(default=None, max_length=128)
    credential_id: str = Field(foreign_key="remote_desktop_credential.id", max_length=36)
    reported_at: datetime
