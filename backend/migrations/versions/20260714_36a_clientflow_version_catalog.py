"""Add ClientFlow version-catalog deployment fields.

Revision ID: 20260714_36a_clientflow_catalog
Revises: 20260714_35a_runtime_contract
"""
from alembic import op
import sqlalchemy as sa

revision = "20260714_36a_clientflow_catalog"
down_revision = "20260714_35a_runtime_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client", sa.Column("client_update_target_version", sa.Text(), nullable=True, server_default="latest"))
    op.add_column("client", sa.Column("client_update_target_release_sequence", sa.Integer(), nullable=True))
    op.add_column("client", sa.Column("client_update_deployment_sequence", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("client", sa.Column("client_update_applied_deployment_sequence", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("client", sa.Column("client_update_allow_downgrade", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("client", sa.Column("client_update_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("client", "client_update_reason")
    op.drop_column("client", "client_update_allow_downgrade")
    op.drop_column("client", "client_update_applied_deployment_sequence")
    op.drop_column("client", "client_update_deployment_sequence")
    op.drop_column("client", "client_update_target_release_sequence")
    op.drop_column("client", "client_update_target_version")
