"""Add isolated ClientFlow 1.2 Livestream control-plane tables.

Revision ID: 20260814_41a_livestream_v2
Revises: 20260814_40a_livestream_control
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260814_41a_livestream_v2"
down_revision = "20260814_40a_livestream_control"
branch_labels = None
depends_on = None


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "livestream_v2_credential",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("secret_digest", sa.String(length=64), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="livestream_v2_credential_client_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="livestream_v2_credential_pkey"),
    )
    op.create_index("ix_livestream_v2_credential_client_id", "livestream_v2_credential", ["client_id"])
    op.create_index("ix_livestream_v2_credential_domain", "livestream_v2_credential", ["domain"])
    op.create_index("ix_livestream_v2_credential_revoked_at", "livestream_v2_credential", ["revoked_at"])
    op.create_index(
        "ix_livestream_v2_credential_client_active",
        "livestream_v2_credential",
        ["client_id", "revoked_at"],
    )

    op.create_table(
        "livestream_v2_command",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("command_type", sa.String(length=64), nullable=False),
        sa.Column("payload", _jsonb(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("claim_token_digest", sa.String(length=64), nullable=True),
        sa.Column("result", _jsonb(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="livestream_v2_command_client_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="livestream_v2_command_pkey"),
    )
    op.create_index("ix_livestream_v2_command_client_id", "livestream_v2_command", ["client_id"])
    op.create_index("ix_livestream_v2_command_state", "livestream_v2_command", ["state"])
    op.create_index("ix_livestream_v2_command_available_at", "livestream_v2_command", ["available_at"])
    op.create_index("ix_livestream_v2_command_lease_expires_at", "livestream_v2_command", ["lease_expires_at"])
    op.create_index("ix_livestream_v2_command_completed_at", "livestream_v2_command", ["completed_at"])
    op.create_index(
        "ix_livestream_v2_command_claim",
        "livestream_v2_command",
        ["client_id", "state", "available_at", "created_at"],
    )

    op.create_table(
        "livestream_v2_agent_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("observed_state", sa.String(length=64), nullable=False),
        sa.Column("status_payload", _jsonb(), nullable=False),
        sa.Column("agent_version", sa.String(length=64), nullable=False),
        sa.Column("boot_id", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="livestream_v2_agent_status_client_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="livestream_v2_agent_status_pkey"),
        sa.UniqueConstraint("client_id", name="uq_livestream_v2_agent_status_client"),
    )
    op.create_index("ix_livestream_v2_agent_status_client_id", "livestream_v2_agent_status", ["client_id"])
    op.create_index("ix_livestream_v2_agent_status_updated_at", "livestream_v2_agent_status", ["updated_at"])

    op.create_table(
        "livestream_v2_viewer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("viewer_id", sa.String(length=120), nullable=False),
        sa.Column("principal_key", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="livestream_v2_viewer_client_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="livestream_v2_viewer_pkey"),
        sa.UniqueConstraint("client_id", "viewer_id", name="uq_livestream_v2_viewer_client_viewer"),
    )
    op.create_index("ix_livestream_v2_viewer_client_id", "livestream_v2_viewer", ["client_id"])
    op.create_index("ix_livestream_v2_viewer_last_seen_at", "livestream_v2_viewer", ["last_seen_at"])
    op.create_index("ix_livestream_v2_viewer_ended_at", "livestream_v2_viewer", ["ended_at"])
    op.create_index(
        "ix_livestream_v2_viewer_active",
        "livestream_v2_viewer",
        ["client_id", "ended_at", "last_seen_at"],
    )

    op.create_table(
        "livestream_v2_generation",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("requested_action", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("last_upload_at", sa.DateTime(), nullable=True),
        sa.Column("last_manifest_at", sa.DateTime(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="livestream_v2_generation_client_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="livestream_v2_generation_pkey"),
    )
    op.create_index("ix_livestream_v2_generation_client_id", "livestream_v2_generation", ["client_id"])
    op.create_index("ix_livestream_v2_generation_state", "livestream_v2_generation", ["state"])
    op.create_index("ix_livestream_v2_generation_last_upload_at", "livestream_v2_generation", ["last_upload_at"])
    op.create_index(
        "ix_livestream_v2_generation_client_created",
        "livestream_v2_generation",
        ["client_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("livestream_v2_generation")
    op.drop_table("livestream_v2_viewer")
    op.drop_table("livestream_v2_agent_status")
    op.drop_table("livestream_v2_command")
    op.drop_table("livestream_v2_credential")
