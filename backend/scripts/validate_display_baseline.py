#!/usr/bin/env python3
"""Validate the Display database platform contract without changing a database."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("ENVIRONMENT", "development")

from display_schema_contract import (  # noqa: E402
    BASELINE_REVISION,
    EXPECTED_COLUMNS,
    EXPECTED_CONSTRAINTS,
    EXPECTED_FINGERPRINT,
    EXPECTED_HEAD_REVISION,
    EXPECTED_INDEXES,
    EXPECTED_EXTENSION_NAMES,
    EXPECTED_SEQUENCES,
    EXPECTED_TABLES,
    EXPECTED_TRIGGERS,
)
from service1.models import SQLModel  # noqa: E402
import service1.livestream_v2_models  # noqa: E402,F401 - registers isolated tables
import service1.client_domain_models  # noqa: E402,F401 - registers shared ClientFlow domain tables
import service1.terminal_v2_models  # noqa: E402,F401 - registers adopted Terminal-v2 tables
import service1.remote_desktop_v2_models  # noqa: E402,F401 - registers isolated Remote Desktop tables
import service1.remote_desktop_session_models  # noqa: E402,F401 - registers reviewed Remote Desktop session tables
import service1.client_activity_models  # noqa: E402,F401 - registers shared activity leases
METADATA = SQLModel.metadata

MIGRATION = ROOT / "migrations" / "versions" / '20260712_30d_display_base_frozen_display_baseline.py'
RUNNER = ROOT / "scripts" / "run_migrations.py"
MAIN = ROOT / "service1" / "main.py"
RENDER = REPO_ROOT / "render.yaml"


def _db_type(column: dict) -> str:
    value = column["data_type"]
    if value == "character varying":
        length = column.get("length")
        return f"VARCHAR({length})" if length else "VARCHAR"
    if value == "integer":
        return "INTEGER"
    if value == "boolean":
        return "BOOLEAN"
    if value == "timestamp with time zone":
        return "TIMESTAMP WITH TIME ZONE"
    if value == "timestamp without time zone":
        return "TIMESTAMP WITHOUT TIME ZONE"
    if value == "time without time zone":
        return "TIME WITHOUT TIME ZONE"
    if value == "date":
        return "DATE"
    if value == "numeric":
        return "NUMERIC"
    if value == "json":
        return "JSON"
    if value == "jsonb":
        return "JSONB"
    if value == "text":
        return "TEXT"
    if value == "double precision":
        return "DOUBLE PRECISION"
    if value == "bytea":
        return "BYTEA"
    return value.upper()


def _normalise_model_type(value: str) -> str:
    value = " ".join(value.upper().split())
    # PostgreSQL reflects SQLAlchemy Float as DOUBLE PRECISION.
    if value == "FLOAT":
        return "DOUBLE PRECISION"
    if value.startswith("NUMERIC("):
        return "NUMERIC"
    return value


def _contract_fingerprint() -> str:
    payload = {
        "tables": sorted(EXPECTED_TABLES),
        "columns": EXPECTED_COLUMNS,
        "constraints": EXPECTED_CONSTRAINTS,
        "indexes": EXPECTED_INDEXES,
        "extensions": sorted(EXPECTED_EXTENSION_NAMES),
        "sequences": sorted(EXPECTED_SEQUENCES),
        "triggers": sorted(EXPECTED_TRIGGERS),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_graph(errors: list[str]) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    bases = script.get_bases()
    revisions = list(script.walk_revisions())
    if bases != [BASELINE_REVISION] or heads != [EXPECTED_HEAD_REVISION]:
        errors.append(
            f"Alembic-kæden afviger; forventet base={BASELINE_REVISION!r}, "
            f"head={EXPECTED_HEAD_REVISION!r}, fik bases={bases}, heads={heads}"
        )
    if not revisions:
        errors.append("Alembic-kæden indeholder ingen revisioner")


def _validate_models(errors: list[str]) -> None:
    dialect = postgresql.dialect()
    model_tables = set(METADATA.tables)
    if model_tables != EXPECTED_TABLES:
        errors.append(
            f"Modeltabeller afviger: model-only={sorted(model_tables-EXPECTED_TABLES)}, "
            f"contract-only={sorted(EXPECTED_TABLES-model_tables)}"
        )
        return

    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        table = METADATA.tables[table_name]
        actual_names = set(table.columns.keys())
        if actual_names != set(expected_columns):
            errors.append(
                f"Kolonnesæt afviger for {table_name}: "
                f"model-only={sorted(actual_names-set(expected_columns))}, "
                f"contract-only={sorted(set(expected_columns)-actual_names)}"
            )
        for name in sorted(actual_names & set(expected_columns)):
            column = table.columns[name]
            model_type = _normalise_model_type(column.type.compile(dialect=dialect))
            expected_type = _db_type(expected_columns[name])
            if model_type != expected_type or column.nullable != expected_columns[name]["nullable"]:
                errors.append(
                    f"Kolonneafvigelse {table_name}.{name}: "
                    f"model=({model_type}, nullable={column.nullable}), "
                    f"contract=({expected_type}, nullable={expected_columns[name]['nullable']})"
                )

    model_indexes = {index.name for table in METADATA.tables.values() for index in table.indexes if index.name}
    backing_indexes = {
        name for name, definition in EXPECTED_CONSTRAINTS.items()
        if definition.startswith(("PRIMARY KEY", "UNIQUE", "EXCLUDE"))
    }
    expected_explicit_indexes = set(EXPECTED_INDEXES) - backing_indexes
    if model_indexes != expected_explicit_indexes:
        errors.append(
            f"Eksplicitte indexes afviger: model-only={sorted(model_indexes-expected_explicit_indexes)}, "
            f"contract-only={sorted(expected_explicit_indexes-model_indexes)}"
        )

    model_constraints = {
        constraint.name
        for table in METADATA.tables.values()
        for constraint in table.constraints
        if constraint.name
    }
    unknown_model_constraints = model_constraints - set(EXPECTED_CONSTRAINTS)
    if unknown_model_constraints:
        errors.append(f"Modelconstraints mangler i production-kontrakten: {sorted(unknown_model_constraints)}")


def _validate_sources(errors: list[str]) -> None:
    ast.parse(MIGRATION.read_text(encoding="utf-8"), filename=str(MIGRATION))
    runner_source = RUNNER.read_text(encoding="utf-8")
    runner_tree = ast.parse(runner_source, filename=str(RUNNER))
    stamp_calls = [
        node
        for node in ast.walk(runner_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stamp"
    ]
    stamp_targets = []
    for call in stamp_calls:
        if len(call.args) < 2 or not isinstance(call.args[1], ast.Name):
            errors.append("Production-runnerens stamp-target skal være en navngivet reviewed konstant")
            continue
        stamp_targets.append(call.args[1].id)
    expected_stamp_targets = {"BASELINE_REVISION"}
    if set(stamp_targets) != expected_stamp_targets or len(stamp_targets) != 1:
        errors.append(
            "Production-runneren må kun bruge Alembic command.stamp til den "
            "kontrollerede BASELINE_REVISION-adoption"
        )
    for required in (
        "MIGRATION_ADOPT_VERIFIED_BASELINE",
        "_baseline_schema_contract",
        'contract_label="frossen baseline"',
        "REVIEWED_BASELINE_ADOPTION_HEAD",
        "RECOVERABLE_LEGACY_REVISION",
        "RECOVERABLE_LEGACY_TARGET",
        "RECOVERABLE_LEGACY_PRESERVED_TABLES",
        "_rewrite_verified_legacy_revision_marker",
        "UPDATE alembic_version",
        "WHERE version_num = :expected",
        "_pre_livestream_control_schema_contract",
        "_known_legacy_tables_at_head",
        "REVIEWED_LEGACY_RECONCILIATION_HEAD",
    ):
        if required not in runner_source:
            errors.append(f"Production-runneren mangler sikker baseline-adoption: {required}")
    if "alembic stamp" in runner_source:
        errors.append("Production-runneren må ikke bruge en løs alembic stamp-kommando")
    for migration_path in sorted((ROOT / "migrations" / "versions").glob("*.py")):
        migration_tree = ast.parse(
            migration_path.read_text(encoding="utf-8"), filename=str(migration_path)
        )
        for node in ast.walk(migration_tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_names = [alias.name for alias in node.names]
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_names.append(node.module)
                if any(name.startswith("service1") for name in module_names):
                    errors.append(
                        f"Migration {migration_path.name} må ikke importere runtime-modeller"
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_all"
            ):
                errors.append(
                    f"Migration {migration_path.name} må ikke kalde metadata.create_all()"
                )

    service_sources = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (ROOT / "service1").rglob("*.py")
    )
    for forbidden in (".create_all(", "ALTER TABLE", "CREATE TABLE"):
        if forbidden in service_sources:
            errors.append(f"Application runtime indeholder forbudt schema-DDL: {forbidden}")

    main_source = MAIN.read_text(encoding="utf-8")
    for route in ('@app.get("/health")', '@app.get("/health/db")'):
        if route not in main_source:
            errors.append(f"Manglende health endpoint: {route}")

    render_source = RENDER.read_text(encoding="utf-8")
    if "preDeployCommand: python scripts/run_migrations.py" not in render_source and 'preDeployCommand: "python scripts/run_migrations.py"' not in render_source:
        errors.append("render.yaml mangler migrationsrunner i preDeployCommand")
    if "healthCheckPath: /health" not in render_source:
        errors.append("Render liveness skal bruge /health")
    for line in render_source.splitlines():
        if "startCommand:" in line and "alembic" in line.lower():
            errors.append("Render startCommand må ikke køre Alembic")


def main() -> int:
    errors: list[str] = []
    if len(BASELINE_REVISION) > 32:
        errors.append("Alembic revision-id overskrider alembic_version VARCHAR(32)")
    if _contract_fingerprint() != EXPECTED_FINGERPRINT:
        errors.append("Schema-kontraktens fingerprint matcher ikke dens indhold")
    _validate_graph(errors)
    _validate_models(errors)
    _validate_sources(errors)

    if errors:
        print("Display database-platform-validering FEJLEDE:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Display database-platform-validering bestået")
    print(f"- base: {BASELINE_REVISION}")
    print(f"- head: {EXPECTED_HEAD_REVISION}")
    print(f"- tabeller: {len(EXPECTED_TABLES)}")
    print(f"- kolonner: {sum(len(value) for value in EXPECTED_COLUMNS.values())}")
    print(f"- indexes: {len(EXPECTED_INDEXES)}")
    print(f"- constraints: {len(EXPECTED_CONSTRAINTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
