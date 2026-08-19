"""Remove mandatory Admin-terminal reason and harden terminal authorization policy.

Revision ID: 20260816_43a_terminal_policy
Revises: 20260816_42a_terminal_v2
Create Date: 2026-08-16

The terminal_session.reason column is intentionally retained as nullable so
historical audit data is preserved. New sessions no longer collect or require a
free-text reason. The application layer enforces superadministrator-only access
for both Bruger-terminal and Admin-terminal; Admin-terminal additionally keeps
password step-up and one-time root grants.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260816_43a_terminal_policy"
down_revision = "20260816_42a_terminal_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    check_names = {
        item.get("name")
        for item in inspector.get_check_constraints("terminal_session")
        if item.get("name")
    }
    if "ck_terminal_session_root_reason" in check_names:
        op.drop_constraint(
            "ck_terminal_session_root_reason",
            "terminal_session",
            type_="check",
        )


def downgrade() -> None:
    # Re-introducing the old mandatory-reason constraint could reject valid
    # root sessions created under this revision. Fail closed rather than mutate
    # or fabricate historical audit data during a downgrade.
    raise RuntimeError(
        "Terminal policy downgrade er bevidst blokeret: obligatorisk root-begrundelse kan ikke genskabes sikkert"
    )
