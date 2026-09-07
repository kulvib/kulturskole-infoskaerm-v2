"""Add first-class ClientFlow deployment and stable update credential state.

Revision ID: 20260819_51a_update_control
Revises: 20260819_50a_canonical
Create Date: 2026-08-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260819_51a_update_control"
down_revision = "20260819_50a_canonical"
branch_labels = None
depends_on = None


_DEPLOYMENT_STATES = (
    "authorized", "downloading", "verified", "staged", "activating", "health_check",
    "succeeded", "failed", "cancelled", "rolling_back", "rolled_back", "recovery_failed",
)
_TERMINAL_STATES = ("succeeded", "failed", "cancelled", "rolled_back", "recovery_failed")


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "clientflow_update_credential",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("rotated_from_credential_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint("algorithm = 'Ed25519'", name="ck_clientflow_update_credential_algorithm"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="clientflow_update_credential_client_id_fkey"),
        sa.ForeignKeyConstraint(
            ["rotated_from_credential_id"],
            ["clientflow_update_credential.id"],
            name="clientflow_update_credential_rotated_from_credential_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="clientflow_update_credential_pkey"),
    )
    op.create_index("ix_clientflow_update_credential_client_id", "clientflow_update_credential", ["client_id"])
    op.create_index("ix_clientflow_update_credential_revoked_at", "clientflow_update_credential", ["revoked_at"])
    op.create_index(
        "uq_clientflow_update_credential_active_client",
        "clientflow_update_credential",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "uq_clientflow_update_credential_key_id",
        "clientflow_update_credential",
        ["key_id"],
        unique=True,
    )

    states = _quoted(_DEPLOYMENT_STATES)
    terminal = _quoted(_TERMINAL_STATES)
    op.create_table(
        "clientflow_deployment",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("target_release_id", sa.String(length=160), nullable=False),
        sa.Column("target_version", sa.String(length=40), nullable=False),
        sa.Column("target_release_sequence", sa.Integer(), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_size", sa.Integer(), nullable=False),
        sa.Column("release_approval_reference", sa.String(length=200), nullable=False),
        sa.Column("release_candidate_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_commit", sa.String(length=64), nullable=True),
        sa.Column("allow_downgrade", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default=sa.text("'authorized'"), nullable=False),
        sa.Column("state_updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("observed_previous_release_id", sa.String(length=160), nullable=True),
        sa.Column("observed_release_id", sa.String(length=160), nullable=True),
        sa.Column("observed_release_sequence", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.CheckConstraint(f"state IN ({states})", name="ck_clientflow_deployment_state"),
        sa.CheckConstraint("target_release_sequence > 0", name="ck_clientflow_deployment_release_sequence"),
        sa.CheckConstraint("bundle_size > 0", name="ck_clientflow_deployment_bundle_size"),
        sa.CheckConstraint("length(bundle_sha256) = 64", name="ck_clientflow_deployment_bundle_sha256"),
        sa.CheckConstraint(
            f"(state IN ({terminal}) AND completed_at IS NOT NULL) OR "
            f"(state NOT IN ({terminal}) AND completed_at IS NULL)",
            name="ck_clientflow_deployment_completion",
        ),
        sa.CheckConstraint(
            "allow_downgrade = false OR reason IS NOT NULL",
            name="ck_clientflow_deployment_downgrade_reason",
        ),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="clientflow_deployment_client_id_fkey"),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["user.id"],
            name="clientflow_deployment_requested_by_user_id_fkey", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="clientflow_deployment_pkey"),
    )
    op.create_index("ix_clientflow_deployment_client_id", "clientflow_deployment", ["client_id"])
    op.create_index("ix_clientflow_deployment_requested_at", "clientflow_deployment", ["requested_at"])
    op.create_index("ix_clientflow_deployment_state", "clientflow_deployment", ["state"])
    op.create_index(
        "ix_clientflow_deployment_target_release",
        "clientflow_deployment",
        ["target_release_id", "target_release_sequence"],
    )
    op.create_index(
        "uq_clientflow_deployment_active_client",
        "clientflow_deployment",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("completed_at IS NULL"),
    )

    op.create_table(
        "clientflow_deployment_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("deployment_id", sa.String(length=36), nullable=False),
        sa.Column("credential_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["clientflow_deployment.id"],
            name="clientflow_deployment_event_deployment_id_fkey", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["clientflow_update_credential.id"],
            name="clientflow_deployment_event_credential_id_fkey", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="clientflow_deployment_event_pkey"),
    )
    op.create_index(
        "ix_clientflow_deployment_event_deployment_id", "clientflow_deployment_event", ["deployment_id"]
    )
    op.create_index(
        "ix_clientflow_deployment_event_received_at", "clientflow_deployment_event", ["received_at"]
    )
    op.create_index(
        "ix_clientflow_deployment_event_credential_id", "clientflow_deployment_event", ["credential_id"]
    )


def downgrade() -> None:
    raise RuntimeError("ClientFlow deployment authority/history kan ikke downgrades sikkert")
