"""53B canonical System command authority.

Revision ID: 20260823_53b_system_authority
Revises: 20260823_53a_display_authority
"""
from alembic import op
import sqlalchemy as sa

revision = "20260823_53b_system_authority"
down_revision = "20260823_53a_display_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Neutralize non-authoritative legacy System mailbox/runtime state before
    # the write paths are retired. Current canonical clients do not consume
    # these fields, so keeping a stale value would only mislead old UI reads.
    op.execute(
        sa.text(
            """
            UPDATE client
            SET state = 'normal'
            WHERE state IN ('rebooting', 'shutdown')
               OR (
                    state = 'updating'
                    AND (COALESCE(pending_os_update, false) OR pending_chrome_action = 'os_update')
               )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE client
            SET pending_reboot = false,
                pending_shutdown = false,
                pending_os_update = false,
                pending_chrome_action = CASE
                    WHEN pending_chrome_action IN ('shutdown', 'os_update') THEN 'none'
                    ELSE pending_chrome_action
                END,
                pending_chrome_action_source = CASE
                    WHEN pending_chrome_action IN ('shutdown', 'os_update') THEN NULL
                    ELSE pending_chrome_action_source
                END
            """
        )
    )

    # Password commands are encrypted into ClientCommand(domain='system')
    # before persistence. Drop the legacy plaintext-capable column entirely.
    op.drop_column("client", "local_management_secret")


def downgrade() -> None:
    # Downgrade restores only the shape, never historical secret values.
    op.add_column("client", sa.Column("local_management_secret", sa.Text(), nullable=True))
