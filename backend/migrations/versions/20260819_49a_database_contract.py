"""Adopt active legacy-origin runtime tables into the exact head contract.

Revision ID: 20260819_49a_db_contract
Revises: 20260818_48a_lifecycle
Create Date: 2026-08-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260819_49a_db_contract"
down_revision = "20260818_48a_lifecycle"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in set(_inspector().get_table_names(schema="public"))


def _index_names(table: str) -> set[str]:
    return {
        str(item.get("name"))
        for item in _inspector().get_indexes(table, schema="public")
        if item.get("name")
    }


def _varchar_length(table: str, column: str) -> int | None:
    for item in _inspector().get_columns(table, schema="public"):
        if item.get("name") != column:
            continue
        return getattr(item.get("type"), "length", None)
    raise RuntimeError(f"{table}.{column} mangler")


def _create_client_command() -> None:
    op.create_table(
        "client_command",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("command_type", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_encryption_key_id", sa.String(120), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(30), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("claim_token_hash", sa.String(64), nullable=True),
        sa.Column("claimed_by_credential_id", sa.String(36), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_client_command_attempt_nonnegative"),
        sa.CheckConstraint(
            "domain IN ('display','livestream','system')",
            name="ck_client_command_domain",
        ),
        sa.CheckConstraint("expires_at > requested_at", name="ck_client_command_expiry_order"),
        sa.CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 10",
            name="ck_client_command_max_attempts",
        ),
        sa.CheckConstraint("schema_version >= 1", name="ck_client_command_schema_version"),
        sa.CheckConstraint(
            "status IN ('queued','claimed','succeeded','failed','expired','cancelled')",
            name="ck_client_command_status",
        ),
        sa.ForeignKeyConstraint(
            ["claimed_by_credential_id"],
            ["client_domain_credential.id"],
            name="client_command_claimed_by_credential_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["client.id"],
            name="client_command_client_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["user.id"],
            name="client_command_requested_by_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="client_command_pkey"),
        sa.UniqueConstraint(
            "client_id",
            "domain",
            "idempotency_key",
            name="uq_client_command_idempotency",
        ),
    )
    for name, columns in (
        ("ix_client_command_available_at", ["available_at"]),
        ("ix_client_command_claim", ["client_id", "domain", "status", "available_at", "expires_at"]),
        ("ix_client_command_client_id", ["client_id"]),
        ("ix_client_command_domain", ["domain"]),
        ("ix_client_command_expires_at", ["expires_at"]),
        ("ix_client_command_lease", ["status", "lease_expires_at"]),
        ("ix_client_command_lease_expires_at", ["lease_expires_at"]),
        ("ix_client_command_requested_by_user_id", ["requested_by_user_id"]),
        ("ix_client_command_status", ["status"]),
    ):
        op.create_index(name, "client_command", columns)


def _normalise_remote_desktop_session() -> None:
    if not _has_table("remote_desktop_session"):
        raise RuntimeError(
            "remote_desktop_session mangler ved Step 49A; Step 46A skulle have etableret tabellen"
        )

    source_ip_length = _varchar_length("remote_desktop_session", "source_ip")
    if source_ip_length == 255:
        too_long = op.get_bind().execute(
            sa.text(
                "SELECT count(*) FROM remote_desktop_session "
                "WHERE source_ip IS NOT NULL AND char_length(source_ip) > 64"
            )
        ).scalar_one()
        if int(too_long or 0) > 0:
            raise RuntimeError(
                "remote_desktop_session.source_ip kan ikke normaliseres til VARCHAR(64): "
                f"{int(too_long)} eksisterende rækker er længere end 64 tegn"
            )
        op.alter_column(
            "remote_desktop_session",
            "source_ip",
            existing_type=sa.String(255),
            type_=sa.String(64),
            existing_nullable=True,
        )
    elif source_ip_length != 64:
        raise RuntimeError(
            "Uventet remote_desktop_session.source_ip-længde; "
            f"forventede reviewed 64 eller fresh-Step-46A 255, fik {source_ip_length!r}"
        )

    existing = _index_names("remote_desktop_session")
    if "ix_remote_desktop_session_expiry" not in existing:
        op.create_index(
            "ix_remote_desktop_session_expiry",
            "remote_desktop_session",
            ["status", "expires_at"],
        )
    if "ix_remote_desktop_session_requested_by_user_id" not in existing:
        op.create_index(
            "ix_remote_desktop_session_requested_by_user_id",
            "remote_desktop_session",
            ["requested_by_user_id"],
        )


def upgrade() -> None:
    # Shared credentials/status already have reviewed migrations (Step 42A).
    # client_command did not: create it only on a database where it is absent.
    # Existing production copies are left untouched and are verified exactly by
    # the runner after this migration.
    if not _has_table("client_command"):
        _create_client_command()

    # Step 46A's fresh-create shape used VARCHAR(255) and omitted two indexes,
    # while the physically verified production table uses VARCHAR(64) and both
    # indexes.  Normalise only that known fresh-path delta; any third shape
    # fails closed.
    _normalise_remote_desktop_session()


def downgrade() -> None:
    # Step 49A adopts tables that may predate Alembic. A downgrade cannot know
    # whether client_command or the RD indexes existed before this revision, so
    # deleting/widening them would mutate historical production state. Fail
    # closed rather than guess.
    raise RuntimeError(
        "Step 49A database-contract adoption kan ikke downgrades sikkert uden at skelne pre-existing legacy storage"
    )
