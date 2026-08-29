from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "client/legacy-client-parity.json"

EXPECTED_LEGACY_PY = {
    "opt/clientflow/api/chrome_kiosk.py",
    "opt/clientflow/api/client_remote_desktop_agent.py",
    "opt/clientflow/api/client_remote_desktop_wayland_capture.py",
    "opt/clientflow/api/client_terminal_agent.py",
    "opt/clientflow/api/clientflow_browser_guard.py",
    "opt/clientflow/api/clientflow_calendar.py",
    "opt/clientflow/api/clientflow_diagnostics.py",
    "opt/clientflow/api/clientflow_display.py",
    "opt/clientflow/api/clientflow_gui.py",
    "opt/clientflow/api/clientflow_service.py",
    "opt/clientflow/api/config_utils.py",
    "opt/clientflow/api/kiosk_sleep.py",
    "opt/clientflow/api/kiosk_wake.py",
    "opt/clientflow/api/livestream.py",
    "opt/clientflow/api/livestream_uploader.py",
    "opt/clientflow/api/livestream_wayland.py",
    "opt/clientflow/api/livestream_wayland_placeholder.py",
    "opt/clientflow/api/rotate_client_secret.py",
    "opt/clientflow/api/status_map.py",
    "opt/clientflow/api/status_utils.py",
    "opt/clientflow/api/ubuntu_update.py",
    "usr/local/bin/clientflow-cursor-idle-monitor.py",
    "usr/local/lib/clientflow-root/chrome_kiosk.py",
    "usr/local/lib/clientflow-root/client_remote_desktop_agent.py",
    "usr/local/lib/clientflow-root/client_remote_desktop_wayland_capture.py",
    "usr/local/lib/clientflow-root/client_terminal_agent.py",
    "usr/local/lib/clientflow-root/clientflow_browser_guard.py",
    "usr/local/lib/clientflow-root/clientflow_calendar.py",
    "usr/local/lib/clientflow-root/clientflow_diagnostics.py",
    "usr/local/lib/clientflow-root/clientflow_display.py",
    "usr/local/lib/clientflow-root/clientflow_graphical_session.py",
    "usr/local/lib/clientflow-root/clientflow_gui.py",
    "usr/local/lib/clientflow-root/clientflow_service.py",
    "usr/local/lib/clientflow-root/clientflow_update_transaction.py",
    "usr/local/lib/clientflow-root/config_utils.py",
    "usr/local/lib/clientflow-root/kiosk_sleep.py",
    "usr/local/lib/clientflow-root/kiosk_wake.py",
    "usr/local/lib/clientflow-root/livestream.py",
    "usr/local/lib/clientflow-root/livestream_uploader.py",
    "usr/local/lib/clientflow-root/livestream_wayland.py",
    "usr/local/lib/clientflow-root/livestream_wayland_placeholder.py",
    "usr/local/lib/clientflow-root/rotate_client_secret.py",
    "usr/local/lib/clientflow-root/status_map.py",
    "usr/local/lib/clientflow-root/status_utils.py",
    "usr/local/lib/clientflow-root/ubuntu_update.py",
    "usr/local/sbin/clientflow-power-event-reporter.py",
}


def test_every_legacy_119_client_python_file_has_explicit_v2_disposition() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["legacy_baseline"] == {
        "release": "1.1.19",
        "sequence": 1119,
        "payload_python_file_count": 46,
    }
    entries = payload["entries"]
    assert {row["legacy_path"] for row in entries} == EXPECTED_LEGACY_PY
    assert len(entries) == len(EXPECTED_LEGACY_PY)

    allowed = {"implemented", "architecturally_replaced", "obsolete"}
    for row in entries:
        assert row["status"] in allowed
        assert str(row["rationale"]).strip()
        replacements = row["v2_replacements"]
        assert replacements
        for rel in replacements:
            assert (ROOT / rel).exists(), f"Legacy parity replacement mangler: {rel}"


def test_active_legacy_capabilities_are_not_marked_obsolete() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_name: dict[str, set[str]] = {}
    for row in payload["entries"]:
        by_name.setdefault(Path(row["legacy_path"]).name, set()).add(row["status"])
    for active_name in (
        "clientflow_browser_guard.py",
        "clientflow_display.py",
        "clientflow_gui.py",
        "clientflow_service.py",
        "kiosk_sleep.py",
        "kiosk_wake.py",
    ):
        assert by_name[active_name].isdisjoint({"obsolete"})
