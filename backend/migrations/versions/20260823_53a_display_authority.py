"""53A canonical Display desired-state authority.

Revision ID: 20260823_53a_display_authority
Revises: 20260822_52a_client_liveness
"""
from alembic import op
import sqlalchemy as sa
from urllib.parse import urlsplit

revision = "20260823_53a_display_authority"
down_revision = "20260822_52a_client_liveness"
branch_labels = None
depends_on = None



def _legacy_kiosk_url_is_canonical(value: object) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    if len(raw) > 2048:
        return False
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() == "https":
        return bool(host and parsed.netloc)
    return parsed.scheme.lower() == "http" and host in {"localhost", "127.0.0.1"}


def _require_legacy_kiosk_urls_canonical() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, kiosk_url FROM client WHERE kiosk_url IS NOT NULL AND btrim(kiosk_url) <> ''")
    ).mappings()
    invalid_ids = [int(row["id"]) for row in rows if not _legacy_kiosk_url_is_canonical(row["kiosk_url"])]
    if invalid_ids:
        sample = ", ".join(str(value) for value in invalid_ids[:20])
        suffix = "..." if len(invalid_ids) > 20 else ""
        raise RuntimeError(
            "53A kan ikke migrere ugyldige legacy kiosk_url-værdier; ret dem før migration. "
            f"client_id={sample}{suffix}"
        )

def upgrade() -> None:
    _require_legacy_kiosk_urls_canonical()
    op.create_table(
        "display_desired_configuration",
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("kiosk_url", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("revision >= 1", name="ck_display_desired_configuration_revision"),
        sa.CheckConstraint("schema_version = 1", name="ck_display_desired_configuration_schema_version"),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_index(
        "ix_display_desired_configuration_updated_at",
        "display_desired_configuration",
        ["updated_at"],
        unique=False,
    )

    # Preserve any existing kiosk intent once, then retire Client.kiosk_url as
    # an authority.  Empty legacy values deliberately do not create desired state.
    op.execute(
        sa.text(
            """
            INSERT INTO display_desired_configuration
                (client_id, schema_version, revision, kiosk_url, updated_at, updated_by_user_id)
            SELECT id, 1, 1, btrim(kiosk_url), COALESCE(created_at, CURRENT_TIMESTAMP), NULL
            FROM client
            WHERE kiosk_url IS NOT NULL AND btrim(kiosk_url) <> ''
            """
        )
    )
    op.drop_column("client", "browser_refresh_interval_sec")
    op.drop_column("client", "kiosk_url")


def downgrade() -> None:
    op.add_column("client", sa.Column("kiosk_url", sa.String(), nullable=True))
    op.add_column(
        "client",
        sa.Column("browser_refresh_interval_sec", sa.Integer(), server_default=sa.text("900"), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE client AS c
            SET kiosk_url = d.kiosk_url
            FROM display_desired_configuration AS d
            WHERE d.client_id = c.id
            """
        )
    )
    op.drop_index("ix_display_desired_configuration_updated_at", table_name="display_desired_configuration")
    op.drop_table("display_desired_configuration")
