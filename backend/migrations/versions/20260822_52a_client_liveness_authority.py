"""Retire legacy Client liveness columns.

Revision ID: 20260822_52a_client_liveness
Revises: 20260820_51b_update_auth
Create Date: 2026-08-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260822_52a_client_liveness"
down_revision = "20260820_51b_update_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ClientDomainStatus(domain='status') is the sole canonical liveness
    # authority. These legacy columns have multiple unrelated writers and must
    # not remain as parallel runtime state.
    op.drop_column("client", "last_seen")
    op.drop_column("client", "isOnline")


def downgrade() -> None:
    op.add_column("client", sa.Column("isOnline", sa.Boolean(), server_default=sa.text("false"), nullable=True))
    op.add_column("client", sa.Column("last_seen", sa.DateTime(timezone=False), nullable=True))
