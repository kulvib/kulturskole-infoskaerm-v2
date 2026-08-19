"""Isolate Remote Desktop client identity, credentials and status.

Revision ID: 20260817_46a_remote_desktop_v2
Revises: 20260816_45a_terminal_client
Create Date: 2026-08-17

The live installation already owns a Remote Desktop credential and legacy
session/event tables. This migration preserves deployed credential IDs and
secret hashes, re-homes Remote Desktop-owned foreign keys, and removes the
Remote Desktop rows from the shared domain credential/status tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260817_46a_remote_desktop_v2"
down_revision = "20260816_45a_terminal_client"
branch_labels = None
depends_on = None


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text())


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name, schema="public")


def _fk_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {str(item.get("name")) for item in _inspector().get_foreign_keys(table, schema="public") if item.get("name")}


def _scalar(sql: str) -> int:
    value = op.get_bind().execute(sa.text(sql)).scalar_one()
    return int(value or 0)


def upgrade() -> None:
    # Fail closed if the live legacy catalog contains cross-domain references
    # that cannot be losslessly re-homed. The reviewed client 23 credential
    # migrates 1:1; these guards protect other production rows as well.
    if _has_table("remote_desktop_session_event"):
        bad_event_credentials = _scalar("""
            SELECT count(*)
            FROM remote_desktop_session_event AS e
            JOIN client_domain_credential AS c ON c.id = e.credential_id
            WHERE e.credential_id IS NOT NULL
              AND c.domain <> 'remote_desktop'
        """)
        if bad_event_credentials:
            raise RuntimeError(
                "remote_desktop_session_event indeholder credential-referencer til andre domæner; migration afbrydes"
            )

    bad_status_credentials = _scalar("""
        SELECT count(*)
        FROM client_domain_status AS s
        JOIN client_domain_credential AS c ON c.id = s.credential_id
        WHERE s.domain = 'remote_desktop'
          AND c.domain <> 'remote_desktop'
    """)
    if bad_status_credentials:
        raise RuntimeError(
            "Remote Desktop-status refererer til credential fra et andet domæne; migration afbrydes"
        )

    if _has_table("client_command"):
        historical_claims = _scalar("""
            SELECT count(*)
            FROM client_command AS cc
            JOIN client_domain_credential AS c ON c.id = cc.claimed_by_credential_id
            WHERE c.domain = 'remote_desktop'
        """)
        if historical_claims:
            raise RuntimeError(
                "client_command har historiske Remote Desktop credential-claims; migrér auditsporet eksplicit før RD-isolation"
            )

    op.create_table(
        "remote_desktop_client",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), server_default=sa.text("'approved'"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('approved','disabled')", name="ck_remote_desktop_client_status"),
        sa.PrimaryKeyConstraint("id", name="remote_desktop_client_pkey"),
    )
    op.create_index("ix_remote_desktop_client_status", "remote_desktop_client", ["status"])

    # Seed every client that already owns Remote Desktop state. Existing IDs
    # remain stable so deployed seq-1200 credentials need no re-enrollment.
    op.execute(sa.text("""
        INSERT INTO remote_desktop_client (id, display_name, status, created_at)
        SELECT DISTINCT
            c.id,
            c.name,
            CASE WHEN lower(coalesce(c.status, '')) = 'approved' THEN 'approved' ELSE 'disabled' END,
            coalesce(c.created_at, CURRENT_TIMESTAMP)
        FROM client AS c
        JOIN (
            SELECT client_id FROM client_domain_credential WHERE domain = 'remote_desktop'
            UNION
            SELECT client_id FROM client_domain_status WHERE domain = 'remote_desktop'
        ) AS rd ON rd.client_id = c.id
        ON CONFLICT (id) DO NOTHING
    """))
    if _has_table("remote_desktop_session"):
        op.execute(sa.text("""
            INSERT INTO remote_desktop_client (id, display_name, status, created_at)
            SELECT DISTINCT
                c.id,
                c.name,
                CASE WHEN lower(coalesce(c.status, '')) = 'approved' THEN 'approved' ELSE 'disabled' END,
                coalesce(c.created_at, CURRENT_TIMESTAMP)
            FROM client AS c
            JOIN remote_desktop_session AS rds ON rds.client_id = c.id
            ON CONFLICT (id) DO NOTHING
        """))

    op.create_table(
        "remote_desktop_credential",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("token_version >= 0", name="ck_remote_desktop_credential_token_version"),
        sa.ForeignKeyConstraint(["client_id"], ["remote_desktop_client.id"], name="remote_desktop_credential_client_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="remote_desktop_credential_pkey"),
        sa.UniqueConstraint("client_id", name="uq_remote_desktop_credential_client"),
    )
    op.create_index("ix_remote_desktop_credential_active", "remote_desktop_credential", ["client_id", "revoked_at"])
    op.create_index("ix_remote_desktop_credential_last_used_at", "remote_desktop_credential", ["last_used_at"])
    op.create_index("ix_remote_desktop_credential_revoked_at", "remote_desktop_credential", ["revoked_at"])
    op.execute(sa.text("""
        INSERT INTO remote_desktop_credential (
            id, client_id, secret_hash, token_version,
            created_at, last_used_at, revoked_at
        )
        SELECT
            id, client_id, secret_hash, token_version,
            created_at, last_used_at, revoked_at
        FROM client_domain_credential
        WHERE domain = 'remote_desktop'
    """))

    op.create_table(
        "remote_desktop_agent_status",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("observed_state", sa.String(80), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("status_payload", _jsonb(), nullable=False),
        sa.Column("agent_version", sa.String(80), nullable=True),
        sa.Column("boot_id", sa.String(128), nullable=True),
        sa.Column("credential_id", sa.String(36), nullable=False),
        sa.Column("reported_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("schema_version >= 1", name="ck_remote_desktop_agent_status_schema_version"),
        sa.ForeignKeyConstraint(["client_id"], ["remote_desktop_client.id"], name="remote_desktop_agent_status_client_id_fkey"),
        sa.ForeignKeyConstraint(["credential_id"], ["remote_desktop_credential.id"], name="remote_desktop_agent_status_credential_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="remote_desktop_agent_status_pkey"),
        sa.UniqueConstraint("client_id", name="uq_remote_desktop_agent_status_client"),
    )
    op.create_index("ix_remote_desktop_agent_status_reported_at", "remote_desktop_agent_status", ["reported_at"])
    op.execute(sa.text("""
        INSERT INTO remote_desktop_agent_status (
            id, client_id, schema_version, observed_state, status_payload,
            agent_version, boot_id, credential_id, reported_at
        )
        SELECT
            s.id, s.client_id, s.schema_version, s.observed_state, s.status_payload,
            s.agent_version, s.boot_id, s.credential_id, s.reported_at
        FROM client_domain_status AS s
        JOIN client_domain_credential AS c ON c.id = s.credential_id
        WHERE s.domain = 'remote_desktop' AND c.domain = 'remote_desktop'
    """))

    if not _has_table("remote_desktop_session"):
        op.create_table(
            "remote_desktop_session",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
            sa.Column("source_ip", sa.String(255), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("connected_at", sa.DateTime(), nullable=True),
            sa.Column("last_activity_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("disconnected_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(30), server_default=sa.text("'authorized'"), nullable=False),
            sa.Column("close_reason", sa.Text(), nullable=True),
            sa.CheckConstraint("expires_at > created_at", name="ck_remote_desktop_session_expiry_order"),
            sa.CheckConstraint(
                "status IN ('requested','authorized','connected','disconnected','expired','revoked','failed')",
                name="ck_remote_desktop_session_status",
            ),
            sa.ForeignKeyConstraint(["client_id"], ["remote_desktop_client.id"], name="remote_desktop_session_client_id_fkey"),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["user.id"], name="remote_desktop_session_requested_by_user_id_fkey"),
            sa.PrimaryKeyConstraint("id", name="remote_desktop_session_pkey"),
        )
    else:
        names = _fk_names("remote_desktop_session")
        if "remote_desktop_session_client_id_fkey" in names:
            op.drop_constraint("remote_desktop_session_client_id_fkey", "remote_desktop_session", type_="foreignkey")
        op.create_foreign_key(
            "remote_desktop_session_client_id_fkey",
            "remote_desktop_session",
            "remote_desktop_client",
            ["client_id"],
            ["id"],
        )
    for name, cols in (
        ("ix_remote_desktop_session_client_id", ["client_id"]),
        ("ix_remote_desktop_session_client_status", ["client_id", "status"]),
        ("ix_remote_desktop_session_expires_at", ["expires_at"]),
        ("ix_remote_desktop_session_status", ["status"]),
    ):
        existing = {idx.get("name") for idx in _inspector().get_indexes("remote_desktop_session", schema="public")}
        if name not in existing:
            op.create_index(name, "remote_desktop_session", cols)

    if not _has_table("remote_desktop_session_event"):
        op.create_table(
            "remote_desktop_session_event",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("remote_desktop_session_id", sa.String(36), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("credential_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("details", _jsonb(), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], name="remote_desktop_session_event_actor_user_id_fkey"),
            sa.ForeignKeyConstraint(["credential_id"], ["remote_desktop_credential.id"], name="remote_desktop_session_event_credential_id_fkey"),
            sa.ForeignKeyConstraint(["remote_desktop_session_id"], ["remote_desktop_session.id"], name="remote_desktop_session_event_remote_desktop_session_id_fkey"),
            sa.PrimaryKeyConstraint("id", name="remote_desktop_session_event_pkey"),
        )
    else:
        names = _fk_names("remote_desktop_session_event")
        if "remote_desktop_session_event_credential_id_fkey" in names:
            op.drop_constraint("remote_desktop_session_event_credential_id_fkey", "remote_desktop_session_event", type_="foreignkey")
        op.create_foreign_key(
            "remote_desktop_session_event_credential_id_fkey",
            "remote_desktop_session_event",
            "remote_desktop_credential",
            ["credential_id"],
            ["id"],
        )
    for name, cols in (
        ("ix_remote_desktop_session_event_created_at", ["created_at"]),
        ("ix_remote_desktop_session_event_event_type", ["event_type"]),
        ("ix_remote_desktop_session_event_timeline", ["remote_desktop_session_id", "created_at"]),
    ):
        existing = {idx.get("name") for idx in _inspector().get_indexes("remote_desktop_session_event", schema="public")}
        if name not in existing:
            op.create_index(name, "remote_desktop_session_event", cols)

    op.execute(sa.text("DELETE FROM client_domain_status WHERE domain = 'remote_desktop'"))
    op.execute(sa.text("DELETE FROM client_domain_credential WHERE domain = 'remote_desktop'"))


def downgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO client_domain_credential (
            id, client_id, domain, secret_hash, token_version,
            created_at, last_used_at, revoked_at
        )
        SELECT
            id, client_id, 'remote_desktop', secret_hash, token_version,
            created_at, last_used_at, revoked_at
        FROM remote_desktop_credential
        ON CONFLICT (id) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO client_domain_status (
            id, client_id, domain, schema_version, observed_state, status_payload,
            agent_version, boot_id, credential_id, reported_at
        )
        SELECT
            id, client_id, 'remote_desktop', schema_version, observed_state, status_payload,
            agent_version, boot_id, credential_id, reported_at
        FROM remote_desktop_agent_status
        ON CONFLICT (id) DO NOTHING
    """))

    if _has_table("remote_desktop_session_event"):
        names = _fk_names("remote_desktop_session_event")
        if "remote_desktop_session_event_credential_id_fkey" in names:
            op.drop_constraint("remote_desktop_session_event_credential_id_fkey", "remote_desktop_session_event", type_="foreignkey")
        op.create_foreign_key(
            "remote_desktop_session_event_credential_id_fkey",
            "remote_desktop_session_event",
            "client_domain_credential",
            ["credential_id"],
            ["id"],
        )
    if _has_table("remote_desktop_session"):
        names = _fk_names("remote_desktop_session")
        if "remote_desktop_session_client_id_fkey" in names:
            op.drop_constraint("remote_desktop_session_client_id_fkey", "remote_desktop_session", type_="foreignkey")
        op.create_foreign_key(
            "remote_desktop_session_client_id_fkey",
            "remote_desktop_session",
            "client",
            ["client_id"],
            ["id"],
        )

    op.drop_index("ix_remote_desktop_agent_status_reported_at", table_name="remote_desktop_agent_status")
    op.drop_table("remote_desktop_agent_status")
    op.drop_index("ix_remote_desktop_credential_revoked_at", table_name="remote_desktop_credential")
    op.drop_index("ix_remote_desktop_credential_last_used_at", table_name="remote_desktop_credential")
    op.drop_index("ix_remote_desktop_credential_active", table_name="remote_desktop_credential")
    op.drop_table("remote_desktop_credential")
    op.drop_index("ix_remote_desktop_client_status", table_name="remote_desktop_client")
    op.drop_table("remote_desktop_client")
