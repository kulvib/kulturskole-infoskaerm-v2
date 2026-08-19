from __future__ import annotations

import ast
from pathlib import Path
import unittest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def read_backend(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding="utf-8")


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class LivestreamV2IsolationSourceTests(unittest.TestCase):
    def test_v2_runtime_does_not_import_terminal_or_remote_desktop(self) -> None:
        for relative in ("service1/livestream_v2.py", "service1/routers/livestream_v2.py"):
            modules = imported_modules(read_backend(relative))
            self.assertFalse(any("terminal" in name for name in modules), (relative, modules))
            self.assertFalse(any("remote_desktop" in name for name in modules), (relative, modules))

    def test_v2_owns_only_prefixed_database_tables(self) -> None:
        source = read_backend("service1/livestream_v2_models.py")
        tree = ast.parse(source)
        table_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            table_names.add(node.value.value)
        self.assertEqual(
            table_names,
            {
                "livestream_v2_credential",
                "livestream_v2_command",
                "livestream_v2_agent_status",
                "livestream_v2_viewer",
                "livestream_v2_generation",
            },
        )
        self.assertTrue(all(name.startswith("livestream_v2_") for name in table_names))

    def test_physical_clientflow_12_agent_contract_is_exposed(self) -> None:
        source = read_backend("service1/routers/livestream_v2.py")
        for route in (
            '"/livestream-agent/clients/{client_id}/commands/claim"',
            '"/livestream-agent/clients/{client_id}/commands/{command_id}/renew"',
            '"/livestream-agent/clients/{client_id}/commands/{command_id}/complete"',
            '"/livestream-agent/clients/{client_id}/commands/{command_id}/fail"',
            '"/livestream-agent/clients/{client_id}/status"',
            '"/livestream-agent/clients/{client_id}/generations/{generation_id}/started"',
            '"/livestream-agent/clients/{client_id}/generations/{generation_id}/stopped"',
            '"/livestream-agent/clients/{client_id}/generations/{generation_id}/files/{filename}"',
        ):
            self.assertIn(route, source)

    def test_shared_client_token_path_is_not_owned_by_livestream_router(self) -> None:
        router = read_backend("service1/routers/livestream_v2.py")
        compat = read_backend("service1/routers/client_auth_compat.py")
        self.assertNotIn('/client-auth/token', router)
        self.assertIn('@router.post("/client-auth/token")', compat)
        self.assertIn('if body.domain == "livestream":', compat)
        self.assertNotIn('if body.domain == "terminal":', compat)
        self.assertNotIn("issue_terminal_token_response", compat)

    def test_viewer_owned_lifecycle_defaults_match_physical_acceptance(self) -> None:
        source = read_backend("service1/livestream_v2.py")
        self.assertIn('LIVESTREAM_V2_VIEWER_HEARTBEAT_SECONDS", "10"', source)
        self.assertIn('LIVESTREAM_V2_VIEWER_LEASE_SECONDS", "30"', source)
        self.assertIn('LIVESTREAM_V2_VIEWER_STOP_GRACE_SECONDS", "30"', source)
        self.assertIn('LIVESTREAM_V2_VIEWER_SWEEP_SECONDS", "5"', source)

    def test_token_boundary_does_not_claim_other_clientflow_domains(self) -> None:
        source = read_backend("service1/livestream_v2.py")
        self.assertIn("if domain != DOMAIN:", source)
        self.assertIn('status_code=404, detail="Domæne-endpoint ikke fundet"', source)

    def test_finalized_livestream_auth_has_no_temporary_bypass(self) -> None:
        service = read_backend("service1/livestream_v2.py")
        router = read_backend("service1/routers/livestream_v2.py")
        render = (REPO / "render.yaml").read_text(encoding="utf-8")

        for source in (service, router, render):
            self.assertNotIn("LIVESTREAM_V2_TEST_AUTH_BYPASS_CLIENT_ID", source)
            self.assertNotIn("livestream_v2_test_auth_bypass", source)
            self.assertNotIn("create_test_client_token", source)
            self.assertNotIn("test_auth_bypass_enabled", source)

        self.assertIn("authenticate_credential", router)
        self.assertIn("create_client_token", router)
        self.assertIn("LIVESTREAM_V2_CREDENTIAL_PEPPER", render)

    def test_hls_playlist_is_served_from_an_immutable_snapshot(self) -> None:
        source = read_backend("service1/main.py")
        class_start = source.index("class AuthenticatedHLSStaticFiles")
        mount_start = source.index('app.mount("/hls"', class_start)
        block = source[class_start:mount_start]

        self.assertIn("Path(full_path).read_bytes", block)
        self.assertIn('Response(content=payload, media_type="application/vnd.apple.mpegurl")', block)
        self.assertIn("await asyncio.to_thread(self.lookup_path, path)", block)

    def test_browser_control_auth_matches_frontend_operator_roles_without_hls_write_access(self) -> None:
        router = read_backend("service1/routers/livestream_v2.py")
        frontend = (
            REPO / "frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn('const canControlStream = ["superadmin", "admin", "bruger"].includes(role);', frontend)
        self.assertIn('def _require_browser_control_access(user: object, client_id: str) -> None:', router)
        self.assertIn('require_hls_access(user, client_id)', router)
        self.assertIn('getattr(user, "is_superadmin", False)', router)
        self.assertIn('getattr(user, "is_admin", False)', router)
        self.assertIn('getattr(user, "role", None) == "bruger"', router)

        start = router.index('def browser_command(')
        command_block = router[start:]
        self.assertIn('_require_browser_control_access(user, client_id)', command_block)
        self.assertNotIn('require_hls_access(user, client_id, write=True)', command_block)

    def test_frontend_uses_v2_presence_without_health_autostart(self) -> None:
        source = (REPO / "frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("const VIEWER_HEARTBEAT_MS = 10_000;", source)
        self.assertIn("/api/livestream-v2/hls/", source)
        self.assertIn("/api/livestream-v2/clients/", source)
        self.assertNotIn('ensureStreamStarted("missing_segments")', source)
        self.assertIn("/segment[-_](\\d+)/", source)

    def test_livestream_core_is_not_blocked_by_legacy_global_online_status(self) -> None:
        source = (REPO / "frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx").read_text(
            encoding="utf-8"
        )

        viewer_start = source.index("// Viewer-owned lifecycle: 10s heartbeat")
        health_start = source.index("// Poll /health", viewer_start)
        hls_start = source.index("// HLS.js lifecycle", health_start)
        segment_start = source.index("// Backend polling — hvert 2s", hls_start)
        watchdog_start = source.index("// Stale watchdog", segment_start)
        playback_start = source.index("// Playback watchdog", watchdog_start)
        lag_start = source.index("// Forsinkelsesberegning", playback_start)

        for name, block in (
            ("viewer", source[viewer_start:health_start]),
            ("health", source[health_start:hls_start]),
            ("hls", source[hls_start:segment_start]),
            ("segment", source[segment_start:watchdog_start]),
            ("stale_watchdog", source[watchdog_start:playback_start]),
            ("playback_watchdog", source[playback_start:lag_start]),
        ):
            self.assertNotIn("clientOnline", block, name)

        self.assertIn(
            "const livestreamVisuallyOffline = clientOnline === false && !serverReady && !manifestReady;",
            source,
        )

    def test_livestream_frontend_has_no_manual_start_stop_state_or_buttons(self) -> None:
        source = (REPO / "frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx").read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "Start livestream",
            "Stop livestream",
            "handleExplicitStart",
            "handleExplicitStop",
            "localExplicitStop",
            "explicitlyStopped",
        ):
            self.assertNotIn(forbidden, source)

        self.assertIn("Viewer-presence ejer Livestream-v2 lifecycle server-side", source)
        self.assertIn("viewer-heartbeat", source)

    def test_viewer_presence_effect_is_not_torn_down_by_legacy_server_stop_state(self) -> None:
        source = (REPO / "frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx").read_text(
            encoding="utf-8"
        )
        viewer_start = source.index("// Viewer-owned lifecycle: 10s heartbeat")
        health_start = source.index("// Poll /health", viewer_start)
        viewer_block = source[viewer_start:health_start]

        self.assertNotIn("localExplicitStop", viewer_block)
        self.assertNotIn("explicitlyStopped", viewer_block)
        self.assertIn("[clientId, inactivityStopped]", viewer_block)

    def test_retryable_stop_timeout_is_not_stale_while_generation_is_stopping(self) -> None:
        source = read_backend("service1/livestream_v2.py")
        start = source.index("def fail_command(")
        end = source.index("def ensure_current_generation(", start)
        fail_block = source[start:end]

        self.assertIn('generation.state == "superseded"', fail_block)
        self.assertIn('(generation.state == "stopping" and command.command_type != "stop")', fail_block)
        self.assertIn("retryable and not stale_generation and command.attempts < COMMAND_MAX_ATTEMPTS", fail_block)

    def test_completed_retry_clears_old_command_error_metadata(self) -> None:
        source = read_backend("service1/livestream_v2.py")
        start = source.index("def complete_command(")
        end = source.index("def fail_command(", start)
        complete_block = source[start:end]

        self.assertIn("command.error_code = None", complete_block)
        self.assertIn("command.error_message = None", complete_block)
        self.assertIn("command.retryable = None", complete_block)


    def test_agent_status_reconciles_only_physically_quiesced_stopping_generation(self) -> None:
        service = read_backend("service1/livestream_v2.py")
        router = read_backend("service1/routers/livestream_v2.py")
        start = service.index("def reconcile_stopping_generation_from_agent_status(")
        end = service.index("def update_agent_status(", start)
        reconcile_block = service[start:end]

        for required in (
            'generation.state != "stopping"',
            'producer_generation = str(producer.get("generation_id") or "")',
            'if producer_generation and producer_generation != generation.id:',
            'uploader_generation = str(uploader.get("generation_id") or "")',
            'if uploader_generation and uploader_generation != generation.id:',
            'previous = session.get(LivestreamV2Generation, uploader_generation)',
            'previous.client_id != client_id',
            'previous.state not in FINAL_GENERATION_STATES',
            'producer.get("state")',
            'producer.get("pid") is not None',
            'uploader.get("state")',
            'LivestreamV2Command.state == "leased"',
            'LivestreamV2Command.state == "queued"',
            'command.state = "cancelled"',
            'generation_stopped(',
            'active_viewer_count(session, client_id) > 0',
            'active_livestream_activity_count(session, client_id) > 0',
            '"viewer_returned_during_recovery"',
            '"client_activity_returned_during_recovery"',
        ):
            self.assertIn(required, reconcile_block)

        producer = (
            REPO
            / "client/runtime/clientflow_runtime/livestream_producer.py"
        ).read_text(encoding="utf-8")
        producer_stop = producer[producer.index("    def _stop(self) -> None:"):producer.index("    def _session_properties", producer.index("    def _stop(self) -> None:"))]
        self.assertIn('self._status("stopped")', producer_stop)
        self.assertIn("self.generation_id = None", producer_stop)

        self.assertIn("reconcile_stopping_generation_from_agent_status", router)
        self.assertIn("FINAL_GENERATION_STATES", service)
        self.assertIn('return {"ok": True, "recovery_enqueued": recovered}', router)

    def test_step_41a_migration_is_additive_and_livestream_prefixed(self) -> None:
        source = read_backend("migrations/versions/20260814_41a_livestream_v2_isolated.py")
        tree = ast.parse(source)
        self.assertIn('down_revision = "20260814_40a_livestream_control"', source)
        create_tables: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_table":
                if node.args and isinstance(node.args[0], ast.Constant):
                    create_tables.append(str(node.args[0].value))
        self.assertEqual(len(create_tables), 5)
        self.assertTrue(all(name.startswith("livestream_v2_") for name in create_tables))


def test_agent_upload_authenticates_before_bounded_body_read():
    router_source = read_backend("service1/routers/livestream_v2.py")
    service_source = read_backend("service1/livestream_v2.py")

    assert "MAX_HLS_FILE_BYTES = 64 * 1024 * 1024" in service_source
    assert "if len(payload) > MAX_HLS_FILE_BYTES:" in service_source
    assert "async def _read_bounded_body" in router_source
    assert "request.stream()" in router_source
    assert "await request.body()" not in router_source

    upload_start = router_source.index("async def agent_upload_file(")
    upload_end = router_source.index("\n\n@router.post", upload_start)
    upload_source = router_source[upload_start:upload_end]
    assert upload_source.index("require_agent_token(auth_session") < upload_source.index("_read_bounded_body(")
    assert "maximum=MAX_HLS_FILE_BYTES" in upload_source


if __name__ == "__main__":
    unittest.main()
