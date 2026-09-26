from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIALOG = ROOT / "frontend/src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx"


def test_admin_password_enter_uses_same_open_gate_as_button() -> None:
    source = DIALOG.read_text(encoding="utf-8")
    assert "const adminOpenDisabled = !connected || !agentConnected || ptyReady || (!adminStepUpReady && !adminPassword);" in source
    assert 'if (event.key !== "Enter" || event.isComposing || adminOpenDisabled) return;' in source
    assert "onKeyDown={handleAdminPasswordKeyDown}" in source
    assert "disabled={adminOpenDisabled}" in source


def test_terminal_support_catalog_is_v2_canonical_and_read_only() -> None:
    source = DIALOG.read_text(encoding="utf-8")
    required = (
        "clientflow-display-agent.service",
        "clientflow-display-runtime.service",
        "clientflow-browser-guard.service",
        "/var/lib/clientflow/display-runtime/configuration.json",
        "/var/lib/clientflow/display-runtime/runtime-status.json",
        "clientflow-updater.timer",
        "dpkg --audit",
        "apt-get -o Debug::NoLocking=1 check",
        "/var/run/reboot-required",
        "resolvectl status",
        "timedatectl status",
    )
    for token in required:
        assert token in source

    forbidden = (
        "Reinstaller Python deps",
        "Reset installer-cache",
        "Reset stale apt-locks",
        "Kør desktop installer",
        "clientflow_service.service",
        "client_remote_desktop_agent.service",
        "clientflow_livestream.service",
    )
    for token in forbidden:
        assert token not in source
