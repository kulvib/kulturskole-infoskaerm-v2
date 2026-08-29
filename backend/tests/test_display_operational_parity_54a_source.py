from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_54a_migration_extends_53b_and_keeps_refresh_under_display_authority() -> None:
    migration = read("backend/migrations/versions/20260829_54a_display_parity.py")
    contract = read("backend/scripts/display_schema_contract.py")
    runner = read("backend/scripts/run_migrations.py")
    validator = read("backend/scripts/validate_display_baseline.py")
    domain_model = read("backend/service1/client_domain_models.py")
    client_model = read("backend/service1/models.py")

    assert 'revision = "20260829_54a_display_parity"' in migration
    assert 'down_revision = "20260823_53b_system_authority"' in migration
    assert '"browser_refresh_interval_sec"' in migration
    assert 'browser_refresh_interval_sec = 0 OR' in migration
    assert 'EXPECTED_HEAD_REVISION = "20260829_54a_display_parity"' in contract
    assert 'REVIEWED_DISPLAY_OPERATIONAL_PARITY_REVISION = "20260829_54a_display_parity"' in runner
    assert 'display_operational_parity_revision.down_revision != REVIEWED_SYSTEM_AUTHORITY_REVISION' in runner
    assert 'if len(str(revision.revision)) > 32:' in validator
    assert 'browser_refresh_interval_sec: int' in domain_model
    client_table = client_model[
        client_model.index("class Client(ClientBase, table=True):"):
        client_model.index("class ClientRead", client_model.index("class Client(ClientBase, table=True):"))
    ]
    assert "browser_refresh_interval_sec" not in client_table


def test_browser_guard_uses_dynamic_display_configuration_and_loopback_devtools() -> None:
    guard = read("client/runtime/clientflow_runtime/browser_guard.py")
    runtime = read("client/runtime/clientflow_runtime/display_runtime.py")
    service = read("client/systemd/clientflow-browser-guard.service")
    target = read("client/systemd/clientflow.target")
    backend = read("backend/service1/routers/clients.py")
    frontend = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")

    assert 'CONFIG_PATH = Path(os.environ.get("CLIENTFLOW_DISPLAY_CONFIG_PATH", "/var/lib/clientflow/display-runtime/configuration.json"))' in guard
    assert '"browser_refresh_interval_sec" in data' in guard
    assert "if seconds <= 0:" in guard and "return 0" in guard
    assert "REFRESH_MIN_SEC" in guard and "REFRESH_MAX_SEC" in guard
    assert '"--remote-debugging-address=127.0.0.1"' in runtime
    assert '"--remote-debugging-port=9222"' in runtime
    assert "IPAddressDeny=any" in service
    assert "IPAddressAllow=localhost" in service
    assert "Environment=CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE=accept" in service
    assert "Environment=CLIENTFLOW_BROWSER_GUARD_ENABLE_AGGRESSIVE_HIDE=1" in service
    assert "Environment=CLIENTFLOW_BROWSER_GUARD_ENABLE_NATIVE_BLOCK=1" in service
    assert "Environment=CLIENTFLOW_BROWSER_GUARD_START_DELAY_SEC=0" in service
    assert "Environment=CLIENTFLOW_BROWSER_GUARD_REFRESH_SEC=900" in service
    assert "SupplementaryGroups=clientflow-display-control" in service
    assert "clientflow-browser-guard.service" in target
    assert '"service_browser_guard_status": "clientflow-browser-guard.service"' in backend
    assert 'browser_refresh_interval_sec' in frontend
    assert '0 = slået fra. Ellers 60–86400 sekunder.' in frontend


def test_display_resolution_is_real_command_result_flow() -> None:
    backend = read("backend/service1/display_control.py")
    clients = read("backend/service1/routers/clients.py")
    shared = read("backend/service1/routers/shared_domain.py")
    agent = read("client/runtime/clientflow_runtime/display_agent.py")
    runtime = read("client/runtime/clientflow_runtime/display_runtime.py")
    resolution = read("client/runtime/clientflow_runtime/display_resolution.py")

    assert '"detect_resolution", "apply_resolution"' in backend
    assert "apply_display_command_completion" in backend
    assert 'client.display_resolution_status = "applied" if command.command_type == "apply_resolution" else "detected"' in backend
    assert 'command_type = "detect_resolution" if resolution_action == "detect" else "apply_resolution"' in clients
    assert 'Display resolution kræver ClientFlow Display-agent 1.3.12 eller nyere' in clients
    assert 'elif domain == "display":' in shared
    assert "apply_display_command_completion" in shared
    assert "apply_display_command_failure" in shared
    assert '"detect_resolution", "apply_resolution"' in agent
    assert 'if action == "detect_resolution":' in runtime
    assert 'if action == "apply_resolution":' in runtime
    assert "ApplyMonitorsConfig" in resolution
    assert "GetCurrentState" in resolution


def test_physical_input_wake_only_uses_display_power_authority() -> None:
    worker = read("client/runtime/clientflow_runtime/display_input_wake.py")
    service = read("client/systemd/clientflow-display-input-wake.service")
    target = read("client/systemd/clientflow.target")
    platform = read("client/runtime/clientflow_runtime/display_platform_prepare.py")

    assert "MANUAL_WAKE_GRACE_SECONDS = 20.0" in worker
    assert 'set_display_power("on")' in worker
    assert 'return int(event.value) != 0' in worker
    assert 'record_calendar_manual_override("manual_input_wake")' in worker
    assert "start_browser" not in worker
    assert "systemctl" not in worker
    assert "subprocess" not in worker
    assert "SupplementaryGroups=input clientflow-display-control" in service
    assert "PrivateDevices=no" in service
    assert "clientflow-display-input-wake.service" in target
    assert '["/usr/sbin/groupadd", "--system", "--force", "input"]' in platform


def test_local_gui_contains_operational_parity_fields_without_credentials() -> None:
    gui = read("client/libexec/local-gui")
    runtime = read("client/runtime/clientflow_runtime/display_runtime.py")

    for label in (
        "Kiosk URL", "Auto refresh", "Skærmopløsning", "Browser Guard",
        "Admin terminal", "Aktivt netværk", "WiFi", "LAN", "Kalender · næste 7 dage",
    ):
        assert label in gui
    assert "CONFIG_PATH" in gui
    assert "RESOLUTION_STATUS_PATH" in gui
    assert "clientflow-browser-guard.service" in gui
    assert "clientflow-root-terminal-broker.socket" in gui
    assert "/etc/clientflow/credentials" not in gui
    assert "LoadCredential" not in gui
    assert "self.set_default_size(720, 720)" in gui
    assert "self.next_resolution_probe" in runtime
