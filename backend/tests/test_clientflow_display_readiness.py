from __future__ import annotations

import json
import time
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "client/runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from clientflow_runtime import display_readiness  # noqa: E402


def test_gui_readiness_requires_wayland_kiosk_session_and_running_browser_when_configured(monkeypatch, tmp_path):
    config = tmp_path / "configuration.json"
    status = tmp_path / "runtime-status.json"
    gui_status = tmp_path / "local-gui-status.json"
    config.write_text(json.dumps({"schema_version": 1, "revision": 1, "kiosk_url": "https://example.test"}), encoding="utf-8")
    status.write_text(json.dumps({"state": "running", "browser_requested": True, "browser_pid": 4321}), encoding="utf-8")
    gui_status.write_text(json.dumps({"state": "running", "pid": 9876, "updated_at": time.time()}), encoding="utf-8")
    monkeypatch.setattr(display_readiness, "CONFIG_PATH", config)
    monkeypatch.setattr(display_readiness, "STATUS_PATH", status)
    monkeypatch.setattr(display_readiness, "LOCAL_GUI_STATUS_PATH", gui_status)
    monkeypatch.setattr(display_readiness.os, "kill", lambda _pid, _sig: None)
    monkeypatch.setattr(display_readiness.os, "getuid", lambda: 1000)
    monkeypatch.setattr(display_readiness.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_name="kiosk"))
    values = {
        ("seat", "seat0", "ActiveSession"): "c2",
        ("session", "c2", "Name"): "kiosk",
        ("session", "c2", "Seat"): "seat0",
        ("session", "c2", "Remote"): "no",
        ("session", "c2", "Type"): "wayland",
        ("session", "c2", "Active"): "yes",
        ("session", "c2", "State"): "active",
        ("session", "c2", "LockedHint"): "no",
    }
    monkeypatch.setattr(display_readiness, "_loginctl", lambda kind, ident, prop: values[(kind, ident, prop)])
    assert display_readiness.ready() is True
    status.write_text(json.dumps({"state": "waiting_session", "browser_requested": True, "browser_pid": None}), encoding="utf-8")
    assert display_readiness.ready() is False


def test_gui_readiness_fails_closed_when_local_clientflow_gui_is_missing(monkeypatch, tmp_path):
    config = tmp_path / "configuration.json"
    status = tmp_path / "runtime-status.json"
    gui_status = tmp_path / "local-gui-status.json"
    config.write_text(json.dumps({"schema_version": 1, "revision": 1, "kiosk_url": ""}), encoding="utf-8")
    status.write_text(json.dumps({"state": "stopped", "browser_requested": False, "browser_pid": None}), encoding="utf-8")
    monkeypatch.setattr(display_readiness, "CONFIG_PATH", config)
    monkeypatch.setattr(display_readiness, "STATUS_PATH", status)
    monkeypatch.setattr(display_readiness, "LOCAL_GUI_STATUS_PATH", gui_status)
    monkeypatch.setattr(display_readiness, "_active_kiosk_session", lambda: True)
    assert display_readiness.ready() is False
