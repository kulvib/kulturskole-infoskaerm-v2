from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from clientflow_runtime import kiosk_lockdown, kiosk_lockdown_broker

ROOT = Path(__file__).resolve().parents[2]


def test_default_platform_baseline_does_not_apply_optional_lockdown():
    source = (Path(__file__).resolve().parents[2] / "client/runtime/clientflow_runtime/display_platform_prepare.py").read_text(encoding="utf-8")
    gsettings = source[source.index("def _gsettings_commands"):source.index("def _prepare_gnome_settings")]
    graphical = source[source.index("def _prepare_graphical_kiosk"):source.index("def prepare()")]
    assert '"disable-command-line", "true"' not in gsettings
    assert '"terminal", "[]"' not in gsettings
    assert '"favorite-apps", "[]"' not in gsettings
    assert "_prepare_kiosk_application_lockdown(" not in graphical
    assert "_prepare_kiosk_binary_acl(" not in graphical
    assert "_prepare_kiosk_polkit_policy(" not in graphical


def test_dynamic_launcher_hide_and_exact_restore(tmp_path, monkeypatch):
    home = tmp_path / "home"
    app_dir = home / ".local/share/applications"
    app_dir.mkdir(parents=True)
    original = app_dir / "org.example.Tool.desktop"
    original.write_text("[Desktop Entry]\nName=Custom local override\n", encoding="utf-8")
    system_apps = tmp_path / "usr-share-applications"
    system_apps.mkdir()
    (system_apps / "org.example.Tool.desktop").write_text("[Desktop Entry]\nName=Tool\n", encoding="utf-8")
    (system_apps / "clientflow-local-gui.desktop").write_text("[Desktop Entry]\nName=ClientFlow\n", encoding="utf-8")
    monkeypatch.setattr(kiosk_lockdown, "SOURCE_DESKTOP_DIRS", (system_apps,))
    monkeypatch.setattr(kiosk_lockdown, "EXTRA_DESKTOP_IDS", ())
    record = SimpleNamespace(pw_uid=0, pw_gid=0)

    kiosk_lockdown._hide_launchers(home, record)
    hidden = original.read_text(encoding="utf-8")
    assert "Hidden=true" in hidden
    assert "X-ClientFlow-Lockdown=true" in hidden
    assert not (app_dir / "clientflow-local-gui.desktop").exists()

    kiosk_lockdown._restore_launchers(home, record)
    assert original.read_text(encoding="utf-8") == "[Desktop Entry]\nName=Custom local override\n"


def test_broker_accepts_only_fixed_boolean_action(monkeypatch):
    monkeypatch.setattr(kiosk_lockdown, "apply", lambda: {"desired": True, "status": "applied"})
    monkeypatch.setattr(kiosk_lockdown, "rollback", lambda: {"desired": False, "status": "disabled"})
    monkeypatch.setattr(kiosk_lockdown, "status", lambda: {"desired": False, "status": "disabled"})
    assert kiosk_lockdown_broker.handle({"schema_version": 1, "action": "set_kiosk_lockdown", "enabled": True})["status"] == "applied"
    assert kiosk_lockdown_broker.handle({"schema_version": 1, "action": "set_kiosk_lockdown", "enabled": False})["status"] == "disabled"
    assert kiosk_lockdown_broker.handle({"schema_version": 1, "action": "status_kiosk_lockdown"})["status"] == "disabled"
    with pytest.raises(ValueError):
        kiosk_lockdown_broker.handle({"schema_version": 1, "action": "set_kiosk_lockdown", "enabled": "true"})
    with pytest.raises(ValueError):
        kiosk_lockdown_broker.handle({"schema_version": 1, "action": "shell", "command": "id"})


def test_recovery_exposes_unlock_and_menu_without_backend_write():
    source = (Path(__file__).resolve().parents[2] / "client/libexec/clientflow-recovery").read_text(encoding="utf-8")
    assert "status|unlock|bundle|restart|menu" in source
    assert 'clientflow-kiosk-lockdown"' in source
    assert '"$helper" rollback' in source
    assert "api" not in source.lower()


def test_display_agent_uses_existing_display_domain_for_lockdown(monkeypatch):
    from clientflow_runtime import display_agent
    from clientflow_runtime.command_agent import CommandContext

    seen = {}
    monkeypatch.setattr(display_agent, "display_control_lock", lambda: __import__("contextlib").nullcontext())
    monkeypatch.setattr(display_agent, "call", lambda path, payload, timeout=0: seen.update({"path": path, "payload": payload, "timeout": timeout}) or {"desired": True, "status": "applied"})
    result = display_agent._handle(CommandContext("c1", 9, "set_kiosk_lockdown", {"enabled": True}, 1, "claim"))
    assert result["status"] == "applied"
    assert seen["path"] == "/run/clientflow/kiosk-lockdown.sock"
    assert seen["payload"] == {"schema_version": 1, "action": "set_kiosk_lockdown", "enabled": True}


def test_backend_lockdown_contract_is_durable_display_reconciliation_source():
    root = Path(__file__).resolve().parents[2]
    display = (root / "backend/service1/display_control.py").read_text(encoding="utf-8")
    clients = (root / "backend/service1/routers/clients.py").read_text(encoding="utf-8")
    shared = (root / "backend/service1/routers/shared_domain.py").read_text(encoding="utf-8")
    assert '"set_kiosk_lockdown"' in display
    assert "def reconcile_kiosk_lockdown" in display
    assert 'payload={"enabled": desired}' in display
    assert "reconcile_kiosk_lockdown(" in shared
    assert "Kiosk lockdown kan kun ændres af superadministrator" in clients
    assert "ikke en understøttet canonical ClientFlow-handling" not in clients


def test_optional_lockdown_restores_legacy_two_second_quicksettings_guard_contract():
    root = ROOT
    guard = (root / "client/runtime/clientflow_runtime/kiosk_quicksettings_guard.py").read_text(encoding="utf-8")
    session = (root / "client/runtime/clientflow_runtime/kiosk_session_policy.py").read_text(encoding="utf-8")
    lockdown = (root / "client/runtime/clientflow_runtime/kiosk_lockdown.py").read_text(encoding="utf-8")
    unit = (root / "client/systemd/clientflow-kiosk-quicksettings-guard.service").read_text(encoding="utf-8")
    target = (root / "client/systemd/clientflow.target").read_text(encoding="utf-8")

    assert '"2"' in guard
    assert "while _desired()" in guard
    assert "lockdown_quicksettings=True" in guard
    assert '[str(NMCLI), "networking", "on"]' in session
    assert '("org.gnome.desktop.notifications", "show-banners", "true")' in session
    assert 'QUICK_GUARD_UNIT = "clientflow-kiosk-quicksettings-guard.service"' in lockdown
    assert '_set_quick_guard_running(True)' in lockdown
    assert '_set_quick_guard_running(False)' in lockdown
    assert "CLIENTFLOW_LOCKDOWN_QUICKSETTINGS_INTERVAL=2" in unit
    assert "clientflow-kiosk-quicksettings-guard.service" in target


def test_lockdown_applied_state_is_published_only_after_quick_guard_starts():
    source = (ROOT / "client/runtime/clientflow_runtime/kiosk_lockdown.py").read_text(encoding="utf-8")
    apply_source = source[source.index("def apply()") : source.index("def rollback()") ]
    assert apply_source.index("_set_quick_guard_running(True)") < apply_source.index("Kiosk lockdown aktiv på kiosk-brugeren")


def test_backend_last_applied_timestamp_is_not_refreshed_by_every_heartbeat() -> None:
    source = (ROOT / "backend/service1/display_control.py").read_text(encoding="utf-8")
    assert 'previous_status = str(getattr(client, "desktop_lockdown_status", "") or "").strip().lower()' in source
    assert 'observed_status in {"applied", "disabled"} and previous_status != observed_status' in source
    completion = source[source.index("def apply_display_command_completion"): ]
    assert "client.desktop_lockdown_last_applied_at = utcnow()" in completion
