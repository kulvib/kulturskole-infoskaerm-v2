"""Add server-authoritative human-user maintenance mode.

Revision ID: 20260929_58a_maintenance
Revises: 20260929_57a_impersonation
"""

from alembic import op
import sqlalchemy as sa

revision = "20260929_58a_maintenance"
down_revision = "20260929_57a_impersonation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_state",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("expected_end_at", sa.DateTime(), nullable=True),
        sa.Column("enabled_at", sa.DateTime(), nullable=True),
        sa.Column("enabled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_maintenance_state_singleton_id"),
        sa.ForeignKeyConstraint(["enabled_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO maintenance_state (id, enabled, message) VALUES (1, false, NULL) "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("maintenance_state")
