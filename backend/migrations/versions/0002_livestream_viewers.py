"""Viewer-owned Livestream lifecycle.

Revision ID: 0002_livestream_viewers
Revises: 0001_fresh_livestream
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_livestream_viewers"
down_revision = "0001_fresh_livestream"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "livestream_viewer",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(32), nullable=True),
    )
    op.create_index("ix_livestream_viewer_client_id", "livestream_viewer", ["client_id"])
    op.create_index("ix_livestream_viewer_user_id", "livestream_viewer", ["user_id"])
    op.create_index("ix_livestream_viewer_last_seen_at", "livestream_viewer", ["last_seen_at"])
    op.create_index("ix_livestream_viewer_ended_at", "livestream_viewer", ["ended_at"])
    op.create_index(
        "ix_livestream_viewer_client_active",
        "livestream_viewer",
        ["client_id", "ended_at", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_table("livestream_viewer")
