"""Canonicalize ClientFlow shared foundations and enrollment persistence.

Revision ID: 20260819_50a_canonical
Revises: 20260819_49a_db_contract
Create Date: 2026-08-19

This revision is intentionally the first canonical-v2 cleanup step. It adopts
physically observed enrollment persistence, removes the retired shared
Livestream transport rows/constraints, and drops Client columns that no active
runtime consumes.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260819_50a_canonical"
down_revision = "20260819_49a_db_contract"
branch_labels = None
depends_on = None

LEGACY_CLIENT_COLUMNS = (
    "pending_livestream_action",
    "pending_livestream_action_source",
    "livestream_control_plane_version",
    "school",
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in set(_inspector().get_table_names(schema="public"))


def _column_names(table: str) -> set[str]:
    return {str(item["name"]) for item in _inspector().get_columns(table, schema="public")}


def _require_exact_columns(table: str, expected: set[str]) -> None:
    actual = _column_names(table)
    if actual != expected:
        raise RuntimeError(
            f"{table} har uventet schema før canonical adoption: "
            f"missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )


def _ensure_enrollment_receipt() -> None:
    expected = {"install_id", "client_id", "resume_proof_hash", "created_at", "expires_at", "completed_at"}
    if not _has_table("client_enrollment_receipt"):
        op.create_table(
            "client_enrollment_receipt",
            sa.Column("install_id", sa.String(36), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("resume_proof_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("expires_at > created_at", name="ck_client_enrollment_receipt_expiry"),
            sa.ForeignKeyConstraint(
                ["client_id"], ["client.id"], name="client_enrollment_receipt_client_id_fkey"
            ),
            sa.PrimaryKeyConstraint("install_id", name="client_enrollment_receipt_pkey"),
            sa.UniqueConstraint("client_id", name="uq_client_enrollment_receipt_client"),
        )
        op.create_index("ix_client_enrollment_receipt_client_id", "client_enrollment_receipt", ["client_id"])
        op.create_index("ix_client_enrollment_receipt_completed_at", "client_enrollment_receipt", ["completed_at"])
        op.create_index("ix_client_enrollment_receipt_expires_at", "client_enrollment_receipt", ["expires_at"])
        op.create_index("ix_client_enrollment_receipt_expiry", "client_enrollment_receipt", ["expires_at", "completed_at"])
    _require_exact_columns("client_enrollment_receipt", expected)


def _ensure_system_encryption_key() -> None:
    expected = {"id", "client_id", "algorithm", "public_key_pem", "created_at", "revoked_at"}
    if not _has_table("client_system_encryption_key"):
        op.create_table(
            "client_system_encryption_key",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("algorithm", sa.String(40), nullable=False),
            sa.Column("public_key_pem", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "algorithm = 'RSA-OAEP-SHA256'",
                name="ck_client_system_encryption_key_algorithm",
            ),
            sa.ForeignKeyConstraint(
                ["client_id"], ["client.id"], name="client_system_encryption_key_client_id_fkey"
            ),
            sa.PrimaryKeyConstraint("id", name="client_system_encryption_key_pkey"),
            sa.UniqueConstraint("client_id", name="uq_client_system_encryption_key_client"),
        )
        op.create_index(
            "ix_client_system_encryption_key_active",
            "client_system_encryption_key",
            ["client_id", "revoked_at"],
        )
        op.create_index(
            "ix_client_system_encryption_key_client_id",
            "client_system_encryption_key",
            ["client_id"],
        )
        op.create_index(
            "ix_client_system_encryption_key_revoked_at",
            "client_system_encryption_key",
            ["revoked_at"],
        )
    _require_exact_columns("client_system_encryption_key", expected)


def _retire_shared_livestream() -> None:
    if not _has_table("livestream_v2_credential"):
        raise RuntimeError("livestream_v2_credential mangler; shared Livestream kan ikke pensioneres sikkert")

    missing_v2 = op.get_bind().execute(sa.text("""
        SELECT count(*)
        FROM client_domain_credential AS shared
        WHERE shared.domain = 'livestream'
          AND NOT EXISTS (
              SELECT 1
              FROM livestream_v2_credential AS isolated
              WHERE isolated.client_id = shared.client_id
                AND isolated.revoked_at IS NULL
          )
    """)).scalar_one()
    if int(missing_v2 or 0) > 0:
        raise RuntimeError(
            "Shared Livestream credentials findes uden aktiv livestream_v2_credential; "
            "canonical migration stopper uden at slette data"
        )

    # Historical shared Livestream state/commands are retired only after the
    # isolated credential presence check above has proved the active boundary.
    #
    # livestream_generation is retained as historical lifecycle data. Its
    # command_id is nullable, so detach references to retired shared commands
    # before deleting those transport rows.
    if _has_table("livestream_generation"):
        op.execute(sa.text("""
            UPDATE livestream_generation AS generation
            SET command_id = NULL
            FROM client_command AS command
            WHERE generation.command_id = command.id
              AND command.domain = 'livestream'
        """))

    op.execute(sa.text("DELETE FROM client_domain_status WHERE domain = 'livestream'"))
    op.execute(sa.text("DELETE FROM client_command WHERE domain = 'livestream'"))
    op.execute(sa.text("DELETE FROM client_domain_credential WHERE domain = 'livestream'"))

    for table, allowed in (
        ("client_domain_credential", {"status", "display", "system"}),
        ("client_domain_status", {"status", "display", "system"}),
        ("client_command", {"display", "system"}),
    ):
        rows = op.get_bind().execute(sa.text(f"SELECT DISTINCT domain FROM {table}")).scalars().all()
        unexpected = {str(item) for item in rows} - allowed
        if unexpected:
            raise RuntimeError(f"{table} indeholder uventede domains: {sorted(unexpected)}")

    op.drop_constraint("ck_client_domain_credential_domain", "client_domain_credential", type_="check")
    op.create_check_constraint(
        "ck_client_domain_credential_domain",
        "client_domain_credential",
        "domain IN ('status','display','system')",
    )
    op.drop_constraint("ck_client_domain_status_domain", "client_domain_status", type_="check")
    op.create_check_constraint(
        "ck_client_domain_status_domain",
        "client_domain_status",
        "domain IN ('status','display','system')",
    )
    op.drop_constraint("ck_client_command_domain", "client_command", type_="check")
    op.create_check_constraint(
        "ck_client_command_domain",
        "client_command",
        "domain IN ('display','system')",
    )


def _drop_retired_client_columns() -> None:
    existing = _column_names("client")
    for column in LEGACY_CLIENT_COLUMNS:
        if column in existing:
            op.drop_column("client", column)


def upgrade() -> None:
    _ensure_enrollment_receipt()
    _ensure_system_encryption_key()
    _retire_shared_livestream()
    _drop_retired_client_columns()


def downgrade() -> None:
    raise RuntimeError(
        "Canonical Step 50A fjerner retired transport state og kan ikke downgrades sikkert"
    )
