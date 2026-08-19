from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from service1.models import SQLModel
import service1.livestream_v2_models  # noqa: F401 - registers isolated tables in metadata
import service1.client_domain_models  # noqa: F401 - registers shared ClientFlow domain tables
import service1.terminal_v2_models  # noqa: F401 - registers adopted Terminal-v2 tables in metadata
import service1.remote_desktop_v2_models  # noqa: F401 - registers isolated Remote Desktop tables in metadata
import service1.client_activity_models  # noqa: F401 - registers shared activity leases

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    value = os.environ["DATABASE_URL"].strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    return value


DATABASE_URL = _database_url()
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
target_metadata = SQLModel.metadata


def _configure(connection=None, *, url=None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        # Legacy server defaults intentionally differ from several safe
        # application-side defaults. Future changes must state defaults
        # explicitly in reviewed migration files.
        compare_server_default=False,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"} if connection is None else None,
    )


def run_migrations_offline() -> None:
    _configure(url=DATABASE_URL)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    external_connection = config.attributes.get("connection")
    if external_connection is not None:
        _configure(connection=external_connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
