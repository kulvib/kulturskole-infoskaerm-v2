"""Add ClientFlow system-time integrity telemetry.

Revision ID: 20260714_38a_time_integrity
Revises: 20260714_37a_season_contract
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260714_38a_time_integrity"
down_revision = "20260714_37a_season_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client", sa.Column("system_timezone", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("ntp_enabled", sa.Boolean(), nullable=True))
    op.add_column("client", sa.Column("ntp_synchronized", sa.Boolean(), nullable=True))
    op.add_column("client", sa.Column("client_time_utc", sa.DateTime(), nullable=True))
    op.add_column("client", sa.Column("clock_drift_seconds", sa.Float(), nullable=True))
    op.add_column(
        "client",
        sa.Column("time_sync_status", sa.Text(), nullable=True, server_default=sa.text("'unknown'::text")),
    )
    op.add_column("client", sa.Column("time_sync_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("client", "time_sync_message")
    op.drop_column("client", "time_sync_status")
    op.drop_column("client", "clock_drift_seconds")
    op.drop_column("client", "client_time_utc")
    op.drop_column("client", "ntp_synchronized")
    op.drop_column("client", "ntp_enabled")
    op.drop_column("client", "system_timezone")
