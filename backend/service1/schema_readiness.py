"""Read-only Alembic schema readiness for PlanIQ health checks.

The module compares the database's recorded Alembic revision with the single
head shipped in the running release. It never upgrades, stamps or otherwise
changes the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _BACKEND_ROOT / "migrations"
_VERSION_TABLE = "alembic_version"


@dataclass(frozen=True)
class RepositorySchemaState:
    """Immutable Alembic metadata loaded from the running release."""

    heads: tuple[str, ...]
    known_revisions: frozenset[str]


@dataclass(frozen=True)
class SchemaReadiness:
    """Neutral readiness result without revision identifiers."""

    ready: bool
    reason: str
    repository_head_count: int
    database_head_count: int


@lru_cache(maxsize=1)
def load_repository_schema_state() -> RepositorySchemaState:
    """Load and cache the repository migration graph for this release."""
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    script = ScriptDirectory.from_config(config)
    heads = tuple(script.get_heads())
    known_revisions = frozenset(
        str(revision.revision)
        for revision in script.walk_revisions(base="base", head="heads")
    )
    return RepositorySchemaState(heads=heads, known_revisions=known_revisions)


def _not_ready(
    reason: str,
    *,
    repository_head_count: int,
    database_head_count: int,
) -> SchemaReadiness:
    return SchemaReadiness(
        ready=False,
        reason=reason,
        repository_head_count=repository_head_count,
        database_head_count=database_head_count,
    )


def check_schema_readiness(
    connection: Connection,
    *,
    repository_state: RepositorySchemaState | None = None,
) -> SchemaReadiness:
    """Compare database revision and repository head without changing schema.

    Expected schema drift is returned as a neutral status. Database/driver
    exceptions deliberately propagate so the caller can classify them as
    ``database_unavailable`` without exposing raw exception data.
    """
    if repository_state is None:
        try:
            repository_state = load_repository_schema_state()
        except Exception:
            return _not_ready(
                "repository_metadata_unavailable",
                repository_head_count=0,
                database_head_count=0,
            )

    repository_head_count = len(repository_state.heads)
    if repository_head_count != 1:
        return _not_ready(
            "repository_heads_invalid",
            repository_head_count=repository_head_count,
            database_head_count=0,
        )

    if not inspect(connection).has_table(_VERSION_TABLE):
        return _not_ready(
            "version_table_missing",
            repository_head_count=repository_head_count,
            database_head_count=0,
        )

    database_heads = tuple(MigrationContext.configure(connection).get_current_heads())
    database_head_count = len(database_heads)
    if database_head_count == 0:
        return _not_ready(
            "version_table_empty",
            repository_head_count=repository_head_count,
            database_head_count=0,
        )
    if database_head_count != 1:
        return _not_ready(
            "database_heads_multiple",
            repository_head_count=repository_head_count,
            database_head_count=database_head_count,
        )

    current_revision = database_heads[0]
    if current_revision not in repository_state.known_revisions:
        return _not_ready(
            "database_revision_unknown",
            repository_head_count=repository_head_count,
            database_head_count=database_head_count,
        )
    if current_revision != repository_state.heads[0]:
        return _not_ready(
            "database_revision_outdated",
            repository_head_count=repository_head_count,
            database_head_count=database_head_count,
        )

    return SchemaReadiness(
        ready=True,
        reason="ready",
        repository_head_count=repository_head_count,
        database_head_count=database_head_count,
    )
