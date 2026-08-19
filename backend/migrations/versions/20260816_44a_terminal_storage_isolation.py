"""Move Terminal credential/status state out of shared domain tables.

Revision ID: 20260816_44a_terminal_store
Revises: 20260816_43a_terminal_policy
Create Date: 2026-08-16

Terminal keeps the existing backend and PostgreSQL database, but owns separate
credential/status tables. Existing Terminal credential IDs, password hashes,
token versions and status rows are preserved so deployed seq-1200 clients do
not need reprovisioning.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260816_44a_terminal_store"
down_revision = "20260816_43a_terminal_policy"
branch_labels = None
depends_on = None


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "terminal_credential",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("token_version >= 0", name="ck_terminal_credential_token_version"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="terminal_credential_client_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="terminal_credential_pkey"),
        sa.UniqueConstraint("client_id", name="uq_terminal_credential_client"),
    )
    op.create_index("ix_terminal_credential_active", "terminal_credential", ["client_id", "revoked_at"])
    op.create_index("ix_terminal_credential_last_used_at", "terminal_credential", ["last_used_at"])
    op.create_index("ix_terminal_credential_revoked_at", "terminal_credential", ["revoked_at"])

    op.execute(sa.text("""
        INSERT INTO terminal_credential (
            id, client_id, secret_hash, token_version,
            created_at, last_used_at, revoked_at
        )
        SELECT
            id, client_id, secret_hash, token_version,
            created_at, last_used_at, revoked_at
        FROM client_domain_credential
        WHERE domain = 'terminal'
    """))

    op.create_table(
        "terminal_agent_status",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("observed_state", sa.String(80), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("status_payload", _jsonb(), nullable=False),
        sa.Column("agent_version", sa.String(80), nullable=True),
        sa.Column("boot_id", sa.String(128), nullable=True),
        sa.Column("credential_id", sa.String(36), nullable=False),
        sa.Column("reported_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("schema_version >= 1", name="ck_terminal_agent_status_schema_version"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], name="terminal_agent_status_client_id_fkey"),
        sa.ForeignKeyConstraint(["credential_id"], ["terminal_credential.id"], name="terminal_agent_status_credential_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="terminal_agent_status_pkey"),
        sa.UniqueConstraint("client_id", name="uq_terminal_agent_status_client"),
    )
    op.create_index("ix_terminal_agent_status_reported_at", "terminal_agent_status", ["reported_at"])

    op.execute(sa.text("""
        INSERT INTO terminal_agent_status (
            id, client_id, schema_version, observed_state, status_payload,
            agent_version, boot_id, credential_id, reported_at
        )
        SELECT
            s.id, s.client_id, s.schema_version, s.observed_state, s.status_payload,
            s.agent_version, s.boot_id, s.credential_id, s.reported_at
        FROM client_domain_status AS s
        JOIN client_domain_credential AS c ON c.id = s.credential_id
        WHERE s.domain = 'terminal' AND c.domain = 'terminal'
    """))

    # Re-home existing Terminal-owned audit/grant references before deleting the
    # legacy shared Terminal credential row.
    op.drop_constraint(
        "root_terminal_grant_issued_to_credential_id_fkey",
        "root_terminal_grant",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "root_terminal_grant_issued_to_credential_id_fkey",
        "root_terminal_grant",
        "terminal_credential",
        ["issued_to_credential_id"],
        ["id"],
    )
    op.drop_constraint(
        "terminal_session_event_credential_id_fkey",
        "terminal_session_event",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "terminal_session_event_credential_id_fkey",
        "terminal_session_event",
        "terminal_credential",
        ["credential_id"],
        ["id"],
    )

    op.execute(sa.text("DELETE FROM client_domain_status WHERE domain = 'terminal'"))
    op.execute(sa.text("DELETE FROM client_domain_credential WHERE domain = 'terminal'"))


def downgrade() -> None:
    # Restore the legacy shared rows before moving FKs back. This preserves the
    # credential IDs and hashes if a rollback is explicitly required.
    op.execute(sa.text("""
        INSERT INTO client_domain_credential (
            id, client_id, domain, secret_hash, token_version,
            created_at, last_used_at, revoked_at
        )
        SELECT
            id, client_id, 'terminal', secret_hash, token_version,
            created_at, last_used_at, revoked_at
        FROM terminal_credential
        ON CONFLICT (id) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO client_domain_status (
            id, client_id, domain, schema_version, observed_state, status_payload,
            agent_version, boot_id, credential_id, reported_at
        )
        SELECT
            id, client_id, 'terminal', schema_version, observed_state, status_payload,
            agent_version, boot_id, credential_id, reported_at
        FROM terminal_agent_status
        ON CONFLICT (id) DO NOTHING
    """))

    op.drop_constraint(
        "terminal_session_event_credential_id_fkey",
        "terminal_session_event",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "terminal_session_event_credential_id_fkey",
        "terminal_session_event",
        "client_domain_credential",
        ["credential_id"],
        ["id"],
    )
    op.drop_constraint(
        "root_terminal_grant_issued_to_credential_id_fkey",
        "root_terminal_grant",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "root_terminal_grant_issued_to_credential_id_fkey",
        "root_terminal_grant",
        "client_domain_credential",
        ["issued_to_credential_id"],
        ["id"],
    )

    op.drop_index("ix_terminal_agent_status_reported_at", table_name="terminal_agent_status")
    op.drop_table("terminal_agent_status")
    op.drop_index("ix_terminal_credential_revoked_at", table_name="terminal_credential")
    op.drop_index("ix_terminal_credential_last_used_at", table_name="terminal_credential")
    op.drop_index("ix_terminal_credential_active", table_name="terminal_credential")
    op.drop_table("terminal_credential")
