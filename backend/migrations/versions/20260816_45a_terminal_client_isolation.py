"""Move Terminal client identity off the shared client table.

Revision ID: 20260816_45a_terminal_client
Revises: 20260816_44a_terminal_store
Create Date: 2026-08-16

Terminal keeps the same backend process and PostgreSQL database, but all
Terminal-owned rows now reference terminal_client instead of the shared client
table. Existing Terminal client IDs are preserved so deployed clients do not
need reprovisioning.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260816_45a_terminal_client"
down_revision = "20260816_44a_terminal_store"
branch_labels = None
depends_on = None


_TERMINAL_CLIENT_FKS = (
    ("terminal_credential", "terminal_credential_client_id_fkey"),
    ("terminal_agent_status", "terminal_agent_status_client_id_fkey"),
    ("root_terminal_grant", "root_terminal_grant_client_id_fkey"),
    ("terminal_session", "terminal_session_client_id_fkey"),
)


def upgrade() -> None:
    op.create_table(
        "terminal_client",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), server_default=sa.text("'approved'"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('approved','disabled')", name="ck_terminal_client_status"),
        sa.PrimaryKeyConstraint("id", name="terminal_client_pkey"),
    )
    op.create_index("ix_terminal_client_status", "terminal_client", ["status"])

    # Existing client FKs guarantee these client IDs currently exist. Copy only
    # clients that already own Terminal state. The new table becomes the sole
    # client identity source for Terminal after the FK switch below.
    op.execute(sa.text("""
        INSERT INTO terminal_client (id, display_name, status, created_at)
        SELECT
            c.id,
            c.name,
            CASE WHEN lower(coalesce(c.status, '')) = 'approved' THEN 'approved' ELSE 'disabled' END,
            coalesce(c.created_at, CURRENT_TIMESTAMP)
        FROM client AS c
        JOIN (
            SELECT client_id FROM terminal_credential
            UNION
            SELECT client_id FROM terminal_agent_status
            UNION
            SELECT client_id FROM root_terminal_grant
            UNION
            SELECT client_id FROM terminal_session
        ) AS terminal_ids ON terminal_ids.client_id = c.id
        ON CONFLICT (id) DO NOTHING
    """))

    for table_name, constraint_name in _TERMINAL_CLIENT_FKS:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            "terminal_client",
            ["client_id"],
            ["id"],
        )


def downgrade() -> None:
    for table_name, constraint_name in reversed(_TERMINAL_CLIENT_FKS):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table_name,
            "client",
            ["client_id"],
            ["id"],
        )

    op.drop_index("ix_terminal_client_status", table_name="terminal_client")
    op.drop_table("terminal_client")
