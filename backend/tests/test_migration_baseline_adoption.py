from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location(
    "display_run_migrations",
    SCRIPTS_DIR / "run_migrations.py",
)
if spec is None or spec.loader is None:  # pragma: no cover - import guard
    raise RuntimeError("Kunne ikke indlæse Display migrationsrunner")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class _MigrationState:
    def __init__(self, heads: tuple[str, ...]):
        self._heads = heads

    def get_current_heads(self) -> tuple[str, ...]:
        return self._heads


class BaselineAdoptionTests(unittest.TestCase):
    def test_all_alembic_revision_ids_fit_version_table_column(self) -> None:
        versions_dir = BACKEND_ROOT / "migrations" / "versions"
        too_long: list[tuple[str, str, int]] = []
        missing: list[str] = []

        for path in sorted(versions_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            revision = None
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("revision = "):
                    value = stripped.split("=", 1)[1].strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
                        revision = value[1:-1]
                    break
            if revision is None:
                missing.append(path.name)
                continue
            if len(revision) > 32:
                too_long.append((path.name, revision, len(revision)))

        self.assertEqual(missing, [], f"Migrationer uden simpel revision-streng: {missing}")
        self.assertEqual(
            too_long,
            [],
            "Alembic revision skal passe i alembic_version.version_num VARCHAR(32): "
            f"{too_long}",
        )

    def test_baseline_contract_removes_all_reviewed_post_baseline_deltas(self) -> None:
        columns, constraints, indexes = runner._baseline_schema_contract()

        self.assertNotIn("livestream_viewer_lease", columns)
        self.assertNotIn("livestream_viewer_lease_pkey", constraints)
        self.assertNotIn("livestream_viewer_lease_client_id_fkey", constraints)
        self.assertNotIn("uq_livestream_viewer_lease_client_viewer", constraints)
        self.assertNotIn("livestream_viewer_lease_pkey", indexes)
        self.assertNotIn("uq_livestream_viewer_lease_client_viewer", indexes)
        self.assertNotIn("ix_livestream_viewer_lease_expires_at", indexes)
        self.assertNotIn("ix_livestream_viewer_lease_client_id", indexes)
        self.assertNotIn("request_id", columns["audit_logs"])
        self.assertNotIn("ix_audit_logs_request_id", indexes)
        self.assertNotIn("calendarmarking_client_season_unique", constraints)
        self.assertNotIn("calendarmarking_client_season_unique", indexes)
        self.assertIn("22:30", columns["organization"]["day_times"]["default"])
        self.assertIn("livestream_viewer_lease", runner.EXPECTED_COLUMNS)
        self.assertIn("livestream_viewer_lease_id_seq", runner.EXPECTED_SEQUENCES)
        self.assertIn("request_id", runner.EXPECTED_COLUMNS["audit_logs"])
        self.assertIn("calendarmarking_client_season_unique", runner.EXPECTED_CONSTRAINTS)
        self.assertIn("calendarmarking_client_season_unique", runner.EXPECTED_INDEXES)
        self.assertIn("20:00", runner.EXPECTED_COLUMNS["organization"]["day_times"]["default"])
        self.assertIn("ix_audit_logs_request_id", runner.EXPECTED_INDEXES)

        runtime_columns = {
            "client_version_patch", "client_version_updated_at",
            "ubuntu_update_status", "ubuntu_update_step", "ubuntu_update_message",
            "ubuntu_update_error", "ubuntu_update_started_at", "ubuntu_update_updated_at",
            "ubuntu_update_finished_at", "ubuntu_update_progress",
            "ubuntu_update_package_count", "ubuntu_update_reboot_required",
            "system_timezone", "ntp_enabled", "ntp_synchronized",
            "client_time_utc", "clock_drift_seconds", "time_sync_status",
            "time_sync_message",
        }
        self.assertTrue(runtime_columns.isdisjoint(columns["client"]))
        self.assertTrue(runtime_columns.issubset(runner.EXPECTED_COLUMNS["client"]))
        self.assertTrue(runner.ADOPTED_RUNTIME_TABLES.isdisjoint(columns))

    def test_empty_database_flag_runs_upgrade_then_exact_head_verification(self) -> None:
        calls: list[str] = []
        states = iter([
            _MigrationState(()),
            _MigrationState((runner.EXPECTED_HEAD_REVISION,)),
        ])

        def verify(_connection, **kwargs):
            calls.append("verify")
            self.assertEqual(kwargs.get("preserved_tables"), frozenset())
            self.assertFalse(kwargs.get("require_preserved_tables"))
            return {"user": 0}

        def upgrade(_cfg, revision):
            self.assertEqual(revision, "head")
            calls.append("upgrade")

        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), object(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            side_effect=lambda _connection: next(states),
        ), patch.object(
            runner,
            "_catalog_snapshot",
            return_value={"tables": set()},
        ), patch.object(
            runner,
            "_env_bool",
            side_effect=lambda name, default=False: name == "MIGRATION_ALLOW_EMPTY_DATABASE",
        ), patch.object(runner, "_verify_schema", side_effect=verify), patch.object(
            runner.command, "upgrade", side_effect=upgrade
        ):
            before, after, counts, adopted = runner._upgrade_and_verify(object())

        self.assertIsNone(before)
        self.assertEqual(after, runner.EXPECTED_HEAD_REVISION)
        self.assertEqual(counts, {"user": 0})
        self.assertFalse(adopted)
        self.assertEqual(calls, ["upgrade", "verify"])

    def test_existing_schema_requires_explicit_adoption_flag(self) -> None:
        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), object(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            return_value=_MigrationState(()),
        ), patch.object(
            runner,
            "_catalog_snapshot",
            return_value={"tables": set(runner.EXPECTED_TABLES)},
        ), patch.object(
            runner,
            "_env_bool",
            return_value=False,
        ), patch.object(runner.command, "stamp") as stamp:
            with self.assertRaisesRegex(RuntimeError, "MIGRATION_ADOPT_VERIFIED_BASELINE=true"):
                runner._upgrade_and_verify(object())

        stamp.assert_not_called()

    def test_verified_baseline_is_checked_before_stamp_and_upgrade(self) -> None:
        calls: list[str] = []
        states = iter(
            [
                _MigrationState(()),
                _MigrationState((runner.BASELINE_REVISION,)),
                _MigrationState((runner.EXPECTED_HEAD_REVISION,)),
            ]
        )

        def verify(_connection, **kwargs):
            label = kwargs.get("contract_label", "head")
            calls.append(f"verify:{label}")
            if label == "frossen baseline":
                expected_sequences = kwargs.get("expected_sequences", set())
                self.assertNotIn("livestream_viewer_lease_id_seq", expected_sequences)
                self.assertTrue(runner.LIVESTREAM_V2_SEQUENCES.isdisjoint(expected_sequences))
                self.assertTrue(
                    runner.LIVESTREAM_V2_TABLES.isdisjoint(kwargs["expected_columns"])
                )
            return {"user": 1}

        def stamp(_cfg, revision):
            self.assertEqual(revision, runner.BASELINE_REVISION)
            calls.append("stamp")

        def upgrade(_cfg, revision):
            self.assertEqual(revision, "head")
            calls.append("upgrade")

        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), object(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            side_effect=lambda _connection: next(states),
        ), patch.object(
            runner,
            "_catalog_snapshot",
            return_value={"tables": set(runner.EXPECTED_TABLES)},
        ), patch.object(
            runner,
            "_env_bool",
            side_effect=lambda name, default=False: name == "MIGRATION_ADOPT_VERIFIED_BASELINE",
        ), patch.object(runner, "_verify_schema", side_effect=verify), patch.object(
            runner.command, "stamp", side_effect=stamp
        ), patch.object(runner.command, "upgrade", side_effect=upgrade):
            before, after, counts, adopted = runner._upgrade_and_verify(object())

        self.assertIsNone(before)
        self.assertEqual(after, runner.EXPECTED_HEAD_REVISION)
        self.assertEqual(counts, {"user": 1})
        self.assertTrue(adopted)
        self.assertEqual(
            calls,
            ["verify:frossen baseline", "stamp", "upgrade", "verify:head"],
        )

    def test_pre_livestream_control_contract_is_exact_step_39a_shape(self) -> None:
        columns, constraints, indexes = runner._pre_livestream_control_schema_contract()

        for column_name in (
            
            
            "livestream_stop_reason",
            
        ):
            self.assertNotIn(column_name, columns["client"])
            self.assertIn(column_name, runner.EXPECTED_COLUMNS["client"])
        self.assertIn("livestream_viewer_lease", columns)
        self.assertTrue(runner.LIVESTREAM_V2_TABLES.isdisjoint(columns))
        self.assertTrue(
            all(not name.startswith(("livestream_v2_", "uq_livestream_v2_")) for name in constraints)
        )
        self.assertTrue(
            all(
                not name.startswith(("livestream_v2_", "ix_livestream_v2_", "uq_livestream_v2_"))
                for name in indexes
            )
        )
        self.assertLess(len(constraints), len(runner.EXPECTED_CONSTRAINTS))
        self.assertLess(len(indexes), len(runner.EXPECTED_INDEXES))

    def test_known_legacy_revision_is_verified_before_reconciliation(self) -> None:
        calls: list[str] = []
        states = iter(
            [
                _MigrationState((runner.RECOVERABLE_LEGACY_REVISION,)),
                _MigrationState((runner.RECOVERABLE_LEGACY_TARGET,)),
                _MigrationState((runner.EXPECTED_HEAD_REVISION,)),
            ]
        )

        class Revision:
            def __init__(self, down_revision=None):
                self.down_revision = down_revision

        class Script:
            def get_revision(self, revision):
                if revision == runner.RECOVERABLE_LEGACY_TARGET:
                    return Revision()
                if revision == runner.REVIEWED_LIVESTREAM_V2_PREDECESSOR:
                    return Revision(runner.RECOVERABLE_LEGACY_TARGET)
                if revision == runner.REVIEWED_LIVESTREAM_V2_REVISION:
                    return Revision(runner.REVIEWED_LIVESTREAM_V2_PREDECESSOR)
                if revision == runner.REVIEWED_TERMINAL_V2_REVISION:
                    return Revision(runner.REVIEWED_LIVESTREAM_V2_REVISION)
                if revision == runner.REVIEWED_TERMINAL_POLICY_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_V2_REVISION)
                if revision == runner.REVIEWED_TERMINAL_STORAGE_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_POLICY_REVISION)
                if revision == runner.REVIEWED_TERMINAL_CLIENT_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_STORAGE_REVISION)
                if revision == runner.REVIEWED_REMOTE_DESKTOP_V2_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_CLIENT_REVISION)
                if revision == runner.REVIEWED_CLIENT_ACTIVITY_REVISION:
                    return Revision(runner.REVIEWED_REMOTE_DESKTOP_V2_REVISION)
                if revision == runner.REVIEWED_LIFECYCLE_REVISION:
                    return Revision(runner.REVIEWED_CLIENT_ACTIVITY_REVISION)
                if revision == runner.REVIEWED_DATABASE_CONTRACT_REVISION:
                    return Revision(runner.REVIEWED_LIFECYCLE_REVISION)
                if revision == runner.REVIEWED_CANONICAL_FOUNDATIONS_REVISION:
                    return Revision(runner.REVIEWED_DATABASE_CONTRACT_REVISION)
                if revision == runner.REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION:
                    return Revision(runner.REVIEWED_CANONICAL_FOUNDATIONS_REVISION)
                if revision == runner.REVIEWED_CLIENTFLOW_UPDATE_AUTH_REVISION:
                    return Revision(runner.REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION)
                if revision == runner.REVIEWED_CLIENT_LIVENESS_REVISION:
                    return Revision(runner.REVIEWED_CLIENTFLOW_UPDATE_AUTH_REVISION)
                if revision == runner.REVIEWED_DISPLAY_AUTHORITY_REVISION:
                    return Revision(runner.REVIEWED_CLIENT_LIVENESS_REVISION)
                if revision == runner.REVIEWED_SYSTEM_AUTHORITY_REVISION:
                    return Revision(runner.REVIEWED_DISPLAY_AUTHORITY_REVISION)
                raise AssertionError(f"unexpected revision lookup: {revision}")

        def verify(_connection, **kwargs):
            label = kwargs.get("contract_label", "head")
            calls.append(f"verify:{label}")
            if label.startswith("legacy "):
                for column_name in (
                    
                    
                    "livestream_stop_reason",
                    
                ):
                    self.assertNotIn(column_name, kwargs["expected_columns"]["client"])
                self.assertEqual(
                    kwargs.get("preserved_tables"),
                    runner.RECOVERABLE_LEGACY_PRESERVED_TABLES,
                )
                self.assertTrue(kwargs.get("require_preserved_tables"))
            elif label == "head":
                self.assertEqual(
                    kwargs.get("preserved_tables"),
                    runner.HEAD_LEGACY_PRESERVED_TABLES,
                )
                self.assertTrue(kwargs.get("require_preserved_tables"))
            return {"user": 1}

        def rewrite(_connection, *, expected_current, target_revision):
            self.assertEqual(expected_current, runner.RECOVERABLE_LEGACY_REVISION)
            self.assertEqual(target_revision, runner.RECOVERABLE_LEGACY_TARGET)
            calls.append("rewrite-marker")

        def upgrade(_cfg, revision):
            self.assertEqual(revision, "head")
            calls.append("upgrade")

        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), Script(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            side_effect=lambda _connection: next(states),
        ), patch.object(runner, "_verify_schema", side_effect=verify), patch.object(
            runner, "_rewrite_verified_legacy_revision_marker", side_effect=rewrite
        ), patch.object(runner.command, "upgrade", side_effect=upgrade):
            before, after, counts, adopted = runner._upgrade_and_verify(object())

        self.assertEqual(before, runner.RECOVERABLE_LEGACY_REVISION)
        self.assertEqual(after, runner.EXPECTED_HEAD_REVISION)
        self.assertEqual(counts, {"user": 1})
        self.assertFalse(adopted)
        self.assertEqual(
            calls,
            [
                (
                    f"verify:legacy {runner.RECOVERABLE_LEGACY_REVISION} som Step 39A "
                    "med bevarede legacy-tabeller"
                ),
                "rewrite-marker",
                "upgrade",
                "verify:head",
            ],
        )


    def test_verified_legacy_marker_rewrite_locks_checks_and_rewrites_exact_row(self) -> None:
        class Result(list):
            def __init__(self, rows=(), rowcount=-1):
                super().__init__(rows)
                self.rowcount = rowcount

        class Connection:
            def __init__(self):
                self.version = runner.RECOVERABLE_LEGACY_REVISION
                self.sql: list[str] = []

            def execute(self, statement, params=None):
                sql = " ".join(str(statement).split())
                self.sql.append(sql)
                if sql == "SELECT version_num FROM alembic_version FOR UPDATE":
                    return Result([(self.version,)])
                if sql.startswith("UPDATE alembic_version SET version_num = :target"):
                    self.assert_params(params)
                    if self.version != params["expected"]:
                        return Result(rowcount=0)
                    self.version = params["target"]
                    return Result(rowcount=1)
                if sql == "SELECT version_num FROM alembic_version":
                    return Result([(self.version,)])
                raise AssertionError(f"unexpected SQL: {sql}")

            @staticmethod
            def assert_params(params):
                if params != {
                    "target": runner.RECOVERABLE_LEGACY_TARGET,
                    "expected": runner.RECOVERABLE_LEGACY_REVISION,
                }:
                    raise AssertionError(f"unexpected params: {params}")

        connection = Connection()
        runner._rewrite_verified_legacy_revision_marker(
            connection,
            expected_current=runner.RECOVERABLE_LEGACY_REVISION,
            target_revision=runner.RECOVERABLE_LEGACY_TARGET,
        )

        self.assertEqual(connection.version, runner.RECOVERABLE_LEGACY_TARGET)
        self.assertEqual(
            connection.sql,
            [
                "SELECT version_num FROM alembic_version FOR UPDATE",
                "UPDATE alembic_version SET version_num = :target WHERE version_num = :expected",
                "SELECT version_num FROM alembic_version",
            ],
        )

    def test_verified_legacy_marker_rewrite_fails_before_update_if_marker_changed(self) -> None:
        class Result(list):
            rowcount = -1

        class Connection:
            def __init__(self):
                self.update_seen = False

            def execute(self, statement, params=None):
                sql = " ".join(str(statement).split())
                if sql == "SELECT version_num FROM alembic_version FOR UPDATE":
                    return Result([("different_revision",)])
                if sql.startswith("UPDATE alembic_version"):
                    self.update_seen = True
                raise AssertionError(f"unexpected SQL after mismatch: {sql}")

        connection = Connection()
        with self.assertRaisesRegex(RuntimeError, "marker ændrede sig"):
            runner._rewrite_verified_legacy_revision_marker(
                connection,
                expected_current=runner.RECOVERABLE_LEGACY_REVISION,
                target_revision=runner.RECOVERABLE_LEGACY_TARGET,
            )
        self.assertFalse(connection.update_seen)


    def test_legacy_preserved_table_set_matches_observed_production_catalog(self) -> None:
        self.assertEqual(
            runner.RECOVERABLE_LEGACY_PRESERVED_TABLES,
            frozenset({
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
            }),
        )
        self.assertEqual(
            runner.HEAD_LEGACY_PRESERVED_TABLES,
            frozenset({
                "browser_websocket_ticket",
                "livestream_generation",
            }),
        )
        self.assertTrue(
            runner.ADOPTED_RUNTIME_TABLES.isdisjoint(runner.HEAD_LEGACY_PRESERVED_TABLES)
        )

    def test_head_recognises_only_the_complete_reviewed_legacy_table_set(self) -> None:
        base = set(runner.EXPECTED_TABLES) | {"alembic_version"}
        with patch.object(
            runner,
            "_catalog_snapshot",
            return_value={
                "tables": base | set(runner.HEAD_LEGACY_PRESERVED_TABLES)
            },
        ):
            self.assertEqual(
                runner._known_legacy_tables_at_head(object()),
                runner.HEAD_LEGACY_PRESERVED_TABLES,
            )

        partial = set(runner.HEAD_LEGACY_PRESERVED_TABLES) - {"livestream_generation"}
        with patch.object(
            runner,
            "_catalog_snapshot",
            return_value={"tables": base | partial},
        ):
            self.assertEqual(runner._known_legacy_tables_at_head(object()), frozenset())

    def test_known_predecessor_preserves_reviewed_legacy_tables_through_upgrade(self) -> None:
        calls: list[tuple[str, object, object]] = []
        states = iter([
            _MigrationState((runner.REVIEWED_LIVESTREAM_V2_PREDECESSOR,)),
            _MigrationState((runner.EXPECTED_HEAD_REVISION,)),
        ])

        def verify(_connection, **kwargs):
            calls.append((
                kwargs.get("contract_label", "head"),
                kwargs.get("preserved_tables"),
                kwargs.get("require_preserved_tables"),
            ))
            return {"user": 1}

        class Script:
            def get_revision(self, revision):
                if revision in {
                    runner.REVIEWED_LIVESTREAM_V2_PREDECESSOR,
                    runner.EXPECTED_HEAD_REVISION,
                }:
                    return object()
                raise AssertionError(f"unexpected revision lookup: {revision}")

        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), Script(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            side_effect=lambda _connection: next(states),
        ), patch.object(
            runner,
            "_known_legacy_tables_at_head",
            return_value=runner.HEAD_LEGACY_PRESERVED_TABLES,
        ) as known_legacy, patch.object(
            runner, "_verify_schema", side_effect=verify
        ), patch.object(runner.command, "upgrade") as upgrade:
            before, after, counts, adopted = runner._upgrade_and_verify(object())

        self.assertEqual(before, runner.REVIEWED_LIVESTREAM_V2_PREDECESSOR)
        self.assertEqual(after, runner.EXPECTED_HEAD_REVISION)
        self.assertEqual(counts, {"user": 1})
        self.assertFalse(adopted)
        known_legacy.assert_called_once()
        upgrade.assert_called_once()
        self.assertEqual(upgrade.call_args.args[1], "head")
        self.assertEqual(
            calls,
            [
                (
                    "head",
                    runner.HEAD_LEGACY_PRESERVED_TABLES,
                    True,
                ),
            ],
        )

    def test_reconciled_head_keeps_preserving_legacy_tables_on_later_deploys(self) -> None:
        calls: list[tuple[str, object, object]] = []
        states = iter([
            _MigrationState((runner.EXPECTED_HEAD_REVISION,)),
            _MigrationState((runner.EXPECTED_HEAD_REVISION,)),
        ])

        def verify(_connection, **kwargs):
            calls.append((
                kwargs.get("contract_label", "head"),
                kwargs.get("preserved_tables"),
                kwargs.get("require_preserved_tables"),
            ))
            return {"user": 1}

        class Script:
            def get_revision(self, revision):
                if revision != runner.EXPECTED_HEAD_REVISION:
                    raise AssertionError(f"unexpected revision lookup: {revision}")
                return object()

        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), Script(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            side_effect=lambda _connection: next(states),
        ), patch.object(
            runner,
            "_known_legacy_tables_at_head",
            return_value=runner.HEAD_LEGACY_PRESERVED_TABLES,
        ), patch.object(runner, "_verify_schema", side_effect=verify), patch.object(
            runner.command, "upgrade"
        ) as upgrade:
            before, after, counts, adopted = runner._upgrade_and_verify(object())

        self.assertEqual(before, runner.EXPECTED_HEAD_REVISION)
        self.assertEqual(after, runner.EXPECTED_HEAD_REVISION)
        self.assertEqual(counts, {"user": 1})
        self.assertFalse(adopted)
        upgrade.assert_called_once()
        self.assertEqual(upgrade.call_args.args[1], "head")
        self.assertEqual(
            calls,
            [
                (
                    "head",
                    runner.HEAD_LEGACY_PRESERVED_TABLES,
                    True,
                ),
                (
                    "head",
                    runner.HEAD_LEGACY_PRESERVED_TABLES,
                    True,
                ),
            ],
        )


    def test_schema_verifier_ignores_only_objects_owned_by_preserved_tables(self) -> None:
        legacy_table = next(iter(runner.HEAD_LEGACY_PRESERVED_TABLES))
        snapshot = {
            "tables": (
                set(runner.EXPECTED_TABLES)
                | {"alembic_version"}
                | set(runner.HEAD_LEGACY_PRESERVED_TABLES)
            ),
            "columns": {table: dict(columns) for table, columns in runner.EXPECTED_COLUMNS.items()},
            "constraints": dict(runner.EXPECTED_CONSTRAINTS) | {"legacy_only_fk": "FOREIGN KEY (x) REFERENCES client(id)"},
            "constraint_tables": {
                **{name: None for name in runner.EXPECTED_CONSTRAINTS},
                "legacy_only_fk": legacy_table,
            },
            "indexes": dict(runner.EXPECTED_INDEXES) | {
                "legacy_only_idx": f"CREATE INDEX legacy_only_idx ON public.{legacy_table} USING btree (id)"
            },
            "index_tables": {
                **{name: None for name in runner.EXPECTED_INDEXES},
                "legacy_only_idx": legacy_table,
            },
            "sequences": set(runner.EXPECTED_SEQUENCES) | {"legacy_only_id_seq"},
            "sequence_tables": {
                **{name: None for name in runner.EXPECTED_SEQUENCES},
                "legacy_only_id_seq": legacy_table,
            },
            "triggers": {"legacy_only_trigger"},
            "trigger_tables": {"legacy_only_trigger": legacy_table},
            "extensions": set(runner.EXPECTED_EXTENSION_NAMES),
        }

        class Connection:
            def scalar(self, *_args, **_kwargs):
                return 0

        with patch.object(runner, "_catalog_snapshot", return_value=snapshot):
            counts = runner._verify_schema(
                Connection(),
                preserved_tables=runner.HEAD_LEGACY_PRESERVED_TABLES,
                require_preserved_tables=True,
            )
        self.assertEqual(counts["client"], 0)

        snapshot["constraint_tables"]["legacy_only_fk"] = "client"
        with patch.object(runner, "_catalog_snapshot", return_value=snapshot):
            with self.assertRaisesRegex(RuntimeError, "constraints-afvigelse"):
                runner._verify_schema(
                    Connection(),
                    preserved_tables=runner.RECOVERABLE_LEGACY_PRESERVED_TABLES,
                    require_preserved_tables=True,
                )

    def test_known_legacy_revision_fails_closed_on_schema_mismatch(self) -> None:
        class Revision:
            def __init__(self, down_revision=None):
                self.down_revision = down_revision

        class Script:
            def get_revision(self, revision):
                if revision == runner.RECOVERABLE_LEGACY_TARGET:
                    return Revision()
                if revision == runner.REVIEWED_LIVESTREAM_V2_PREDECESSOR:
                    return Revision(runner.RECOVERABLE_LEGACY_TARGET)
                if revision == runner.REVIEWED_LIVESTREAM_V2_REVISION:
                    return Revision(runner.REVIEWED_LIVESTREAM_V2_PREDECESSOR)
                if revision == runner.REVIEWED_TERMINAL_V2_REVISION:
                    return Revision(runner.REVIEWED_LIVESTREAM_V2_REVISION)
                if revision == runner.REVIEWED_TERMINAL_POLICY_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_V2_REVISION)
                if revision == runner.REVIEWED_TERMINAL_STORAGE_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_POLICY_REVISION)
                if revision == runner.REVIEWED_TERMINAL_CLIENT_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_STORAGE_REVISION)
                if revision == runner.REVIEWED_REMOTE_DESKTOP_V2_REVISION:
                    return Revision(runner.REVIEWED_TERMINAL_CLIENT_REVISION)
                if revision == runner.REVIEWED_CLIENT_ACTIVITY_REVISION:
                    return Revision(runner.REVIEWED_REMOTE_DESKTOP_V2_REVISION)
                if revision == runner.REVIEWED_LIFECYCLE_REVISION:
                    return Revision(runner.REVIEWED_CLIENT_ACTIVITY_REVISION)
                if revision == runner.REVIEWED_DATABASE_CONTRACT_REVISION:
                    return Revision(runner.REVIEWED_LIFECYCLE_REVISION)
                if revision == runner.REVIEWED_CANONICAL_FOUNDATIONS_REVISION:
                    return Revision(runner.REVIEWED_DATABASE_CONTRACT_REVISION)
                if revision == runner.REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION:
                    return Revision(runner.REVIEWED_CANONICAL_FOUNDATIONS_REVISION)
                if revision == runner.REVIEWED_CLIENTFLOW_UPDATE_AUTH_REVISION:
                    return Revision(runner.REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION)
                if revision == runner.REVIEWED_CLIENT_LIVENESS_REVISION:
                    return Revision(runner.REVIEWED_CLIENTFLOW_UPDATE_AUTH_REVISION)
                if revision == runner.REVIEWED_DISPLAY_AUTHORITY_REVISION:
                    return Revision(runner.REVIEWED_CLIENT_LIVENESS_REVISION)
                if revision == runner.REVIEWED_SYSTEM_AUTHORITY_REVISION:
                    return Revision(runner.REVIEWED_DISPLAY_AUTHORITY_REVISION)
                raise AssertionError(f"unexpected revision lookup: {revision}")

        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), Script(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            return_value=_MigrationState((runner.RECOVERABLE_LEGACY_REVISION,)),
        ), patch.object(
            runner,
            "_verify_schema",
            side_effect=RuntimeError("schema mismatch"),
        ), patch.object(
            runner, "_rewrite_verified_legacy_revision_marker"
        ) as rewrite_marker, patch.object(runner.command, "upgrade") as upgrade:
            with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
                runner._upgrade_and_verify(object())

        rewrite_marker.assert_not_called()
        upgrade.assert_not_called()

    def test_other_unknown_revision_still_fails_closed(self) -> None:
        class Script:
            def get_revision(self, revision):
                raise runner.CommandError(f"unknown {revision}")

        with patch.object(
            runner,
            "_alembic_config",
            return_value=(object(), Script(), runner.EXPECTED_HEAD_REVISION),
        ), patch.object(
            runner.MigrationContext,
            "configure",
            return_value=_MigrationState(("totally_unknown",)),
        ), patch.object(runner.command, "stamp") as stamp, patch.object(
            runner.command, "upgrade"
        ) as upgrade:
            with self.assertRaisesRegex(RuntimeError, "ukendt Alembic-revision 'totally_unknown'"):
                runner._upgrade_and_verify(object())

        stamp.assert_not_called()
        upgrade.assert_not_called()


if __name__ == "__main__":
    unittest.main()
