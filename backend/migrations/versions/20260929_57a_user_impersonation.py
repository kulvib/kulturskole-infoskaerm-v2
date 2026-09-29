"""57A secure administrator user switching session context.

Revision ID: 20260929_57a_impersonation
Revises: 20260922_56a_calendar_rev
"""

from alembic import op
import sqlalchemy as sa

revision = "20260929_57a_impersonation"
down_revision = "20260922_56a_calendar_rev"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("session_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_refresh_tokens_session_id",
        "refresh_tokens",
        ["session_id"],
        unique=False,
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("impersonated_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "refresh_tokens_impersonated_user_id_fkey",
        "refresh_tokens",
        "user",
        ["impersonated_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_refresh_tokens_impersonated_user_id",
        "refresh_tokens",
        ["impersonated_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_impersonated_user_id", table_name="refresh_tokens")
    op.drop_constraint(
        "refresh_tokens_impersonated_user_id_fkey",
        "refresh_tokens",
        type_="foreignkey",
    )
    op.drop_column("refresh_tokens", "impersonated_user_id")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "session_id")
