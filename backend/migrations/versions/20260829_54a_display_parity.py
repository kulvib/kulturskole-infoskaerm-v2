"""54A Display operational parity: durable browser refresh authority.

Revision ID: 20260829_54a_display_parity
Revises: 20260823_53b_system_authority
"""
from alembic import op
import sqlalchemy as sa

revision = "20260829_54a_display_parity"
down_revision = "20260823_53b_system_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "display_desired_configuration",
        sa.Column("browser_refresh_interval_sec", sa.Integer(), server_default=sa.text("900"), nullable=False),
    )
    op.create_check_constraint(
        "ck_display_desired_configuration_browser_refresh_interval",
        "display_desired_configuration",
        "browser_refresh_interval_sec = 0 OR (browser_refresh_interval_sec >= 60 AND browser_refresh_interval_sec <= 86400)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_display_desired_configuration_browser_refresh_interval",
        "display_desired_configuration",
        type_="check",
    )
    op.drop_column("display_desired_configuration", "browser_refresh_interval_sec")
