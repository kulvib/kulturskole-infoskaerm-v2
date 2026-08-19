"""Remove retired runtime compatibility columns.

Revision ID: 20260819_50a_remove_runtime_legacy
Revises: 20260819_49a_db_contract
Create Date: 2026-08-19

The application no longer exposes the Livestream v1 mailbox/control-plane
switch and no longer models the unused ``client.school`` compatibility column.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260819_50a_remove_runtime_legacy"
down_revision = "20260819_49a_db_contract"
branch_labels = None
depends_on = None

COLUMNS = (
    "pending_livestream_action",
    "pending_livestream_action_source",
    "livestream_control_plane_version",
    "school",
)


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {str(item["name"]) for item in inspector.get_columns("client", schema="public")}


def upgrade() -> None:
    existing = _columns()
    for column in COLUMNS:
        if column in existing:
            op.drop_column("client", column)


def downgrade() -> None:
    # The retired columns carried ambiguous v1 compatibility state and are not
    # reconstructed. Restoring them would reintroduce a transport contract the
    # canonical runtime intentionally removed.
    raise RuntimeError("Canonical legacy-column removal is intentionally irreversible")
