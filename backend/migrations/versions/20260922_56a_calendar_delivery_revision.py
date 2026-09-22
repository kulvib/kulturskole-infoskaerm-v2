"""56A lightweight calendar delivery revision metadata.

Revision ID: 20260922_56a_calendar_rev
Revises: 20260908_55a_enroll_binding
"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_56a_calendar_rev"
down_revision = "20260908_55a_enroll_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable first so the migration remains safe for existing rows, then
    # backfill in one statement and enforce the model contract.  No persistent
    # DB default is retained: normal writes are owned by SQLAlchemy's
    # default/onupdate hooks on CalendarMarking.
    op.add_column(
        "calendarmarking",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        "UPDATE calendarmarking SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
    )
    op.alter_column("calendarmarking", "updated_at", nullable=False)


def downgrade() -> None:
    op.drop_column("calendarmarking", "updated_at")
