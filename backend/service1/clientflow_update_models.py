"""Durable authority state for the stable ClientFlow update bootstrap plane.

These tables deliberately do not belong to the shared Display/System domain
credential or command queue.  A ClientFlow deployment is a first-class durable
operation whose authorization must survive replacement of /opt/clientflow/active.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


CLIENTFLOW_DEPLOYMENT_STATES = (
    "authorized",
    "downloading",
    "verified",
    "staged",
    "activating",
    "health_check",
    "succeeded",
    "failed",
    "cancelled",
    "rolling_back",
    "rolled_back",
    "recovery_failed",
)
CLIENTFLOW_DEPLOYMENT_TERMINAL_STATES = frozenset({
    "succeeded",
    "failed",
    "cancelled",
    "rolled_back",
    "recovery_failed",
})
CLIENTFLOW_DEPLOYMENT_CANCELLABLE_STATES = frozenset({
    "authorized",
    "downloading",
    "verified",
    "staged",
})


def _jsonb_type():
    return JSON().with_variant(JSONB(), "postgresql")


class ClientFlowUpdateCredential(SQLModel, table=True):
    """Asymmetric client identity owned by the stable update bootstrap plane."""

    __tablename__ = "clientflow_update_credential"
    __table_args__ = (
        CheckConstraint("algorithm = 'Ed25519'", name="ck_clientflow_update_credential_algorithm"),
        Index("ix_clientflow_update_credential_client_id", "client_id"),
        Index("ix_clientflow_update_credential_revoked_at", "revoked_at"),
        Index(
            "uq_clientflow_update_credential_active_client",
            "client_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
        Index("uq_clientflow_update_credential_key_id", "key_id", unique=True),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")
    key_id: str = Field(max_length=64)
    public_key_pem: str = Field(sa_column=Column(Text, nullable=False))
    algorithm: str = Field(default="Ed25519", max_length=20)
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    rotated_from_credential_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(36),
            ForeignKey("clientflow_update_credential.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


class ClientFlowDeployment(SQLModel, table=True):
    """Backend-authoritative immutable authorization plus observed outcome."""

    __tablename__ = "clientflow_deployment"
    __table_args__ = (
        CheckConstraint(
            "state IN ('authorized','downloading','verified','staged','activating','health_check',"
            "'succeeded','failed','cancelled','rolling_back','rolled_back','recovery_failed')",
            name="ck_clientflow_deployment_state",
        ),
        CheckConstraint(
            "target_release_sequence > 0",
            name="ck_clientflow_deployment_release_sequence",
        ),
        CheckConstraint("bundle_size > 0", name="ck_clientflow_deployment_bundle_size"),
        CheckConstraint("length(bundle_sha256) = 64", name="ck_clientflow_deployment_bundle_sha256"),
        CheckConstraint(
            "(state IN ('succeeded','failed','cancelled','rolled_back','recovery_failed') AND completed_at IS NOT NULL) "
            "OR (state NOT IN ('succeeded','failed','cancelled','rolled_back','recovery_failed') AND completed_at IS NULL)",
            name="ck_clientflow_deployment_completion",
        ),
        CheckConstraint(
            "allow_downgrade = false OR reason IS NOT NULL",
            name="ck_clientflow_deployment_downgrade_reason",
        ),
        Index("ix_clientflow_deployment_client_id", "client_id"),
        Index("ix_clientflow_deployment_requested_at", "requested_at"),
        Index("ix_clientflow_deployment_state", "state"),
        Index("ix_clientflow_deployment_target_release", "target_release_id", "target_release_sequence"),
        Index(
            "uq_clientflow_deployment_active_client",
            "client_id",
            unique=True,
            postgresql_where=text("completed_at IS NULL"),
            sqlite_where=text("completed_at IS NULL"),
        ),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")

    # Immutable backend authorization snapshot.
    target_release_id: str = Field(max_length=160)
    target_version: str = Field(max_length=40)
    target_release_sequence: int = Field(sa_column=Column(Integer, nullable=False))
    bundle_sha256: str = Field(max_length=64)
    bundle_size: int = Field(sa_column=Column(Integer, nullable=False))
    release_approval_reference: str = Field(max_length=200)
    release_candidate_sha256: Optional[str] = Field(default=None, max_length=64)
    source_commit: Optional[str] = Field(default=None, max_length=64)
    allow_downgrade: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false")))
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    requested_by_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
    )
    requested_at: datetime

    # Backend-owned lifecycle state. Updaters report events; they do not write
    # this column directly.
    state: str = Field(default="authorized", max_length=32)
    state_updated_at: datetime
    completed_at: Optional[datetime] = None

    # Observed result/provenance reported by the updater.
    observed_previous_release_id: Optional[str] = Field(default=None, max_length=160)
    observed_release_id: Optional[str] = Field(default=None, max_length=160)
    observed_release_sequence: Optional[int] = None
    failure_code: Optional[str] = Field(default=None, max_length=100)
    failure_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


class ClientFlowDeploymentEvent(SQLModel, table=True):
    """Append-only, idempotent updater/server event history for a deployment."""

    __tablename__ = "clientflow_deployment_event"
    __table_args__ = (
        Index("ix_clientflow_deployment_event_deployment_id", "deployment_id"),
        Index("ix_clientflow_deployment_event_received_at", "received_at"),
        Index("ix_clientflow_deployment_event_credential_id", "credential_id"),
    )

    id: str = Field(primary_key=True, max_length=36)
    deployment_id: str = Field(
        sa_column=Column(
            String(36),
            ForeignKey("clientflow_deployment.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    credential_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(36),
            ForeignKey("clientflow_update_credential.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    event_type: str = Field(max_length=80)
    occurred_at: Optional[datetime] = None
    received_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_jsonb_type(), nullable=False))


class ClientFlowUpdateReplay(SQLModel, table=True):
    """Persistent replay guard for private-key assertions and DPoP proofs."""

    __tablename__ = "clientflow_update_replay"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('client_assertion','dpop')",
            name="ck_clientflow_update_replay_kind",
        ),
        Index("ix_clientflow_update_replay_expires_at", "expires_at"),
        Index("ix_clientflow_update_replay_credential_id", "credential_id"),
        UniqueConstraint("jti_hash", name="uq_clientflow_update_replay_jti_hash"),
    )

    id: str = Field(primary_key=True, max_length=36)
    credential_id: str = Field(
        sa_column=Column(
            String(36),
            ForeignKey("clientflow_update_credential.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    kind: str = Field(max_length=24)
    jti_hash: str = Field(max_length=64)
    created_at: datetime
    expires_at: datetime


class ClientFlowUpdateProvisioningToken(SQLModel, table=True):
    """Short-lived client-bound bootstrap/recovery grant for an update public key."""

    __tablename__ = "clientflow_update_provisioning_token"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('bootstrap','recovery')",
            name="ck_clientflow_update_provisioning_token_purpose",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_clientflow_update_provisioning_token_expiry",
        ),
        Index("ix_clientflow_update_provisioning_token_client_id", "client_id"),
        Index("ix_clientflow_update_provisioning_token_expires_at", "expires_at"),
        Index("uq_clientflow_update_provisioning_token_code_hash", "code_hash", unique=True),
        Index(
            "uq_clientflow_update_provisioning_token_active_client",
            "client_id",
            unique=True,
            postgresql_where=text("used_at IS NULL AND revoked_at IS NULL"),
            sqlite_where=text("used_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")
    code_hash: str = Field(max_length=64)
    purpose: str = Field(max_length=20)
    created_by_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
    )
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
