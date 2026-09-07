"""Preserve domain/session history across permanent user deletion.

Revision ID: 20260818_48a_lifecycle
Revises: 20260818_47a_client_activity
Create Date: 2026-08-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260818_48a_lifecycle"
down_revision = "20260818_47a_client_activity"
branch_labels = None
depends_on = None


_USER_REFERENCES = (
    ("terminal_session", "requested_by_user_id", "terminal_session_requested_by_user_id_fkey", True),
    ("root_terminal_grant", "user_id", "root_terminal_grant_user_id_fkey", True),
    ("terminal_session_event", "actor_user_id", "terminal_session_event_actor_user_id_fkey", False),
    ("remote_desktop_session", "requested_by_user_id", "remote_desktop_session_requested_by_user_id_fkey", True),
    ("remote_desktop_session_event", "actor_user_id", "remote_desktop_session_event_actor_user_id_fkey", False),
    ("client_command", "requested_by_user_id", "client_command_requested_by_user_id_fkey", True),
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in set(_inspector().get_table_names(schema="public"))


def _columns(table: str) -> dict[str, dict]:
    return {item["name"]: item for item in _inspector().get_columns(table, schema="public")}


def _drop_user_fk(table: str, column: str) -> None:
    for fk in _inspector().get_foreign_keys(table, schema="public"):
        if list(fk.get("constrained_columns") or []) != [column]:
            continue
        referred = str(fk.get("referred_table") or "")
        if referred != "user":
            continue
        name = fk.get("name")
        if not name:
            raise RuntimeError(f"{table}.{column} har en unavngiven user-FK; migration afbrydes")
        op.drop_constraint(name, table, type_="foreignkey")
        return


def _create_user_fk(table: str, column: str, name: str, *, ondelete: str | None) -> None:
    op.create_foreign_key(
        name,
        table,
        "user",
        [column],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    for table, column, fk_name, must_become_nullable in _USER_REFERENCES:
        if not _has_table(table):
            continue
        columns = _columns(table)
        if column not in columns:
            continue
        _drop_user_fk(table, column)
        if must_become_nullable and not bool(columns[column].get("nullable")):
            op.alter_column(table, column, existing_type=sa.Integer(), nullable=True)
        _create_user_fk(table, column, fk_name, ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    # A downgrade cannot restore NOT NULL semantics after users have actually
    # been deleted without destroying retained history. Fail closed instead.
    for table, column, _fk_name, must_become_nullable in _USER_REFERENCES:
        if not must_become_nullable or not _has_table(table) or column not in _columns(table):
            continue
        null_count = bind.execute(
            sa.text(f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NULL')
        ).scalar_one()
        if int(null_count or 0) > 0:
            raise RuntimeError(
                f"Kan ikke downgrade lifecycle-retention: {table}.{column} indeholder bevaret historik uden bruger-FK"
            )

    for table, column, fk_name, must_become_nullable in reversed(_USER_REFERENCES):
        if not _has_table(table) or column not in _columns(table):
            continue
        _drop_user_fk(table, column)
        if must_become_nullable:
            op.alter_column(table, column, existing_type=sa.Integer(), nullable=False)
        _create_user_fk(table, column, fk_name, ondelete=None)
