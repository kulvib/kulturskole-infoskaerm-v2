from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "client/runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from clientflow_runtime import display_runtime as runtime_module  # noqa: E402


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


def _configure_runtime_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "state"
    run = tmp_path / "run"
    monkeypatch.setattr(runtime_module, "STATE_DIR", state)
    monkeypatch.setattr(runtime_module, "RUNTIME_DIR", run)
    monkeypatch.setattr(runtime_module, "CONFIG_PATH", state / "configuration.json")
    monkeypatch.setattr(runtime_module, "STATUS_PATH", state / "runtime-status.json")
    monkeypatch.setattr(runtime_module, "SOCKET_PATH", run / "runtime.sock")
    monkeypatch.setattr(runtime_module, "PID_PATH", run / "browser.pid")
    monkeypatch.setattr(runtime_module, "PROFILE_DIR", state / "browser-profile")
    monkeypatch.setattr(runtime_module, "CHROME_BINARY", Path("/bin/true"))
    state.mkdir(parents=True)
    run.mkdir(parents=True)
    return state, run


def test_display_configuration_starts_browser_and_survives_runtime_recreation(monkeypatch, tmp_path):
    state, _run = _configure_runtime_paths(monkeypatch, tmp_path)

    graphical_env = {
        "HOME": str(tmp_path / "home"),
        "USER": "kiosk",
        "LOGNAME": "kiosk",
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": str(tmp_path / "xdg"),
        "WAYLAND_DISPLAY": "wayland-0",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={tmp_path / 'xdg' / 'bus'}",
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
        "DESKTOP_SESSION": "ubuntu",
        "GDK_BACKEND": "wayland",
    }
    monkeypatch.setattr(runtime_module.DisplayRuntime, "_graphical_environment", lambda self: dict(graphical_env))

    launched: list[tuple[list[str], dict[str, str]]] = []
    pids = iter((5101, 5102))

    def fake_popen(command, **kwargs):
        launched.append((list(command), dict(kwargs["env"])))
        return _FakeProcess(next(pids))

    monkeypatch.setattr(runtime_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime_module.os, "killpg", lambda *_args, **_kwargs: None)

    kiosk_url = "https://infoskaerm.example.test/client/4242"
    runtime = runtime_module.DisplayRuntime()
    assert runtime.configuration == {}
    assert runtime.browser_requested is False

    applied = runtime.apply_configuration(
        {"schema_version": 1, "revision": 1, "kiosk_url": kiosk_url}
    )
    assert applied == {"applied": True, "revision": 1}
    assert runtime.browser_requested is True
    assert runtime.browser is not None and runtime.browser.pid == 5101

    persisted = json.loads((state / "configuration.json").read_text(encoding="utf-8"))
    assert persisted == {"schema_version": 1, "revision": 1, "kiosk_url": kiosk_url}
    status = json.loads((state / "runtime-status.json").read_text(encoding="utf-8"))
    assert status["state"] == "running"
    assert status["configuration_revision"] == 1
    assert status["browser_pid"] == 5101

    first_command, first_env = launched[0]
    assert first_command[0] == "/bin/true"
    assert "--ozone-platform=wayland" in first_command
    assert "--start-fullscreen" in first_command
    assert "--kiosk" not in first_command
    assert first_command[-1] == kiosk_url
    assert first_env["WAYLAND_DISPLAY"] == "wayland-0"
    assert first_env["XDG_SESSION_TYPE"] == "wayland"

    # Simulate service recreation/reboot: durable Display configuration is reloaded
    # and makes the browser desired again without any cloned machine state.
    recreated = runtime_module.DisplayRuntime()
    assert recreated.configuration == persisted
    assert recreated.browser_requested is True
    started = recreated.start_browser()
    assert started["started"] is True
    assert recreated.browser is not None and recreated.browser.pid == 5102
    assert launched[1][0][-1] == kiosk_url


def test_graphical_environment_requires_exact_local_wayland_session(monkeypatch, tmp_path):
    import socket
    from types import SimpleNamespace

    uid = 1000
    xdg_runtime = tmp_path / "run-user-1000"
    xdg_runtime.mkdir()

    bus = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    wayland = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bus.bind(str(xdg_runtime / "bus"))
    wayland.bind(str(xdg_runtime / "wayland-0"))

    real_path = Path

    def mapped_path(value):
        if str(value) == f"/run/user/{uid}":
            return xdg_runtime
        return real_path(value)

    monkeypatch.setattr(runtime_module, "Path", mapped_path)

    # The execution container itself is root. Preserve the real Unix-socket mode
    # while presenting the ownership that a real kiosk user's /run/user/<uid>
    # sockets have on Ubuntu.
    path_type = type(xdg_runtime)
    real_stat = path_type.stat

    def kiosk_owned_stat(self, *args, **kwargs):
        metadata = real_stat(self, *args, **kwargs)
        if self in {xdg_runtime / "bus", xdg_runtime / "wayland-0"}:
            return SimpleNamespace(st_uid=uid, st_mode=metadata.st_mode)
        return metadata

    monkeypatch.setattr(path_type, "stat", kiosk_owned_stat)
    monkeypatch.setattr(runtime_module.os, "getuid", lambda: uid)
    monkeypatch.setattr(
        runtime_module.pwd,
        "getpwuid",
        lambda value: SimpleNamespace(pw_name="kiosk", pw_dir="/home/kiosk") if value == uid else None,
    )

    session_props = {
        "Name": "kiosk",
        "User": str(uid),
        "Seat": "seat0",
        "Remote": "no",
        "Class": "user",
        "Type": "wayland",
        "Active": "yes",
        "State": "active",
        "LockedHint": "no",
    }

    def loginctl_value(kind: str, ident: str, prop: str) -> str:
        if (kind, ident, prop) == ("seat", "seat0", "ActiveSession"):
            return "c7"
        assert kind == "session" and ident == "c7"
        return session_props[prop]

    monkeypatch.setattr(runtime_module.DisplayRuntime, "_loginctl_value", staticmethod(loginctl_value))

    try:
        runtime = runtime_module.DisplayRuntime()
        environment = runtime._graphical_environment()
    finally:
        bus.close()
        wayland.close()

    assert environment["USER"] == "kiosk"
    assert environment["XDG_RUNTIME_DIR"] == str(xdg_runtime)
    assert environment["WAYLAND_DISPLAY"] == "wayland-0"
    assert environment["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={xdg_runtime / 'bus'}"
    assert environment["XDG_SESSION_TYPE"] == "wayland"
    assert environment["GDK_BACKEND"] == "wayland"
