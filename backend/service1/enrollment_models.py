"""Canonical persistence for resumable ClientFlow 1.2 enrollment."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Column, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class ClientEnrollmentReceipt(SQLModel, table=True):
    __tablename__ = "client_enrollment_receipt"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_client_enrollment_receipt_expiry"),
        UniqueConstraint("client_id", name="uq_client_enrollment_receipt_client"),
        Index("ix_client_enrollment_receipt_client_id", "client_id"),
        Index("ix_client_enrollment_receipt_completed_at", "completed_at"),
        Index("ix_client_enrollment_receipt_expires_at", "expires_at"),
        Index("ix_client_enrollment_receipt_expiry", "expires_at", "completed_at"),
    )

    install_id: str = Field(primary_key=True, max_length=36)
    client_id: int = Field(foreign_key="client.id")
    resume_proof_hash: str = Field(max_length=64)
    created_at: datetime
    expires_at: datetime
    completed_at: Optional[datetime] = None


class ClientSystemEncryptionKey(SQLModel, table=True):
    __tablename__ = "client_system_encryption_key"
    __table_args__ = (
        CheckConstraint(
            "algorithm = 'RSA-OAEP-SHA256'",
            name="ck_client_system_encryption_key_algorithm",
        ),
        UniqueConstraint("client_id", name="uq_client_system_encryption_key_client"),
        Index("ix_client_system_encryption_key_active", "client_id", "revoked_at"),
        Index("ix_client_system_encryption_key_client_id", "client_id"),
        Index("ix_client_system_encryption_key_revoked_at", "revoked_at"),
    )

    id: str = Field(primary_key=True, max_length=64)
    client_id: int = Field(foreign_key="client.id")
    algorithm: str = Field(default="RSA-OAEP-SHA256", max_length=40)
    public_key_pem: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime
    revoked_at: Optional[datetime] = None
