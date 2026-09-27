from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_command_line_escape_is_always_on_kiosk_baseline():
    prepare = read("client/runtime/clientflow_runtime/display_platform_prepare.py")
    session = read("client/runtime/clientflow_runtime/kiosk_session_policy.py")
    for source in (prepare, session):
        assert '("org.gnome.desktop.lockdown", "disable-command-line", "true")' in source
        assert '("org.gnome.settings-daemon.plugins.media-keys", "terminal", "[]")' in source


def test_optional_lockdown_cannot_reset_command_line_baseline():
    lockdown = read("client/runtime/clientflow_runtime/kiosk_lockdown.py")
    optional = lockdown[lockdown.index("OPTIONAL_GSETTINGS = ("):lockdown.index("class KioskLockdownError")]
    assert '("org.gnome.desktop.lockdown", "disable-command-line", "true")' not in optional
    assert '("org.gnome.settings-daemon.plugins.media-keys", "terminal", "[]")' not in optional
    assert 'for schema, key, value in OPTIONAL_GSETTINGS' in lockdown


def test_clientflow_gui_and_brokered_terminal_are_preserved():
    target = read("client/systemd/clientflow.target")
    gui = read("client/libexec/local-gui")
    lockdown = read("client/runtime/clientflow_runtime/kiosk_lockdown.py")

    # The local ClientFlow GUI remains part of the canonical runtime surface.
    assert "clientflow-local-gui" in gui.lower() or "ClientFlow" in gui
    assert '_allowed(desktop_id: str)' in lockdown
    assert '"clientflow" in value' in lockdown

    # ClientFlow Terminal remains its own brokered domain; GNOME command-line
    # lockdown must not disable these sockets/services.
    assert "clientflow-terminal-agent.service" in target
    assert "clientflow-standard-terminal-broker.socket" in target
    assert "clientflow-root-terminal-broker.socket" in target
    assert "clientflow-terminal-agent" not in lockdown
    assert "clientflow-standard-terminal-broker" not in lockdown
    assert "clientflow-root-terminal-broker" not in lockdown


def test_cfadmin_is_outside_kiosk_session_policy_authority():
    session = read("client/runtime/clientflow_runtime/kiosk_session_policy.py")
    assert 'KIOSK_USER = "clientflow-kiosk"' in session
    assert 'cfadmin' in session  # documented as intentionally outside authority
    assert 'runuser", "-u", "cfadmin"' not in session
