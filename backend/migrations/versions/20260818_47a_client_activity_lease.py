"""Add shared authenticated browser activity leases.

Revision ID: 20260818_47a_client_activity
Revises: 20260817_46a_remote_desktop_v2
Create Date: 2026-08-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260818_47a_client_activity"
down_revision = "20260817_46a_remote_desktop_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_activity_lease",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "domain IN ('terminal','remote_desktop')",
            name="ck_client_activity_lease_domain",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["client.id"],
            name="client_activity_lease_client_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="client_activity_lease_pkey"),
        sa.UniqueConstraint(
            "client_id", "domain", "session_id",
            name="uq_client_activity_lease_client_domain_session",
        ),
    )
    op.create_index(
        "ix_client_activity_lease_client_id",
        "client_activity_lease",
        ["client_id"],
    )
    op.create_index(
        "ix_client_activity_lease_last_seen_at",
        "client_activity_lease",
        ["last_seen_at"],
    )
    op.create_index(
        "ix_client_activity_lease_ended_at",
        "client_activity_lease",
        ["ended_at"],
    )
    op.create_index(
        "ix_client_activity_lease_active",
        "client_activity_lease",
        ["client_id", "domain", "ended_at", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_activity_lease_active", table_name="client_activity_lease")
    op.drop_index("ix_client_activity_lease_ended_at", table_name="client_activity_lease")
    op.drop_index("ix_client_activity_lease_last_seen_at", table_name="client_activity_lease")
    op.drop_index("ix_client_activity_lease_client_id", table_name="client_activity_lease")
    op.drop_table("client_activity_lease")
