from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "client/runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from clientflow_runtime import display_runtime as runtime_module  # noqa: E402
from clientflow_runtime.display_shared_file import atomic_write_shared_json  # noqa: E402


def _configure_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "state"
    runtime = tmp_path / "run"
    monkeypatch.setattr(runtime_module, "STATE_DIR", state)
    monkeypatch.setattr(runtime_module, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(runtime_module, "CONFIG_PATH", state / "configuration.json")
    monkeypatch.setattr(runtime_module, "STATUS_PATH", state / "runtime-status.json")
    monkeypatch.setattr(runtime_module, "SOCKET_PATH", runtime / "runtime.sock")
    monkeypatch.setattr(runtime_module, "PID_PATH", runtime / "browser.pid")
    monkeypatch.setattr(runtime_module, "PROFILE_DIR", state / "browser-profile")
    return state, runtime


def test_atomic_json_can_publish_with_explicit_shared_group(tmp_path: Path):
    target = tmp_path / "state.json"
    atomic_write_shared_json(target, {"ok": True}, mode=0o640, group_gid=os.getgid())

    metadata = target.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o640
    assert metadata.st_gid == os.getgid()
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_display_runtime_restores_shared_boundary_and_socket_group(monkeypatch, tmp_path):
    state, runtime_dir = _configure_paths(monkeypatch, tmp_path)
    state.mkdir()
    runtime_dir.mkdir()
    (state / "configuration.json").write_text(
        json.dumps({"schema_version": 1, "revision": 1, "kiosk_url": "https://example.test/"}),
        encoding="utf-8",
    )
    (state / "runtime-status.json").write_text("{}", encoding="utf-8")

    shared_gid = os.getgid()
    monkeypatch.setattr(
        runtime_module.DisplayRuntime,
        "_control_group_gid",
        staticmethod(lambda: shared_gid),
    )

    runtime = runtime_module.DisplayRuntime()
    runtime._prepare_shared_permissions()

    for directory in (state, runtime_dir):
        metadata = directory.stat()
        assert stat.S_IMODE(metadata.st_mode) == 0o750
        assert metadata.st_gid == shared_gid
    for path in (state / "configuration.json", state / "runtime-status.json"):
        metadata = path.stat()
        assert stat.S_IMODE(metadata.st_mode) == 0o640
        assert metadata.st_gid == shared_gid

    runtime.browser_requested = True
    runtime._status("failed", error="browser_exited", exit_code=-5)
    failed = json.loads((state / "runtime-status.json").read_text(encoding="utf-8"))
    assert failed["state"] == "failed"
    assert failed["browser_requested"] is True
    assert (state / "runtime-status.json").stat().st_gid == shared_gid

    stopped = runtime.stop_browser()
    assert stopped == {"stopped": True, "was_running": False}
    assert runtime.browser_requested is False
    status_payload = json.loads((state / "runtime-status.json").read_text(encoding="utf-8"))
    assert status_payload["state"] == "stopped"
    assert status_payload["browser_requested"] is False

    server = runtime._open_server_socket()
    try:
        socket_metadata = (runtime_dir / "runtime.sock").stat()
        assert stat.S_IMODE(socket_metadata.st_mode) == 0o660
        assert socket_metadata.st_gid == shared_gid
    finally:
        server.close()
        (runtime_dir / "runtime.sock").unlink(missing_ok=True)


def test_display_runtime_unit_keeps_kiosk_primary_group_and_control_supplementary():
    unit = (ROOT / "client/systemd/clientflow-display-runtime.service").read_text(encoding="utf-8")
    service_lines = [line.strip() for line in unit.splitlines() if line.strip()]

    assert "User=@CLIENTFLOW_KIOSK_USER@" in service_lines
    assert "Group=clientflow-display-control" not in service_lines
    supplementary = next(line for line in service_lines if line.startswith("SupplementaryGroups="))
    groups = set(supplementary.split("=", 1)[1].split())
    assert {"clientflow-display-control", "video", "render", "audio"}.issubset(groups)
