"""Fresh ClientFlow 1.2 Livestream foundation.

Revision ID: 0001_fresh_livestream
Revises:
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_fresh_livestream"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_account_organization_id", "user_account", ["organization_id"])
    op.create_index("ix_user_account_email", "user_account", ["email"])

    op.create_table(
        "client",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_client_org_name"),
    )
    op.create_index("ix_client_organization_id", "client", ["organization_id"])

    op.create_table(
        "client_domain_credential",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("secret_digest", sa.String(64), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_client_domain_credential_client_id", "client_domain_credential", ["client_id"])
    op.create_index("ix_client_domain_credential_domain", "client_domain_credential", ["domain"])
    op.create_index("ix_credential_client_domain_active", "client_domain_credential", ["client_id", "domain", "revoked_at"])

    op.create_table(
        "client_command",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("command_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token_digest", sa.String(64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_client_command_client_id", "client_command", ["client_id"])
    op.create_index("ix_client_command_domain", "client_command", ["domain"])
    op.create_index("ix_client_command_state", "client_command", ["state"])
    op.create_index("ix_client_command_available_at", "client_command", ["available_at"])
    op.create_index("ix_client_command_lease_expires_at", "client_command", ["lease_expires_at"])
    op.create_index("ix_command_claim", "client_command", ["client_id", "domain", "state", "available_at", "created_at"])

    op.create_table(
        "client_domain_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("observed_state", sa.String(64), nullable=False),
        sa.Column("status_payload", sa.JSON(), nullable=False),
        sa.Column("agent_version", sa.String(64), nullable=False),
        sa.Column("boot_id", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_id", "domain", name="uq_status_client_domain"),
    )
    op.create_index("ix_client_domain_status_client_id", "client_domain_status", ["client_id"])

    op.create_table(
        "livestream_generation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("requested_action", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_upload_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_manifest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
    )
    op.create_index("ix_livestream_generation_client_id", "livestream_generation", ["client_id"])
    op.create_index("ix_livestream_generation_state", "livestream_generation", ["state"])
    op.create_index("ix_livestream_generation_client_created", "livestream_generation", ["client_id", "created_at"])


def downgrade() -> None:
    op.drop_table("livestream_generation")
    op.drop_table("client_domain_status")
    op.drop_table("client_command")
    op.drop_table("client_domain_credential")
    op.drop_table("client")
    op.drop_table("user_account")
    op.drop_table("organization")
