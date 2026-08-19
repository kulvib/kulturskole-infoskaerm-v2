"""Database models owned exclusively by the isolated Livestream v2 control plane."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, JSON, SQLModel


def _jsonb_type():
    return JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LivestreamV2Credential(SQLModel, table=True):
    __tablename__ = "livestream_v2_credential"
    __table_args__ = (
        Index("ix_livestream_v2_credential_client_active", "client_id", "revoked_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id", index=True)
    domain: str = Field(default="livestream", max_length=64, index=True)
    secret_digest: str = Field(max_length=64)
    token_version: int = Field(default=1, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    revoked_at: Optional[datetime] = Field(default=None, index=True)


class LivestreamV2Command(SQLModel, table=True):
    __tablename__ = "livestream_v2_command"
    __table_args__ = (
        Index(
            "ix_livestream_v2_command_claim",
            "client_id",
            "state",
            "available_at",
            "created_at",
        ),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id", index=True)
    command_type: str = Field(max_length=64)
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(_jsonb_type(), nullable=False),
    )
    schema_version: int = Field(default=1, nullable=False)
    state: str = Field(default="queued", max_length=32, index=True)
    attempts: int = Field(default=0, nullable=False)
    available_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    lease_expires_at: Optional[datetime] = Field(default=None, index=True)
    claim_token_digest: Optional[str] = Field(default=None, max_length=64)
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(_jsonb_type(), nullable=True),
    )
    error_code: Optional[str] = Field(default=None, max_length=128)
    error_message: Optional[str] = Field(default=None)
    retryable: Optional[bool] = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
    completed_at: Optional[datetime] = Field(default=None, index=True)


class LivestreamV2AgentStatus(SQLModel, table=True):
    __tablename__ = "livestream_v2_agent_status"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_livestream_v2_agent_status_client"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    observed_state: str = Field(max_length=64)
    status_payload: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(_jsonb_type(), nullable=False),
    )
    agent_version: str = Field(max_length=64)
    boot_id: Optional[str] = Field(default=None, max_length=128)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)


class LivestreamV2Viewer(SQLModel, table=True):
    __tablename__ = "livestream_v2_viewer"
    __table_args__ = (
        UniqueConstraint("client_id", "viewer_id", name="uq_livestream_v2_viewer_client_viewer"),
        Index("ix_livestream_v2_viewer_active", "client_id", "ended_at", "last_seen_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    viewer_id: str = Field(max_length=120)
    principal_key: str = Field(max_length=160)
    source: Optional[str] = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    last_seen_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    ended_at: Optional[datetime] = Field(default=None, index=True)
    end_reason: Optional[str] = Field(default=None, max_length=32)


class LivestreamV2Generation(SQLModel, table=True):
    __tablename__ = "livestream_v2_generation"
    __table_args__ = (
        Index("ix_livestream_v2_generation_client_created", "client_id", "created_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id", index=True)
    state: str = Field(max_length=32, index=True)
    requested_action: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None
    last_upload_at: Optional[datetime] = Field(default=None, index=True)
    last_manifest_at: Optional[datetime] = None
    last_sequence: Optional[int] = None
    error_code: Optional[str] = Field(default=None, max_length=128)
