"""Persist livestream viewer leases.

Revision ID: 20260717_39a_livestream_leases
Revises: 20260714_38a_time_integrity
"""
from alembic import op
import sqlalchemy as sa

revision = "20260717_39a_livestream_leases"
down_revision = "20260714_38a_time_integrity"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "livestream_viewer_lease",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("client.id"), nullable=False),
        sa.Column("viewer_id", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("client_id", "viewer_id", name="uq_livestream_viewer_lease_client_viewer"),
    )
    op.create_index("ix_livestream_viewer_lease_expires_at", "livestream_viewer_lease", ["expires_at"])
    op.create_index("ix_livestream_viewer_lease_client_id", "livestream_viewer_lease", ["client_id"])

def downgrade() -> None:
    op.drop_index("ix_livestream_viewer_lease_client_id", table_name="livestream_viewer_lease")
    op.drop_index("ix_livestream_viewer_lease_expires_at", table_name="livestream_viewer_lease")
    op.drop_table("livestream_viewer_lease")
