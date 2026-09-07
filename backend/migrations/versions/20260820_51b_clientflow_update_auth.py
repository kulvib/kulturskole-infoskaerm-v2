"""Add persistent ClientFlow update-auth replay and reprovision state.

Revision ID: 20260820_51b_update_auth
Revises: 20260819_51a_update_control
Create Date: 2026-08-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260820_51b_update_auth"
down_revision = "20260819_51a_update_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clientflow_update_replay",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("credential_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('client_assertion','dpop')",
            name="ck_clientflow_update_replay_kind",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["clientflow_update_credential.id"],
            name="clientflow_update_replay_credential_id_fkey", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="clientflow_update_replay_pkey"),
        sa.UniqueConstraint("jti_hash", name="uq_clientflow_update_replay_jti_hash"),
    )
    op.create_index(
        "ix_clientflow_update_replay_expires_at", "clientflow_update_replay", ["expires_at"]
    )
    op.create_index(
        "ix_clientflow_update_replay_credential_id", "clientflow_update_replay", ["credential_id"]
    )

    op.create_table(
        "clientflow_update_provisioning_token",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('bootstrap','recovery')",
            name="ck_clientflow_update_provisioning_token_purpose",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_clientflow_update_provisioning_token_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["client.id"],
            name="clientflow_update_provisioning_token_client_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["user.id"],
            name="clientflow_update_provisioning_token_created_by_user_id_fkey", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="clientflow_update_provisioning_token_pkey"),
    )
    op.create_index(
        "ix_clientflow_update_provisioning_token_client_id",
        "clientflow_update_provisioning_token", ["client_id"],
    )
    op.create_index(
        "ix_clientflow_update_provisioning_token_expires_at",
        "clientflow_update_provisioning_token", ["expires_at"],
    )
    op.create_index(
        "uq_clientflow_update_provisioning_token_code_hash",
        "clientflow_update_provisioning_token", ["code_hash"], unique=True,
    )
    op.create_index(
        "uq_clientflow_update_provisioning_token_active_client",
        "clientflow_update_provisioning_token", ["client_id"], unique=True,
        postgresql_where=sa.text("used_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("ClientFlow update-auth replay/provisioning state kan ikke downgrades sikkert")
