"""Isolate livestream command mailbox and persist canonical lifecycle status.

Revision ID: 20260814_40a_livestream_control
Revises: 20260717_39a_livestream_leases
"""
from alembic import op
import sqlalchemy as sa

revision = "20260814_40a_livestream_control"
down_revision = "20260717_39a_livestream_leases"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("client", sa.Column("pending_livestream_action", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("pending_livestream_action_source", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("livestream_stop_reason", sa.Text(), nullable=True))
    op.add_column(
        "client",
        sa.Column("livestream_control_plane_version", sa.Integer(), nullable=True, server_default=sa.text("1")),
    )


def downgrade():
    op.drop_column("client", "livestream_control_plane_version")
    op.drop_column("client", "livestream_stop_reason")
    op.drop_column("client", "pending_livestream_action_source")
    op.drop_column("client", "pending_livestream_action")
