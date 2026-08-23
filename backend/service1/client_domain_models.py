"""Shared SQLModel mappings for ClientFlow domain credentials and status.

These tables are deliberate shared infrastructure only for Status, Display and
System. Livestream, Terminal and Remote Desktop own isolated credential/status
storage and must not create rows here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _jsonb_type():
    return JSON().with_variant(JSONB(), "postgresql")


class ClientDomainCredential(SQLModel, table=True):
    __tablename__ = "client_domain_credential"
    __table_args__ = (
        CheckConstraint(
            "domain IN ('status','display','system')",
            name="ck_client_domain_credential_domain",
        ),
        CheckConstraint("token_version >= 0", name="ck_client_domain_credential_token_version"),
        UniqueConstraint("client_id", "domain", name="uq_client_domain_credential_client_domain"),
        Index("ix_client_domain_credential_active", "client_id", "domain", "revoked_at"),
        Index("ix_client_domain_credential_client_id", "client_id"),
        Index("ix_client_domain_credential_domain", "domain"),
        Index("ix_client_domain_credential_last_used_at", "last_used_at"),
        Index("ix_client_domain_credential_revoked_at", "revoked_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")
    domain: str = Field(max_length=40)
    secret_hash: str = Field(sa_column=Column(Text, nullable=False))
    token_version: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class ClientDomainStatus(SQLModel, table=True):
    __tablename__ = "client_domain_status"
    __table_args__ = (
        CheckConstraint(
            "domain IN ('status','display','system')",
            name="ck_client_domain_status_domain",
        ),
        CheckConstraint("schema_version >= 1", name="ck_client_domain_status_schema_version"),
        UniqueConstraint("client_id", "domain", name="uq_client_domain_status_client_domain"),
        Index("ix_client_domain_status_client_id", "client_id"),
        Index("ix_client_domain_status_domain", "domain"),
        Index("ix_client_domain_status_reported", "domain", "reported_at"),
        Index("ix_client_domain_status_reported_at", "reported_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")
    domain: str = Field(max_length=40)
    schema_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    observed_state: str = Field(
        default="unknown",
        sa_column=Column(String(80), nullable=False, server_default=text("'unknown'")),
    )
    status_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_jsonb_type(), nullable=False))
    agent_version: Optional[str] = Field(default=None, max_length=80)
    boot_id: Optional[str] = Field(default=None, max_length=128)
    credential_id: str = Field(foreign_key="client_domain_credential.id", max_length=36)
    reported_at: datetime


class DisplayDesiredConfiguration(SQLModel, table=True):
    """Durable Display-owned desired state.

    ``Client.kiosk_url`` is intentionally not an authority.  The row is the
    persistence authority that is reconciled to the Display agent.
    """

    __tablename__ = "display_desired_configuration"
    __table_args__ = (
        CheckConstraint("schema_version = 1", name="ck_display_desired_configuration_schema_version"),
        CheckConstraint("revision >= 1", name="ck_display_desired_configuration_revision"),
        Index("ix_display_desired_configuration_updated_at", "updated_at"),
    )

    client_id: int = Field(
        sa_column=Column(Integer, ForeignKey("client.id", ondelete="CASCADE"), primary_key=True)
    )
    schema_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    revision: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    kiosk_url: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime
    updated_by_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
    )


class ClientCommand(SQLModel, table=True):
    """Shared command queue owned only by Display/System agents.

    Livestream uses ``livestream_v2_command`` and is deliberately excluded
    from this shared queue.
    """

    __tablename__ = "client_command"
    __table_args__ = (
        CheckConstraint(
            "domain IN ('display','system')",
            name="ck_client_command_domain",
        ),
        CheckConstraint(
            "status IN ('queued','claimed','succeeded','failed','expired','cancelled')",
            name="ck_client_command_status",
        ),
        CheckConstraint("schema_version >= 1", name="ck_client_command_schema_version"),
        CheckConstraint("attempt_count >= 0", name="ck_client_command_attempt_nonnegative"),
        CheckConstraint("max_attempts >= 1 AND max_attempts <= 10", name="ck_client_command_max_attempts"),
        CheckConstraint("expires_at > requested_at", name="ck_client_command_expiry_order"),
        UniqueConstraint("client_id", "domain", "idempotency_key", name="uq_client_command_idempotency"),
        Index("ix_client_command_available_at", "available_at"),
        Index("ix_client_command_claim", "client_id", "domain", "status", "available_at", "expires_at"),
        Index("ix_client_command_client_id", "client_id"),
        Index("ix_client_command_domain", "domain"),
        Index("ix_client_command_expires_at", "expires_at"),
        Index("ix_client_command_lease", "status", "lease_expires_at"),
        Index("ix_client_command_lease_expires_at", "lease_expires_at"),
        Index("ix_client_command_requested_by_user_id", "requested_by_user_id"),
        Index("ix_client_command_status", "status"),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")
    domain: str = Field(max_length=40)
    command_type: str = Field(max_length=100)
    schema_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_jsonb_type(), nullable=False))
    payload_encryption_key_id: Optional[str] = Field(default=None, max_length=120)
    idempotency_key: str = Field(max_length=200)
    requested_by_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    requested_at: datetime
    available_at: datetime
    expires_at: datetime
    status: str = Field(default="queued", sa_column=Column(String(30), nullable=False, server_default=text("'queued'")))
    claim_token_hash: Optional[str] = Field(default=None, max_length=64)
    claimed_by_credential_id: Optional[str] = Field(default=None, foreign_key="client_domain_credential.id", max_length=36)
    claimed_at: Optional[datetime] = None
    lease_expires_at: Optional[datetime] = None
    attempt_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    max_attempts: int = Field(default=3, sa_column=Column(Integer, nullable=False, server_default=text("3")))
    completed_at: Optional[datetime] = None
    result: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(_jsonb_type(), nullable=True))
    error_code: Optional[str] = Field(default=None, max_length=100)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
