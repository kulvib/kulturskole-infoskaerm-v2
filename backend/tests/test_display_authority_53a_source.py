from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_53a_remains_reviewed_predecessor_under_53b_system_authority():
    migration = read("backend/migrations/versions/20260823_53a_display_authority.py")
    contract = read("backend/scripts/display_schema_contract.py")
    runner = read("backend/scripts/run_migrations.py")
    model = read("backend/service1/client_domain_models.py")

    assert 'revision = "20260823_53a_display_authority"' in migration
    assert 'down_revision = "20260822_52a_client_liveness"' in migration
    assert '"display_desired_configuration"' in migration
    assert '_require_legacy_kiosk_urls_canonical()' in migration
    assert 'host in {"localhost", "127.0.0.1"}' in migration
    assert 'op.drop_column("client", "kiosk_url")' in migration
    assert 'op.drop_column("client", "browser_refresh_interval_sec")' in migration
    assert 'class DisplayDesiredConfiguration(SQLModel, table=True):' in model
    assert contract.rsplit("EXPECTED_HEAD_REVISION = ", 1)[1].splitlines()[0] == '"20260823_53b_system_authority"'
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260823_53b_system_authority"' in runner
    assert 'REVIEWED_LEGACY_RECONCILIATION_HEAD = "20260823_53b_system_authority"' in runner
    assert 'REVIEWED_DISPLAY_AUTHORITY_REVISION = "20260823_53a_display_authority"' in runner
    assert 'display_authority_revision = script.get_revision(REVIEWED_DISPLAY_AUTHORITY_REVISION)' in runner
    assert 'display_authority_revision.down_revision != REVIEWED_CLIENT_LIVENESS_REVISION' in runner
    assert 'REVIEWED_SYSTEM_AUTHORITY_REVISION = "20260823_53b_system_authority"' in runner
    assert 'system_authority_revision = script.get_revision(REVIEWED_SYSTEM_AUTHORITY_REVISION)' in runner
    assert 'system_authority_revision.down_revision != REVIEWED_DISPLAY_AUTHORITY_REVISION' in runner
    assert 'head != REVIEWED_SYSTEM_AUTHORITY_REVISION' in runner


def test_client_aggregate_no_longer_has_display_config_storage_fields():
    models = read("backend/service1/models.py")
    client_table = models[models.index("class Client(ClientBase, table=True):"):models.index("class ClientRead", models.index("class Client(ClientBase, table=True):"))]
    assert "kiosk_url:" not in client_table
    assert "browser_refresh_interval_sec" not in client_table
    # Response/input compatibility may still expose kiosk_url, but the fake
    # auto-refresh contract is removed everywhere.
    assert "browser_refresh_interval_sec" not in models


def test_backend_display_producer_is_durable_version_gated_and_reconciled():
    display = read("backend/service1/display_control.py")
    clients = read("backend/service1/routers/clients.py")
    shared = read("backend/service1/shared_domain.py")
    shared_router = read("backend/service1/routers/shared_domain.py")

    assert 'DISPLAY_MIN_COMMAND_AGENT_VERSION = "1.3.5"' in display
    assert 'query = query.with_for_update()' in display
    assert 'select(Client.id).where(Client.id == client_id).with_for_update()' in display
    assert 'lock_display_client(session, client_id)' in display
    assert 'desired = get_display_desired_configuration(session, client_id, for_update=True)' in display
    assert 'command_type="apply_configuration"' in display
    assert 'ClientCommand.domain == DISPLAY_DOMAIN' in display
    assert 'ClientCommand.expires_at > utcnow()' in display
    assert 'len(raw) > 2048' in display
    assert 'parsed.scheme.lower() == "http" and host in {"localhost", "127.0.0.1"}' in display

    assert 'set_display_desired_kiosk_url(' in clients
    assert 'client.kiosk_url =' not in clients
    assert 'lock_display_client(session, id)' in clients
    assert 'queue_display_command(' in clients
    assert 'command_type, payload = "reset_browser", {}' in clients
    assert 'command_type, payload = "set_display_power", {"state": "off"}' in clients
    assert 'command_type, payload = "set_display_power", {"state": "on"}' in clients
    assert 'client.pending_chrome_action = chrome_action' not in clients

    assert 'display_agent_supports_commands' in shared
    assert 'return {"claimed": None}' in shared
    assert 'reconcile_display_configuration(' in shared_router


def test_display_runtime_is_google_chrome_wayland_only_with_exact_reset_boundary():
    runtime = read("client/runtime/clientflow_runtime/display_runtime.py")
    agent = read("client/runtime/clientflow_runtime/display_agent.py")
    command_agent = read("client/runtime/clientflow_runtime/command_agent.py")

    assert 'Path("/usr/bin/google-chrome-stable")' in runtime
    assert '"/var/lib/clientflow/display-runtime"' in runtime
    assert "chromium" not in runtime.lower()
    assert "browser_refresh_interval_sec" not in runtime
    assert "browser_binary" not in runtime
    assert "browser_arguments" not in runtime
    assert 'configuration["revision"] == current_revision' in runtime
    assert "display_environment" not in runtime
    assert 'len(raw) > 2048' in runtime
    assert 'host in {"localhost", "127.0.0.1"}' in runtime
    assert 'props["Type"] != "wayland"' in runtime
    assert 'PROFILE_DIR' in runtime and 'shutil.rmtree' in runtime
    assert 'self.browser_requested = bool(self.configuration.get("kiosk_url"))' in runtime
    assert 'self.next_start_attempt = time.monotonic() + 5.0' in runtime
    assert 'self.stop_browser(preserve_request=True)' in runtime
    assert 'and time.monotonic() >= self.next_start_attempt' in runtime
    assert '_status("waiting_session"' in runtime
    assert '"reset_browser"' in runtime
    assert "remote-debugging" not in runtime

    assert '"/var/lib/clientflow/display-runtime/runtime-status.json"' in agent
    assert '"set_display_power"' in agent
    assert '"display_power"' in agent
    assert "report_status_after_command=True" in agent
    assert "report_status_after_command" in command_agent


def test_frontend_has_single_transaction_kiosk_write_and_no_fake_auto_refresh():
    frontend = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")
    assert "browser_refresh_interval_sec" not in frontend
    assert "Browser auto-refresh" not in frontend
    assert "isCanonicalKioskUrl" in frontend
    assert 'raw.length > 2048' in frontend
    assert '["localhost", "127.0.0.1"].includes(parsed.hostname.toLowerCase())' in frontend
    assert "payload.kiosk_url = nextKioskUrl" in frontend
    # The mixed client update remains one apiUpdateClient request; kiosk URL is
    # not split into a second frontend transaction.
    assert "apiUpdateKioskUrl" not in frontend


def test_release_identity_and_chrome_lock_are_exact_1209_inputs():
    assert read("client/VERSION").strip() == "1.3.8"
    release_input = json.loads(read("client/release/release-input.json"))
    assert release_input["release_sequence"] == 1209
    lock = json.loads(read("client/release/runtime-platform-inputs.lock.json"))
    assert lock["schema_version"] == 1
    assert lock["platform_artifacts"] == [{
        "file": "google-chrome-stable_151.0.7922.173-1_amd64.deb",
        "package": "google-chrome-stable",
        "version": "151.0.7922.173-1",
        "architecture": "amd64",
        "size": 140077524,
        "sha256": "878e5ab495b8a694980fca61bc09b37e651ccedce2291c73434d16e48a2646fd",
    }]
    builder = read("client/release/lib/clientflow_release/builder.py")
    assert 'runtime-inputs/platform/runtime-platform-inputs.lock.json' in builder
    assert 'runtime-inputs/platform" / name' in builder
    # Do not grow the old manifest platform schema; 1.3.4 must still parse it.
    manifest_platform = builder[builder.index('"platform": {'):builder.index('"credential_domains"')]
    assert "google" not in manifest_platform.lower()
    assert "chrome" not in manifest_platform.lower()


def test_display_read_projection_cannot_autoflush_into_legacy_client_columns():
    clients = read("backend/service1/routers/clients.py")
    helper = clients[clients.index("def _set_runtime_read_attr"):clients.index("def _apply_network_status_for_read")]
    projection = clients[clients.index("def _apply_display_projection_for_read"):clients.index("def _prepare_clients_read")]

    assert "set_committed_value" in helper
    assert "setattr(obj, key, value)" not in helper
    assert 'mapper is not None and key in mapper.attrs' in helper
    assert '_set_runtime_read_attr(client, "chrome_status"' in projection
    assert '_set_runtime_read_attr(client, "pending_chrome_action"' in projection


def test_legacy_display_writes_remain_unroutable_after_system_authority_cutover():
    clients = read("backend/service1/routers/clients.py")

    legacy_set = clients[clients.index("LEGACY_DISPLAY_STATUS_WRITE_FIELDS ="):clients.index("def _reject_legacy_display_write_fields")]
    for field in ("chrome_status", "chrome_color", "chrome_step", "chrome_last_updated", "service_calendar_status"):
        assert f'"{field}"' in legacy_set
    assert "_reject_legacy_display_write_fields(create_fields)" in clients
    assert 'pending_display_action in _LEGACY_DISPLAY_PENDING_ACTIONS' in clients
    assert 'Legacy pending Chrome/Display-action er fjernet' in clients
    assert 'legacy_step in SYSTEM_TERMINAL_STEPS or legacy_step.startswith("os_")' not in clients
    projection = clients[clients.index("def _apply_display_projection_for_read"):clients.index("def _apply_system_projection_for_read")]
    assert '_set_runtime_read_attr(client, "chrome_step", projection["chrome_step"])' in projection
    assert "System/OS steps remain temporarily visible" not in projection

    chrome_put = clients[clients.index('@router.put("/clients/{id}/chrome-status")'):clients.index('@router.put("/clients/{id}/state")')]
    assert 'legacy_status_fields = {"chrome_status", "chrome_color", "chrome_step", "chrome_last_updated", "chrome_step_timestamp"} & set(data)' in chrome_put
    assert 'if legacy_status_fields:' in chrome_put
    assert "Display og System observed/completion state" in chrome_put
    assert "canonical domain-kontrakter" in chrome_put
