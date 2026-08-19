"""Add request-id correlation to audit logs.

Revision ID: 20260712_34a_audit_request_id
Revises: 20260712_30d_display_base
"""
from alembic import op
import sqlalchemy as sa

revision = "20260712_34a_audit_request_id"
down_revision = "20260712_30d_display_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_column("audit_logs", "request_id")
