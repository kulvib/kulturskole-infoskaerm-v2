#!/usr/bin/env python3
"""Run PlanIQ Display Alembic migrations safely during Render pre-deploy.

The runner never guesses. It verifies the current revision, runs all reviewed
migrations under a PostgreSQL advisory lock, and validates the final catalog
against the frozen production contract. A legacy production schema can be
adopted exactly once, but only behind an explicit environment flag and only
after a full comparison with the reviewed frozen baseline.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from display_schema_contract import (
    BASELINE_REVISION,
    EXPECTED_COLUMNS,
    EXPECTED_CONSTRAINTS,
    EXPECTED_EXTENSION_NAMES,
    EXPECTED_HEAD_REVISION,
    EXPECTED_INDEXES,
    EXPECTED_SEQUENCES,
    EXPECTED_TABLES,
    EXPECTED_TRIGGERS,
)
from terminal_v2_schema_contract import (
    TERMINAL_V2_CONSTRAINTS,
    TERMINAL_V2_INDEXES,
    TERMINAL_V2_TABLES,
)
from remote_desktop_v2_schema_contract import (
    REMOTE_DESKTOP_V2_CONSTRAINTS,
    REMOTE_DESKTOP_V2_INDEXES,
    REMOTE_DESKTOP_V2_TABLES,
)
from client_activity_schema_contract import (
    CLIENT_ACTIVITY_CONSTRAINTS,
    CLIENT_ACTIVITY_INDEXES,
    CLIENT_ACTIVITY_TABLES,
)
from adopted_runtime_schema_contract import (
    ADOPTED_RUNTIME_CONSTRAINTS,
    ADOPTED_RUNTIME_INDEXES,
    ADOPTED_RUNTIME_TABLES,
)
from canonical_foundations_schema_contract import (
    CANONICAL_FOUNDATION_CONSTRAINTS,
    CANONICAL_FOUNDATION_INDEXES,
    CANONICAL_FOUNDATION_TABLES,
    CANONICAL_RETIRED_CLIENT_COLUMNS,
)
from clientflow_deployment_schema_contract import (
    CLIENTFLOW_DEPLOYMENT_CONSTRAINTS,
    CLIENTFLOW_DEPLOYMENT_INDEXES,
    CLIENTFLOW_DEPLOYMENT_TABLES,
)

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"
ADVISORY_LOCK_KEY = -614927384150371204

# Baseline adoption is deliberately reviewed only for this exact graph. If a
# later migration changes the head, the adoption path fails closed until the
# baseline delta is reviewed again.
REVIEWED_BASELINE_ADOPTION_HEAD = "20260819_51a_update_control"
REVIEWED_BASELINE_ADOPTION_BASE = "20260712_30d_display_base"

# Production was observed at this Alembic label before Step 40A was deployed,
# but that label is not present in the reviewed repository graph. We only
# reconcile it when the *entire* live catalog exactly matches the known Step
# 39A schema; otherwise deployment fails closed without stamping or DDL.
RECOVERABLE_LEGACY_REVISION = "20260730_41a"
RECOVERABLE_LEGACY_TARGET = "20260717_39a_livestream_leases"
REVIEWED_LEGACY_RECONCILIATION_HEAD = "20260819_51a_update_control"
REVIEWED_LIVESTREAM_V2_PREDECESSOR = "20260814_40a_livestream_control"
REVIEWED_LIVESTREAM_V2_REVISION = "20260814_41a_livestream_v2"
REVIEWED_TERMINAL_V2_REVISION = "20260816_42a_terminal_v2"
REVIEWED_TERMINAL_POLICY_REVISION = "20260816_43a_terminal_policy"
REVIEWED_TERMINAL_STORAGE_REVISION = "20260816_44a_terminal_store"
REVIEWED_TERMINAL_CLIENT_REVISION = "20260816_45a_terminal_client"
REVIEWED_REMOTE_DESKTOP_V2_REVISION = "20260817_46a_remote_desktop_v2"
REVIEWED_CLIENT_ACTIVITY_REVISION = "20260818_47a_client_activity"
REVIEWED_LIFECYCLE_REVISION = "20260818_48a_lifecycle"
REVIEWED_DATABASE_CONTRACT_REVISION = "20260819_49a_db_contract"
REVIEWED_CANONICAL_FOUNDATIONS_REVISION = "20260819_50a_canonical"
REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION = "20260819_51a_update_control"
LIVESTREAM_V2_TABLES = frozenset({
    "livestream_v2_agent_status",
    "livestream_v2_command",
    "livestream_v2_credential",
    "livestream_v2_generation",
    "livestream_v2_viewer",
})
LIVESTREAM_V2_SEQUENCES = frozenset({
    "livestream_v2_agent_status_id_seq",
    "livestream_v2_viewer_id_seq",
})


def _without_livestream_v2_schema(
    columns: dict[str, dict],
    constraints: dict[str, str],
    indexes: dict[str, str],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Remove only Step 41A's isolated Livestream-v2 objects."""
    cleaned_columns = {
        table: values for table, values in columns.items()
        if table not in LIVESTREAM_V2_TABLES
    }
    cleaned_constraints = {
        name: definition for name, definition in constraints.items()
        if not name.startswith("livestream_v2_")
        and not name.startswith("uq_livestream_v2_")
    }
    cleaned_indexes = {
        name: definition for name, definition in indexes.items()
        if not name.startswith("livestream_v2_")
        and not name.startswith("ix_livestream_v2_")
        and not name.startswith("uq_livestream_v2_")
    }
    return cleaned_columns, cleaned_constraints, cleaned_indexes


def _without_terminal_v2_schema(
    columns: dict[str, dict],
    constraints: dict[str, str],
    indexes: dict[str, str],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Remove Step 42A's adopted Terminal-v2 objects from a head contract."""
    cleaned_columns = {table: values for table, values in columns.items() if table not in TERMINAL_V2_TABLES}
    cleaned_constraints = {
        name: definition for name, definition in constraints.items()
        if name not in TERMINAL_V2_CONSTRAINTS
    }
    cleaned_indexes = {
        name: definition for name, definition in indexes.items()
        if name not in TERMINAL_V2_INDEXES
    }
    return cleaned_columns, cleaned_constraints, cleaned_indexes


def _without_remote_desktop_v2_schema(
    columns: dict[str, dict],
    constraints: dict[str, str],
    indexes: dict[str, str],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Remove Step 46A's Remote Desktop-owned storage from a head contract."""
    cleaned_columns = {table: values for table, values in columns.items() if table not in REMOTE_DESKTOP_V2_TABLES}
    cleaned_constraints = {
        name: definition for name, definition in constraints.items()
        if name not in REMOTE_DESKTOP_V2_CONSTRAINTS
    }
    cleaned_indexes = {
        name: definition for name, definition in indexes.items()
        if name not in REMOTE_DESKTOP_V2_INDEXES
    }
    return cleaned_columns, cleaned_constraints, cleaned_indexes


def _without_client_activity_schema(
    columns: dict[str, dict],
    constraints: dict[str, str],
    indexes: dict[str, str],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Remove Step 47A's shared browser-activity leases from a head contract."""
    cleaned_columns = {table: values for table, values in columns.items() if table not in CLIENT_ACTIVITY_TABLES}
    cleaned_constraints = {
        name: definition for name, definition in constraints.items()
        if name not in CLIENT_ACTIVITY_CONSTRAINTS
    }
    cleaned_indexes = {
        name: definition for name, definition in indexes.items()
        if name not in CLIENT_ACTIVITY_INDEXES
    }
    return cleaned_columns, cleaned_constraints, cleaned_indexes


def _without_adopted_runtime_schema(
    columns: dict[str, dict],
    constraints: dict[str, str],
    indexes: dict[str, str],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Remove Step 49A's legacy-origin tables from an earlier exact contract."""
    cleaned_columns = {table: values for table, values in columns.items() if table not in ADOPTED_RUNTIME_TABLES}
    cleaned_constraints = {
        name: definition for name, definition in constraints.items()
        if name not in ADOPTED_RUNTIME_CONSTRAINTS
    }
    cleaned_indexes = {
        name: definition for name, definition in indexes.items()
        if name not in ADOPTED_RUNTIME_INDEXES
    }
    return cleaned_columns, cleaned_constraints, cleaned_indexes


# These tables were observed in the production catalog stamped at the legacy
# revision above. Recovery must preserve the complete observed set while the
# unknown marker is reconciled. At the current head, Terminal-owned tables and
# the Step-49A adopted runtime tables move into exact verification; only the
# remaining opaque historical objects stay in HEAD_LEGACY_PRESERVED_TABLES.
RECOVERABLE_LEGACY_PRESERVED_TABLES = frozenset({
    "browser_websocket_ticket",
    "client_command",
    "client_domain_credential",
    "client_domain_status",
    "client_enrollment_receipt",
    "client_system_encryption_key",
    "livestream_generation",
    "remote_desktop_session",
    "remote_desktop_session_event",
    "root_terminal_grant",
    "terminal_session",
    "terminal_session_event",
})

HEAD_LEGACY_PRESERVED_TABLES = frozenset(
    RECOVERABLE_LEGACY_PRESERVED_TABLES
    - TERMINAL_V2_TABLES
    - ADOPTED_RUNTIME_TABLES
    - CANONICAL_FOUNDATION_TABLES
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} skal være true eller false")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} skal være et heltal") from exc
    if value < minimum:
        raise RuntimeError(f"{name} skal være mindst {minimum}")
    return value


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL mangler")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if not value.startswith("postgresql://"):
        raise RuntimeError("Display production-migrationer kræver PostgreSQL")
    return value


def _normalise(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value.strip())


def _normalise_constraint(value: str | None) -> str | None:
    """Normalise PostgreSQL-equivalent constraint deparsing across majors.

    PostgreSQL can deparse ``text = ANY(text[])`` / ``text <> ALL(text[])``
    constants either by casting each varchar literal to text or by casting the
    completed varchar array to ``text[]``.  Those forms are semantically identical, but a byte-for-byte
    catalog comparison would treat them as drift.  Keep this deliberately
    narrow to CHECK/ANY/ARRAY renderings so meaningful constraint differences
    still fail closed.
    """
    normalised = _normalise(value)
    if (
        normalised is None
        or not normalised.startswith("CHECK (")
        or (" ANY (ARRAY[" not in normalised and " ALL (ARRAY[" not in normalised)
    ):
        return normalised

    string_literal = r"('(?:''|[^'])*')"
    normalised = re.sub(
        string_literal + r"::character varying::text",
        r"\1",
        normalised,
    )
    normalised = re.sub(
        string_literal + r"::character varying",
        r"\1",
        normalised,
    )
    normalised = re.sub(r"(ARRAY\[[^\]]*\])::text\[\]", r"\1", normalised)
    return normalised


def _catalog_snapshot(connection) -> dict:
    tables = {
        row[0]
        for row in connection.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE'"
        ))
    }
    columns: dict[str, dict[str, dict]] = {}
    for row in connection.execute(text("""
        SELECT table_name, column_name, data_type, udt_name, is_nullable,
               character_maximum_length, column_default
        FROM information_schema.columns
        WHERE table_schema='public'
        ORDER BY table_name, ordinal_position
    """)):
        columns.setdefault(row.table_name, {})[row.column_name] = {
            "data_type": row.data_type,
            "udt_name": row.udt_name,
            "nullable": row.is_nullable == "YES",
            "length": row.character_maximum_length,
            "default": row.column_default,
        }
    constraint_rows = list(connection.execute(text("""
        SELECT c.conname AS constraint_name,
               c.contype AS constraint_type,
               pg_get_constraintdef(c.oid, true) AS definition,
               rel.relname AS table_name
        FROM pg_constraint c
        JOIN pg_namespace n ON n.oid=c.connamespace
        LEFT JOIN pg_class rel ON rel.oid=c.conrelid
        WHERE n.nspname='public'
    """)))
    constraints = {
        row.constraint_name: _normalise(row.definition)
        for row in constraint_rows
        if row.constraint_name != "alembic_version_pkc"
        and row.constraint_type != "n"
    }
    constraint_tables = {
        row.constraint_name: row.table_name
        for row in constraint_rows
        if row.constraint_name != "alembic_version_pkc"
        and row.constraint_type != "n"
    }

    index_rows = list(connection.execute(text(
        "SELECT tablename AS table_name, indexname, indexdef "
        "FROM pg_indexes WHERE schemaname='public'"
    )))
    indexes = {
        row.indexname: _normalise(row.indexdef)
        for row in index_rows
        if row.indexname != "alembic_version_pkc"
    }
    index_tables = {
        row.indexname: row.table_name
        for row in index_rows
        if row.indexname != "alembic_version_pkc"
    }

    sequence_rows = list(connection.execute(text("""
        SELECT seq.relname AS sequence_name, tbl.relname AS table_name
        FROM pg_class seq
        JOIN pg_namespace ns ON ns.oid = seq.relnamespace
        LEFT JOIN pg_depend dep
          ON dep.objid = seq.oid
         AND dep.classid = 'pg_class'::regclass
         AND dep.refclassid = 'pg_class'::regclass
         AND dep.deptype IN ('a', 'i')
        LEFT JOIN pg_class tbl ON tbl.oid = dep.refobjid
        WHERE ns.nspname='public' AND seq.relkind='S'
    """)))
    sequences = {row.sequence_name for row in sequence_rows}
    sequence_tables: dict[str, str | None] = {}
    for row in sequence_rows:
        if row.sequence_name not in sequence_tables or row.table_name is not None:
            sequence_tables[row.sequence_name] = row.table_name

    trigger_rows = list(connection.execute(text(
        "SELECT DISTINCT trigger_name, event_object_table AS table_name "
        "FROM information_schema.triggers WHERE trigger_schema='public'"
    )))
    triggers = {row.trigger_name for row in trigger_rows}
    trigger_tables = {row.trigger_name: row.table_name for row in trigger_rows}

    extensions = {row[0] for row in connection.execute(text("SELECT extname FROM pg_extension"))}
    return {
        "tables": tables,
        "columns": columns,
        "constraints": constraints,
        "constraint_tables": constraint_tables,
        "constraint_entries": [
            (row.constraint_name, _normalise(row.definition), row.table_name)
            for row in constraint_rows
            if row.constraint_name != "alembic_version_pkc"
            and row.constraint_type != "n"
        ],
        "indexes": indexes,
        "index_tables": index_tables,
        "sequences": sequences,
        "sequence_tables": sequence_tables,
        "triggers": triggers,
        "trigger_tables": trigger_tables,
        "extensions": extensions,
    }


def _without_clientflow_deployment_schema(
    columns: dict[str, dict],
    constraints: dict[str, str],
    indexes: dict[str, str],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Remove Step 51A objects when reconstructing earlier reviewed schemas."""
    cleaned_columns = {
        table: values for table, values in columns.items()
        if table not in CLIENTFLOW_DEPLOYMENT_TABLES
    }
    cleaned_constraints = {
        name: definition for name, definition in constraints.items()
        if name not in CLIENTFLOW_DEPLOYMENT_CONSTRAINTS
    }
    cleaned_indexes = {
        name: definition for name, definition in indexes.items()
        if name not in CLIENTFLOW_DEPLOYMENT_INDEXES
    }
    return cleaned_columns, cleaned_constraints, cleaned_indexes


def _without_canonical_foundations_schema(
    columns: dict[str, dict],
    constraints: dict[str, str],
    indexes: dict[str, str],
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Remove Step 50A objects when reconstructing an earlier reviewed schema."""
    cleaned_columns = {
        table: values for table, values in columns.items()
        if table not in CANONICAL_FOUNDATION_TABLES
    }
    client_columns = dict(cleaned_columns["client"])
    client_columns.update(CANONICAL_RETIRED_CLIENT_COLUMNS)
    cleaned_columns["client"] = client_columns
    cleaned_constraints = {
        name: definition for name, definition in constraints.items()
        if name not in CANONICAL_FOUNDATION_CONSTRAINTS
        or name in {
            "ck_client_domain_credential_domain",
            "ck_client_domain_status_domain",
            "ck_client_command_domain",
        }
    }
    # Restore the Step-49A shared-domain definitions before earlier-schema
    # reconstruction removes the adopted shared runtime tables entirely.
    for name in (
        "ck_client_domain_credential_domain",
        "ck_client_domain_status_domain",
        "ck_client_command_domain",
    ):
        cleaned_constraints[name] = ADOPTED_RUNTIME_CONSTRAINTS[name]
    cleaned_indexes = {
        name: definition for name, definition in indexes.items()
        if name not in CANONICAL_FOUNDATION_INDEXES
    }
    return cleaned_columns, cleaned_constraints, cleaned_indexes


def _baseline_schema_contract() -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Return the exact frozen schema immediately before Step 34A.

    Reviewed deltas from the frozen baseline are Step 34A audit request-id,
    Step 35A ClientFlow runtime telemetry columns, Step 36A ClientFlow
    release-catalog deployment columns, Step 37A's calendar uniqueness and
    system-default database expressions, Step 38A's time-integrity columns, and
    Step 39A's persistent livestream viewer-lease table. The explicit head guard
    prevents this one-time adoption helper from being reused after the migration
    graph changes without a new review.
    """
    if (
        BASELINE_REVISION != REVIEWED_BASELINE_ADOPTION_BASE
        or EXPECTED_HEAD_REVISION != REVIEWED_BASELINE_ADOPTION_HEAD
    ):
        raise RuntimeError(
            "Display baseline-adoption er ikke gennemgået for den aktuelle Alembic-kæde"
        )

    columns, constraints, indexes = _without_clientflow_deployment_schema(
        {table: dict(values) for table, values in EXPECTED_COLUMNS.items()},
        dict(EXPECTED_CONSTRAINTS),
        dict(EXPECTED_INDEXES),
    )
    columns, constraints, indexes = _without_canonical_foundations_schema(
        columns, constraints, indexes
    )
    columns, constraints, indexes = _without_adopted_runtime_schema(
        columns, constraints, indexes
    )
    columns, constraints, indexes = _without_livestream_v2_schema(
        columns, constraints, indexes
    )
    columns, constraints, indexes = _without_terminal_v2_schema(columns, constraints, indexes)
    columns, constraints, indexes = _without_client_activity_schema(columns, constraints, indexes)
    columns, constraints, indexes = _without_remote_desktop_v2_schema(columns, constraints, indexes)
    removed_livestream_table = columns.pop("livestream_viewer_lease", None)
    if removed_livestream_table is None:
        raise RuntimeError("Head-kontrakten mangler livestream_viewer_lease")

    audit_columns = dict(columns["audit_logs"])
    removed_column = audit_columns.pop("request_id", None)
    if removed_column is None:
        raise RuntimeError("Head-kontrakten mangler audit_logs.request_id")
    columns["audit_logs"] = audit_columns

    client_columns = dict(columns["client"])
    runtime_columns = {
        "client_version_patch", "client_version_updated_at",
        "ubuntu_update_status", "ubuntu_update_step", "ubuntu_update_message",
        "ubuntu_update_error", "ubuntu_update_started_at", "ubuntu_update_updated_at",
        "ubuntu_update_finished_at", "ubuntu_update_progress",
        "ubuntu_update_package_count", "ubuntu_update_reboot_required",
        "client_update_target_version", "client_update_target_release_sequence",
        "client_update_deployment_sequence", "client_update_applied_deployment_sequence",
        "client_update_allow_downgrade", "client_update_reason",
        "system_timezone", "ntp_enabled", "ntp_synchronized",
        "client_time_utc", "clock_drift_seconds", "time_sync_status",
        "time_sync_message",
        # Step 40A: isolated Livestream control-plane / explicit-stop metadata.
    }
    missing_runtime_columns = sorted(runtime_columns - set(client_columns))
    if missing_runtime_columns:
        raise RuntimeError(
            f"Head-kontrakten mangler runtime-kolonner: {missing_runtime_columns}"
        )
    for column_name in runtime_columns:
        client_columns.pop(column_name)
    columns["client"] = client_columns

    old_day_times_default = (
        "jsonb_build_object('monday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), "
        "'tuesday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'wednesday', "
        "jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'thursday', "
        "jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'friday', "
        "jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'saturday', "
        "jsonb_build_object('onTime', '08:00', 'offTime', '18:00'), 'sunday', "
        "jsonb_build_object('onTime', '08:00', 'offTime', '18:00'))"
    )
    for table_name in ("organization", "organizationseasontimes"):
        table_columns = dict(columns[table_name])
        day_times = dict(table_columns["day_times"])
        day_times["default"] = old_day_times_default
        table_columns["day_times"] = day_times
        columns[table_name] = table_columns

    for constraint_name in (
        "livestream_viewer_lease_pkey",
        "livestream_viewer_lease_client_id_fkey",
        "uq_livestream_viewer_lease_client_viewer",
    ):
        if constraints.pop(constraint_name, None) is None:
            raise RuntimeError(f"Head-kontrakten mangler {constraint_name}")
    removed_constraint = constraints.pop("calendarmarking_client_season_unique", None)
    if removed_constraint is None:
        raise RuntimeError("Head-kontrakten mangler calendarmarking_client_season_unique")

    for index_name in (
        "livestream_viewer_lease_pkey",
        "uq_livestream_viewer_lease_client_viewer",
        "ix_livestream_viewer_lease_expires_at",
        "ix_livestream_viewer_lease_client_id",
    ):
        if indexes.pop(index_name, None) is None:
            raise RuntimeError(f"Head-kontrakten mangler {index_name}")
    removed_index = indexes.pop("ix_audit_logs_request_id", None)
    if removed_index is None:
        raise RuntimeError("Head-kontrakten mangler ix_audit_logs_request_id")
    removed_calendar_index = indexes.pop("calendarmarking_client_season_unique", None)
    if removed_calendar_index is None:
        raise RuntimeError("Head-kontrakten mangler calendarmarking_client_season_unique index")
    return columns, constraints, indexes


def _pre_livestream_control_schema_contract() -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Return the exact reviewed schema at Step 39A, immediately before Step 40A.

    This contract is used only to recover one production Alembic label that is
    absent from the repository. Recovery is allowed only when the complete
    database catalog exactly matches Step 39A, proving that the unknown label
    carries no schema delta relative to the reviewed predecessor.
    """
    if EXPECTED_HEAD_REVISION != REVIEWED_LEGACY_RECONCILIATION_HEAD:
        raise RuntimeError(
            "Legacy-revision reconciliation er ikke gennemgået for den aktuelle Alembic-kæde"
        )

    columns, constraints, indexes = _without_clientflow_deployment_schema(
        {table: dict(values) for table, values in EXPECTED_COLUMNS.items()},
        dict(EXPECTED_CONSTRAINTS),
        dict(EXPECTED_INDEXES),
    )
    columns, constraints, indexes = _without_canonical_foundations_schema(
        columns, constraints, indexes
    )
    columns, constraints, indexes = _without_adopted_runtime_schema(
        columns, constraints, indexes
    )
    columns, constraints, indexes = _without_livestream_v2_schema(
        columns, constraints, indexes
    )
    columns, constraints, indexes = _without_terminal_v2_schema(columns, constraints, indexes)
    columns, constraints, indexes = _without_client_activity_schema(columns, constraints, indexes)
    columns, constraints, indexes = _without_remote_desktop_v2_schema(columns, constraints, indexes)
    client_columns = dict(columns["client"])
    step_40a_columns = {
        "livestream_stop_reason",
    }
    missing = sorted(step_40a_columns - set(client_columns))
    if missing:
        raise RuntimeError(f"Head-kontrakten mangler Step 40A-kolonner: {missing}")
    for column_name in step_40a_columns:
        client_columns.pop(column_name)
    columns["client"] = client_columns

    # Step 40A changes columns only. Step 41A objects were removed above,
    # leaving the exact Step 39A constraints/indexes.
    return columns, constraints, indexes


def _verify_schema(
    connection,
    *,
    exact_tables: bool = True,
    expected_columns: dict[str, dict] | None = None,
    expected_constraints: dict[str, str] | None = None,
    expected_indexes: dict[str, str] | None = None,
    expected_sequences: set[str] | None = None,
    preserved_tables: frozenset[str] | set[str] | None = None,
    require_preserved_tables: bool = False,
    contract_label: str = "head",
) -> dict[str, int]:
    expected_columns = expected_columns or EXPECTED_COLUMNS
    expected_constraints = expected_constraints or EXPECTED_CONSTRAINTS
    expected_indexes = expected_indexes or EXPECTED_INDEXES
    if expected_sequences is None:
        expected_sequences = EXPECTED_SEQUENCES
    preserved_tables = frozenset(preserved_tables or ())
    expected_tables = set(expected_columns)
    snapshot = _catalog_snapshot(connection)
    allowed_tables = expected_tables | {"alembic_version"} | set(preserved_tables)
    missing_tables = sorted(expected_tables - snapshot["tables"])
    missing_preserved = (
        sorted(set(preserved_tables) - snapshot["tables"]) if require_preserved_tables else []
    )
    unexpected_tables = sorted(snapshot["tables"] - allowed_tables) if exact_tables else []
    if missing_tables or missing_preserved or unexpected_tables:
        raise RuntimeError(
            f"Display {contract_label}-schema table-afvigelse; "
            f"mangler={missing_tables}, legacy_mangler={missing_preserved}, "
            f"uventede={unexpected_tables}"
        )

    column_errors: dict[str, object] = {}
    for table, expected in expected_columns.items():
        actual = snapshot["columns"].get(table, {})
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = {
            name: {"expected": expected[name], "actual": actual[name]}
            for name in sorted(set(expected) & set(actual))
            if expected[name] != actual[name]
        }
        if missing or extra or changed:
            column_errors[table] = {"missing": missing, "extra": extra, "changed": changed}
    if column_errors:
        raise RuntimeError(
            f"Display {contract_label}-schema kolonne-afvigelse: {column_errors}"
        )

    if snapshot.get("constraint_entries") is not None:
        actual_constraints = {
            name: definition
            for name, definition, table_name in snapshot["constraint_entries"]
            if table_name not in preserved_tables
        }
    else:
        actual_constraints = {
            name: definition
            for name, definition in snapshot["constraints"].items()
            if snapshot.get("constraint_tables", {}).get(name) not in preserved_tables
        }
    actual_indexes = {
        name: definition
        for name, definition in snapshot["indexes"].items()
        if snapshot.get("index_tables", {}).get(name) not in preserved_tables
    }
    for label, expected, actual in (
        ("constraints", expected_constraints, actual_constraints),
        ("indexes", expected_indexes, actual_indexes),
    ):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = {
            name: {"expected": expected[name], "actual": actual[name]}
            for name in sorted(set(expected) & set(actual))
            if _normalise_constraint(expected[name]) != _normalise_constraint(actual[name])
        }
        if missing or extra or changed:
            raise RuntimeError(
                f"Display {contract_label}-schema {label}-afvigelse; "
                f"mangler={missing}, uventede={extra}, ændrede={changed}"
            )

    actual_sequences = {
        name for name in snapshot["sequences"]
        if snapshot.get("sequence_tables", {}).get(name) not in preserved_tables
    }
    if actual_sequences != expected_sequences:
        raise RuntimeError(
            f"Display {contract_label}-schema sequence-afvigelse; "
            f"forventet={sorted(expected_sequences)}, aktuel={sorted(actual_sequences)}"
        )
    actual_triggers = {
        name for name in snapshot["triggers"]
        if snapshot.get("trigger_tables", {}).get(name) not in preserved_tables
    }
    if actual_triggers != EXPECTED_TRIGGERS:
        raise RuntimeError(
            f"Display {contract_label}-schema trigger-afvigelse; "
            f"forventet={sorted(EXPECTED_TRIGGERS)}, aktuel={sorted(actual_triggers)}"
        )
    missing_extensions = EXPECTED_EXTENSION_NAMES - snapshot["extensions"]
    if missing_extensions:
        raise RuntimeError(
            f"Display {contract_label}-schema mangler extensions: {sorted(missing_extensions)}"
        )

    counts = {}
    for table in ("user", "organization", "client", "enrollmenttoken", "calendarmarking"):
        counts[table] = int(connection.scalar(text(f'SELECT COUNT(*) FROM "{table}"')) or 0)
    return counts


def _known_legacy_tables_at_head(connection) -> frozenset[str]:
    """Return the reviewed opaque legacy table set when it is present exactly.

    Once a legacy database has been reconciled to this repo head, subsequent
    deploys must continue to preserve those tables. A partial or different
    unknown table set is *not* accepted and will still fail exact head
    verification.
    """
    snapshot = _catalog_snapshot(connection)
    extras = snapshot["tables"] - EXPECTED_TABLES - {"alembic_version"}
    if extras == set(HEAD_LEGACY_PRESERVED_TABLES):
        return HEAD_LEGACY_PRESERVED_TABLES
    return frozenset()


def _rewrite_verified_legacy_revision_marker(
    connection,
    *,
    expected_current: str,
    target_revision: str,
) -> None:
    """Rewrite one verified unknown Alembic marker without resolving it.

    ``alembic command.stamp`` cannot move away from an unknown current revision:
    Alembic tries to resolve the current marker before writing the destination and
    fails first. This helper is intentionally narrower than ``stamp``. It only
    rewrites the single locked ``alembic_version`` row after the caller has fully
    verified the reviewed live schema. The surrounding migration transaction and
    advisory lock make the rewrite atomic with the subsequent normal upgrade.
    """
    if not expected_current or not target_revision or expected_current == target_revision:
        raise RuntimeError("Ugyldig legacy Alembic marker-reconciliation")

    rows = list(connection.execute(text(
        "SELECT version_num FROM alembic_version FOR UPDATE"
    )))
    versions = tuple(str(row[0]) for row in rows)
    if versions != (expected_current,):
        raise RuntimeError(
            "Legacy Alembic marker ændrede sig under reconciliation; "
            f"forventet={(expected_current,)}, aktuel={versions}. Ingen marker blev ændret."
        )

    result = connection.execute(
        text(
            "UPDATE alembic_version "
            "SET version_num = :target "
            "WHERE version_num = :expected"
        ),
        {"target": target_revision, "expected": expected_current},
    )
    if result.rowcount != 1:
        raise RuntimeError(
            "Legacy Alembic marker kunne ikke opdateres entydigt; "
            f"rowcount={result.rowcount}."
        )

    after_rows = list(connection.execute(text(
        "SELECT version_num FROM alembic_version"
    )))
    after_versions = tuple(str(row[0]) for row in after_rows)
    if after_versions != (target_revision,):
        raise RuntimeError(
            "Legacy Alembic marker-verifikation fejlede efter reconciliation; "
            f"forventet={(target_revision,)}, aktuel={after_versions}."
        )


def _alembic_config(connection) -> tuple[Config, ScriptDirectory, str]:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Forventede præcis ét Alembic-head, fandt {heads}")
    head = heads[0]
    if head != EXPECTED_HEAD_REVISION:
        raise RuntimeError(
            f"Repo-head {head!r} matcher ikke schema-kontraktens head {EXPECTED_HEAD_REVISION!r}"
        )
    return cfg, script, head


def _upgrade_and_verify(connection) -> tuple[str | None, str, dict[str, int], bool]:
    cfg, script, head = _alembic_config(connection)
    current_heads = MigrationContext.configure(connection).get_current_heads()
    if len(current_heads) > 1:
        raise RuntimeError(f"Databasen har flere Alembic-heads: {current_heads}")
    current = current_heads[0] if current_heads else None
    before = current
    baseline_adopted = False
    preserved_legacy_tables: frozenset[str] = frozenset()

    if current is None:
        app_tables = _catalog_snapshot(connection)["tables"] & EXPECTED_TABLES
        if app_tables:
            if not _env_bool("MIGRATION_ADOPT_VERIFIED_BASELINE", False):
                raise RuntimeError(
                    "Databasen har eksisterende Display-tabeller, men ingen Alembic-revision. "
                    "Sæt MIGRATION_ADOPT_VERIFIED_BASELINE=true til én kontrolleret deploy, "
                    "så runneren kan verificere hele den frosne baseline før adoption."
                )
            baseline_columns, baseline_constraints, baseline_indexes = _baseline_schema_contract()
            _verify_schema(
                connection,
                expected_columns=baseline_columns,
                expected_constraints=baseline_constraints,
                expected_indexes=baseline_indexes,
                expected_sequences=EXPECTED_SEQUENCES - {"livestream_viewer_lease_id_seq"} - LIVESTREAM_V2_SEQUENCES,
                contract_label="frossen baseline",
            )
            command.stamp(cfg, BASELINE_REVISION)
            stamped_heads = MigrationContext.configure(connection).get_current_heads()
            if stamped_heads != (BASELINE_REVISION,):
                raise RuntimeError(
                    f"Baseline-adoption endte ikke på {BASELINE_REVISION!r}; "
                    f"aktuel revision={stamped_heads}"
                )
            current = BASELINE_REVISION
            baseline_adopted = True
        elif not _env_bool("MIGRATION_ALLOW_EMPTY_DATABASE", False):
            raise RuntimeError(
                "Databasen er tom og har ingen Alembic-revision. "
                "MIGRATION_ALLOW_EMPTY_DATABASE=true kræves bevidst for en ny database."
            )
    else:
        if current == RECOVERABLE_LEGACY_REVISION:
            if head != REVIEWED_LEGACY_RECONCILIATION_HEAD:
                raise RuntimeError(
                    "Legacy-revision reconciliation er ikke gennemgået for dette repo-head"
                )
            target_revision = script.get_revision(RECOVERABLE_LEGACY_TARGET)
            predecessor_revision = script.get_revision(REVIEWED_LIVESTREAM_V2_PREDECESSOR)
            livestream_v2_revision = script.get_revision(REVIEWED_LIVESTREAM_V2_REVISION)
            terminal_v2_revision = script.get_revision(REVIEWED_TERMINAL_V2_REVISION)
            terminal_policy_revision = script.get_revision(REVIEWED_TERMINAL_POLICY_REVISION)
            terminal_storage_revision = script.get_revision(REVIEWED_TERMINAL_STORAGE_REVISION)
            terminal_client_revision = script.get_revision(REVIEWED_TERMINAL_CLIENT_REVISION)
            remote_desktop_revision = script.get_revision(REVIEWED_REMOTE_DESKTOP_V2_REVISION)
            client_activity_revision = script.get_revision(REVIEWED_CLIENT_ACTIVITY_REVISION)
            lifecycle_revision = script.get_revision(REVIEWED_LIFECYCLE_REVISION)
            database_contract_revision = script.get_revision(REVIEWED_DATABASE_CONTRACT_REVISION)
            canonical_foundations_revision = script.get_revision(REVIEWED_CANONICAL_FOUNDATIONS_REVISION)
            clientflow_deployment_revision = script.get_revision(REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION)
            head_revision = script.get_revision(head)
            if any(
                item is None
                for item in (
                    target_revision, predecessor_revision, livestream_v2_revision,
                    terminal_v2_revision, terminal_policy_revision, terminal_storage_revision,
                    terminal_client_revision, remote_desktop_revision, client_activity_revision, lifecycle_revision,
                    database_contract_revision, canonical_foundations_revision, clientflow_deployment_revision, head_revision,
                )
            ):
                raise RuntimeError("Legacy-revision reconciliation mangler kendte Alembic-noder")
            if (
                predecessor_revision.down_revision != RECOVERABLE_LEGACY_TARGET
                or livestream_v2_revision.down_revision != REVIEWED_LIVESTREAM_V2_PREDECESSOR
                or terminal_v2_revision.down_revision != REVIEWED_LIVESTREAM_V2_REVISION
                or terminal_policy_revision.down_revision != REVIEWED_TERMINAL_V2_REVISION
                or terminal_storage_revision.down_revision != REVIEWED_TERMINAL_POLICY_REVISION
                or terminal_client_revision.down_revision != REVIEWED_TERMINAL_STORAGE_REVISION
                or remote_desktop_revision.down_revision != REVIEWED_TERMINAL_CLIENT_REVISION
                or client_activity_revision.down_revision != REVIEWED_REMOTE_DESKTOP_V2_REVISION
                or lifecycle_revision.down_revision != REVIEWED_CLIENT_ACTIVITY_REVISION
                or database_contract_revision.down_revision != REVIEWED_LIFECYCLE_REVISION
                or canonical_foundations_revision.down_revision != REVIEWED_DATABASE_CONTRACT_REVISION
                or clientflow_deployment_revision.down_revision != REVIEWED_CANONICAL_FOUNDATIONS_REVISION
                or head != REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION
            ):
                raise RuntimeError(
                    "Legacy-revision reconciliation kræver den reviewed Step 39A -> 40A -> 41A -> 42A -> 43A -> 44A -> 45A -> 46A -> 47A -> 48A -> 49A -> 50A -> 51A-kæde"
                )
            legacy_columns, legacy_constraints, legacy_indexes = (
                _pre_livestream_control_schema_contract()
            )
            _verify_schema(
                connection,
                expected_columns=legacy_columns,
                expected_constraints=legacy_constraints,
                expected_indexes=legacy_indexes,
                expected_sequences=EXPECTED_SEQUENCES - LIVESTREAM_V2_SEQUENCES,
                preserved_tables=RECOVERABLE_LEGACY_PRESERVED_TABLES,
                require_preserved_tables=True,
                contract_label=(
                    f"legacy {RECOVERABLE_LEGACY_REVISION} som Step 39A "
                    "med bevarede legacy-tabeller"
                ),
            )
            _rewrite_verified_legacy_revision_marker(
                connection,
                expected_current=RECOVERABLE_LEGACY_REVISION,
                target_revision=RECOVERABLE_LEGACY_TARGET,
            )
            stamped_heads = MigrationContext.configure(connection).get_current_heads()
            if stamped_heads != (RECOVERABLE_LEGACY_TARGET,):
                raise RuntimeError(
                    f"Legacy-revision reconciliation endte ikke på {RECOVERABLE_LEGACY_TARGET!r}; "
                    f"aktuel revision={stamped_heads}"
                )
            current = RECOVERABLE_LEGACY_TARGET
            preserved_legacy_tables = RECOVERABLE_LEGACY_PRESERVED_TABLES
            print(
                "Verificeret legacy Alembic-revision "
                f"{RECOVERABLE_LEGACY_REVISION!r}: repo-ejet Step 39A-schema matcher eksakt; "
                f"{len(RECOVERABLE_LEGACY_PRESERVED_TABLES)} kendte legacy-tabeller bevares urørte; "
                f"versionsmarkør omskrevet sikkert til {RECOVERABLE_LEGACY_TARGET!r}."
            )
        else:
            try:
                script.get_revision(current)
            except CommandError as exc:
                raise RuntimeError(
                    f"Databasen står på ukendt Alembic-revision {current!r}; "
                    "ingen stamp eller schemaændring udføres."
                ) from exc
        # A reconciled production database can be on a known predecessor
        # revision while still carrying the complete reviewed opaque legacy
        # table set. Detect that set *before* upgrade so the final head-schema
        # verification keeps preserving it. Partial/different unknown table
        # sets still return an empty set and therefore fail exact verification.
        if not preserved_legacy_tables:
            preserved_legacy_tables = _known_legacy_tables_at_head(connection)

        if current == head:
            _verify_schema(
                connection,
                preserved_tables=preserved_legacy_tables,
                require_preserved_tables=bool(preserved_legacy_tables),
            )

    command.upgrade(cfg, "head")
    after_heads = MigrationContext.configure(connection).get_current_heads()
    if after_heads != (head,):
        raise RuntimeError(f"Alembic endte ikke på head {head!r}; aktuel revision={after_heads}")
    head_preserved_tables = frozenset(
        set(preserved_legacy_tables) & set(HEAD_LEGACY_PRESERVED_TABLES)
    )
    counts = _verify_schema(
        connection,
        preserved_tables=head_preserved_tables,
        require_preserved_tables=bool(head_preserved_tables),
    )
    return before, head, counts, baseline_adopted


def _acquire_lock(connection, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY}
        )
        if acquired:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Kunne ikke få migrationslåsen inden for {timeout_seconds} sekunder")
        time.sleep(1)


def main() -> None:
    advisory_timeout = _env_int("MIGRATION_ADVISORY_LOCK_TIMEOUT_SECONDS", 120)
    lock_timeout = _env_int("MIGRATION_LOCK_TIMEOUT_SECONDS", 10)
    statement_timeout = _env_int("MIGRATION_STATEMENT_TIMEOUT_SECONDS", 300)
    engine = create_engine(_database_url(), poolclass=NullPool, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                _acquire_lock(connection, advisory_timeout)
                connection.execute(
                    text("SELECT set_config('lock_timeout', :value, true)"),
                    {"value": f"{lock_timeout}s"},
                )
                connection.execute(
                    text("SELECT set_config('statement_timeout', :value, true)"),
                    {"value": f"{statement_timeout}s"},
                )
                before, after, counts, baseline_adopted = _upgrade_and_verify(connection)
        print("Display database-migration bestået")
        print(f"- revision før: {before or '<ingen Alembic-revision>'}")
        print(f"- verificeret baseline adopteret: {'ja' if baseline_adopted else 'nej'}")
        print(f"- revision efter: {after}")
        print("- rækkeantal: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
