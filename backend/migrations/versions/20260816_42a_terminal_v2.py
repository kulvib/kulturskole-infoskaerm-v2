"""Adopt the existing ClientFlow 1.2 Terminal domain schema.

Revision ID: 20260816_42a_terminal_v2
Revises: 20260814_41a_livestream_v2

Production already contains these reviewed tables.  Upgrade therefore creates
only missing tables (fresh installations) and leaves existing production rows
and objects untouched; the migration runner's exact head contract validates the
adopted catalog afterwards.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260816_42a_terminal_v2"
down_revision = "20260814_41a_livestream_v2"
branch_labels = None
depends_on = None


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text())


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name, schema="public")


def upgrade() -> None:
    if not _has_table("client_domain_credential"):
        op.create_table(
            "client_domain_credential",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("domain", sa.String(40), nullable=False),
            sa.Column("secret_hash", sa.Text(), nullable=False),
            sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "domain IN ('status','display','livestream','remote_desktop','terminal','system')",
                name="ck_client_domain_credential_domain",
            ),
            sa.CheckConstraint("token_version >= 0", name="ck_client_domain_credential_token_version"),
            sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="client_domain_credential_client_id_fkey"),
            sa.PrimaryKeyConstraint("id", name="client_domain_credential_pkey"),
            sa.UniqueConstraint("client_id", "domain", name="uq_client_domain_credential_client_domain"),
        )
        op.create_index("ix_client_domain_credential_active", "client_domain_credential", ["client_id", "domain", "revoked_at"])
        op.create_index("ix_client_domain_credential_client_id", "client_domain_credential", ["client_id"])
        op.create_index("ix_client_domain_credential_domain", "client_domain_credential", ["domain"])
        op.create_index("ix_client_domain_credential_last_used_at", "client_domain_credential", ["last_used_at"])
        op.create_index("ix_client_domain_credential_revoked_at", "client_domain_credential", ["revoked_at"])

    if not _has_table("client_domain_status"):
        op.create_table(
            "client_domain_status",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("domain", sa.String(40), nullable=False),
            sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
            sa.Column("observed_state", sa.String(80), server_default=sa.text("'unknown'"), nullable=False),
            sa.Column("status_payload", _jsonb(), nullable=False),
            sa.Column("agent_version", sa.String(80), nullable=True),
            sa.Column("boot_id", sa.String(128), nullable=True),
            sa.Column("credential_id", sa.String(36), nullable=False),
            sa.Column("reported_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "domain IN ('status','display','livestream','remote_desktop','terminal','system')",
                name="ck_client_domain_status_domain",
            ),
            sa.CheckConstraint("schema_version >= 1", name="ck_client_domain_status_schema_version"),
            sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="client_domain_status_client_id_fkey"),
            sa.ForeignKeyConstraint(["credential_id"], ["client_domain_credential.id"], name="client_domain_status_credential_id_fkey"),
            sa.PrimaryKeyConstraint("id", name="client_domain_status_pkey"),
            sa.UniqueConstraint("client_id", "domain", name="uq_client_domain_status_client_domain"),
        )
        op.create_index("ix_client_domain_status_client_id", "client_domain_status", ["client_id"])
        op.create_index("ix_client_domain_status_domain", "client_domain_status", ["domain"])
        op.create_index("ix_client_domain_status_reported", "client_domain_status", ["domain", "reported_at"])
        op.create_index("ix_client_domain_status_reported_at", "client_domain_status", ["reported_at"])

    if not _has_table("terminal_session"):
        op.create_table(
            "terminal_session",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
            sa.Column("privilege_level", sa.String(20), server_default=sa.text("'standard'"), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("source_ip", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("authorized_at", sa.DateTime(), nullable=False),
            sa.Column("connected_at", sa.DateTime(), nullable=True),
            sa.Column("last_activity_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("disconnected_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(30), server_default=sa.text("'authorized'"), nullable=False),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column("transcript_reference", sa.Text(), nullable=True),
            sa.Column("transcript_sha256", sa.String(64), nullable=True),
            sa.CheckConstraint("expires_at > created_at", name="ck_terminal_session_expiry_order"),
            sa.CheckConstraint("privilege_level IN ('standard','root')", name="ck_terminal_session_privilege"),
            sa.CheckConstraint(
                "privilege_level <> 'root' OR (reason IS NOT NULL AND length(trim(reason)) >= 8)",
                name="ck_terminal_session_root_reason",
            ),
            sa.CheckConstraint(
                "status IN ('requested','authorized','connected','disconnected','expired','revoked','failed')",
                name="ck_terminal_session_status",
            ),
            sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="terminal_session_client_id_fkey"),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["user.id"], name="terminal_session_requested_by_user_id_fkey"),
            sa.PrimaryKeyConstraint("id", name="terminal_session_pkey"),
        )
        op.create_index("ix_terminal_session_client_id", "terminal_session", ["client_id"])
        op.create_index("ix_terminal_session_client_status", "terminal_session", ["client_id", "status"])
        op.create_index("ix_terminal_session_expires_at", "terminal_session", ["expires_at"])
        op.create_index("ix_terminal_session_expiry", "terminal_session", ["status", "expires_at"])
        op.create_index("ix_terminal_session_requested_by_user_id", "terminal_session", ["requested_by_user_id"])
        op.create_index("ix_terminal_session_status", "terminal_session", ["status"])

    if not _has_table("root_terminal_grant"):
        op.create_table(
            "root_terminal_grant",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("terminal_session_id", sa.String(36), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("grant_hash", sa.String(64), nullable=True),
            sa.Column("step_up_verified_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("issued_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("capability", sa.String(80), server_default=sa.text("'terminal_root'"), nullable=False),
            sa.Column("issued_to_credential_id", sa.String(36), nullable=True),
            sa.CheckConstraint("capability = 'terminal_root'", name="ck_root_terminal_grant_capability"),
            sa.CheckConstraint("expires_at > created_at", name="ck_root_terminal_grant_expiry_order"),
            sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="root_terminal_grant_client_id_fkey"),
            sa.ForeignKeyConstraint(["issued_to_credential_id"], ["client_domain_credential.id"], name="root_terminal_grant_issued_to_credential_id_fkey"),
            sa.ForeignKeyConstraint(["terminal_session_id"], ["terminal_session.id"], name="root_terminal_grant_terminal_session_id_fkey"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="root_terminal_grant_user_id_fkey"),
            sa.PrimaryKeyConstraint("id", name="root_terminal_grant_pkey"),
            sa.UniqueConstraint("grant_hash", name="root_terminal_grant_grant_hash_key"),
            sa.UniqueConstraint("terminal_session_id", name="uq_root_terminal_grant_session"),
        )
        op.create_index("ix_root_terminal_grant_client_id", "root_terminal_grant", ["client_id"])
        op.create_index("ix_root_terminal_grant_consumed_at", "root_terminal_grant", ["consumed_at"])
        op.create_index("ix_root_terminal_grant_expires_at", "root_terminal_grant", ["expires_at"])
        op.create_index("ix_root_terminal_grant_revoked_at", "root_terminal_grant", ["revoked_at"])
        op.create_index("ix_root_terminal_grant_user_id", "root_terminal_grant", ["user_id"])
        op.create_index("ix_root_terminal_grant_valid", "root_terminal_grant", ["client_id", "expires_at", "consumed_at", "revoked_at"])

    if not _has_table("terminal_session_event"):
        op.create_table(
            "terminal_session_event",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("terminal_session_id", sa.String(36), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("credential_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("details", _jsonb(), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], name="terminal_session_event_actor_user_id_fkey"),
            sa.ForeignKeyConstraint(["credential_id"], ["client_domain_credential.id"], name="terminal_session_event_credential_id_fkey"),
            sa.ForeignKeyConstraint(["terminal_session_id"], ["terminal_session.id"], name="terminal_session_event_terminal_session_id_fkey"),
            sa.PrimaryKeyConstraint("id", name="terminal_session_event_pkey"),
        )
        op.create_index("ix_terminal_session_event_created_at", "terminal_session_event", ["created_at"])
        op.create_index("ix_terminal_session_event_event_type", "terminal_session_event", ["event_type"])
        op.create_index("ix_terminal_session_event_timeline", "terminal_session_event", ["terminal_session_id", "created_at"])


def downgrade() -> None:
    # This revision adopts production-owned data that predates the repository.
    # A destructive downgrade could drop live credentials/transcripts, so the
    # reviewed downgrade is intentionally non-destructive.
    pass
