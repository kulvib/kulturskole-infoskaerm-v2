"""Persist the complete ClientFlow runtime update contract.

Revision ID: 20260714_35a_runtime_contract
Revises: 20260712_34a_audit_request_id
"""
from alembic import op
import sqlalchemy as sa

revision = "20260714_35a_runtime_contract"
down_revision = "20260712_34a_audit_request_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client", sa.Column("client_version_patch", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("client_version_updated_at", sa.DateTime(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_status", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_step", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_message", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_error", sa.Text(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_started_at", sa.DateTime(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_updated_at", sa.DateTime(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_finished_at", sa.DateTime(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_progress", sa.Integer(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_package_count", sa.Integer(), nullable=True))
    op.add_column("client", sa.Column("ubuntu_update_reboot_required", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("client", "ubuntu_update_reboot_required")
    op.drop_column("client", "ubuntu_update_package_count")
    op.drop_column("client", "ubuntu_update_progress")
    op.drop_column("client", "ubuntu_update_finished_at")
    op.drop_column("client", "ubuntu_update_updated_at")
    op.drop_column("client", "ubuntu_update_started_at")
    op.drop_column("client", "ubuntu_update_error")
    op.drop_column("client", "ubuntu_update_message")
    op.drop_column("client", "ubuntu_update_step")
    op.drop_column("client", "ubuntu_update_status")
    op.drop_column("client", "client_version_updated_at")
    op.drop_column("client", "client_version_patch")
