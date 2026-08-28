from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = ROOT / "client/release/lib"
RUNTIME_ROOT = ROOT / "client/runtime"
BACKEND_ROOT = ROOT / "backend"
for item in (RELEASE_LIB, RUNTIME_ROOT, BACKEND_ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from clientflow_release import builder, cli  # noqa: E402
from clientflow_runtime import display_runtime, platform_prepare, system_broker  # noqa: E402


def test_direct_exec_payload_modes_do_not_depend_on_github_source_mode(tmp_path):
    source = tmp_path / "helper"
    source.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    source.chmod(0o644)
    assert builder._payload_source_mode(
        source,
        PurePosixPath("clientflow-9.9.9/client-runtime/libexec/display-power"),
    ) == 0o755
    assert builder._payload_source_mode(
        source,
        PurePosixPath("clientflow-9.9.9/client-runtime/libexec/update-os"),
    ) == 0o755
    assert builder._payload_source_mode(
        source,
        PurePosixPath("clientflow-9.9.9/client-runtime/config-examples/example.json"),
    ) == 0o644


def test_system_broker_password_input_uses_one_subprocess_stdin_mechanism(monkeypatch):
    seen = {}

    class Completed:
        returncode = 0
        stdout = b""

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        assert not ("input" in kwargs and "stdin" in kwargs)
        return Completed()

    monkeypatch.setattr(system_broker.subprocess, "run", fake_run)
    result = system_broker._run(
        ["/usr/sbin/chpasswd"],
        timeout=10,
        input_bytes=b"cfadmin:redacted\n",
    )
    assert result["exit_code"] == 0
    assert seen["input"] == b"cfadmin:redacted\n"


def test_stale_chrome_singleton_cleanup_preserves_profile(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile"
    default = profile / "Default"
    default.mkdir(parents=True)
    preserved = default / "Bookmarks"
    preserved.write_text("keep-me", encoding="utf-8")
    (profile / "SingletonLock").symlink_to("old-hostname-999999")
    (profile / "SingletonCookie").write_text("cookie", encoding="utf-8")
    (profile / "SingletonSocket").symlink_to("/tmp/stale-chrome-socket")

    monkeypatch.setattr(display_runtime, "PROFILE_DIR", profile)
    monkeypatch.setattr(display_runtime.socket, "gethostname", lambda: "new-hostname")

    instance = object.__new__(display_runtime.DisplayRuntime)
    instance._clear_stale_process_singleton()

    assert not (profile / "SingletonLock").exists()
    assert not (profile / "SingletonLock").is_symlink()
    assert not (profile / "SingletonCookie").exists()
    assert not (profile / "SingletonSocket").is_symlink()
    assert preserved.read_text(encoding="utf-8") == "keep-me"


def test_active_same_host_chrome_singleton_is_not_stolen(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to(f"host-a-{__import__('os').getpid()}")
    monkeypatch.setattr(display_runtime, "PROFILE_DIR", profile)
    monkeypatch.setattr(display_runtime.socket, "gethostname", lambda: "host-a")
    instance = object.__new__(display_runtime.DisplayRuntime)
    with pytest.raises(RuntimeError, match="aktiv proces"):
        instance._clear_stale_process_singleton()
    assert (profile / "SingletonLock").is_symlink()


def test_ubuntu_2604_host_requirement_is_release_bound(monkeypatch, tmp_path):
    lock = {
        "schema_version": 1,
        "host_requirements": {
            "os_id": "ubuntu",
            "version_id": "26.04",
            "architecture": "amd64",
            "packages": [
                {"package": "gstreamer1.0-plugins-bad", "minimum_version": "1.28.2-1ubuntu1.1"},
                {"package": "gir1.2-gst-plugins-base-1.0", "minimum_version": "1.28.2-1"},
            ],
        },
    }
    path = tmp_path / "runtime-platform-inputs.lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(platform_prepare, "LOCK_PATH", path)
    rows = platform_prepare._requirements()
    assert {row["package"] for row in rows} == {
        "gstreamer1.0-plugins-bad",
        "gir1.2-gst-plugins-base-1.0",
    }


def test_platform_gate_is_target_owned_and_precedes_frozen_consumers():
    target = (ROOT / "client/systemd/clientflow.target").read_text(encoding="utf-8")
    assert "Requires=clientflow-platform-prepare.service" in target
    assert "After=clientflow-platform-prepare.service" in target
    for name in ("clientflow-livestream-producer.service", "clientflow-remote-desktop-capture.service"):
        unit = (ROOT / "client/systemd" / name).read_text(encoding="utf-8")
        assert "Requires=clientflow-platform-prepare.service" in unit
        assert "clientflow-platform-prepare.service" in next(
            line for line in unit.splitlines() if line.startswith("After=")
        )


def test_service_specific_confinement_contracts():
    display = (ROOT / "client/systemd/clientflow-display-runtime.service").read_text(encoding="utf-8")
    power = (ROOT / "client/systemd/clientflow-display-power-broker.service").read_text(encoding="utf-8")
    system = (ROOT / "client/systemd/clientflow-system-broker.service").read_text(encoding="utf-8")
    assert "MemoryDenyWriteExecute=no" in display
    assert "NoNewPrivileges=no" in power
    families = next(line for line in system.splitlines() if line.startswith("RestrictAddressFamilies="))
    assert {"AF_UNIX", "AF_NETLINK", "AF_INET", "AF_INET6"} <= set(families.split("=", 1)[1].split())


def test_cfadmin_is_created_locked_without_privileged_groups(monkeypatch):
    from types import SimpleNamespace

    calls = []
    created = {"value": False}

    def fake_getpwnam(name):
        assert name == "cfadmin"
        if not created["value"]:
            raise KeyError(name)
        return SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_dir="/home/cfadmin", pw_shell="/bin/bash")

    def fake_run(command, **kwargs):
        calls.append(command)
        created["value"] = True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.pwd, "getpwnam", fake_getpwnam)
    monkeypatch.setattr(cli.grp, "getgrgid", lambda gid: SimpleNamespace(gr_name="cfadmin"))
    monkeypatch.setattr(cli.os, "getgrouplist", lambda user, gid: [gid])
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli._ensure_cfadmin_account(cli.Layout(Path("/")))

    assert len(calls) == 1
    command = calls[0]
    assert command[0] == "/usr/sbin/useradd"
    assert "--create-home" in command
    assert ["--shell", "/bin/bash"] == command[command.index("--shell"):command.index("--shell") + 2]
    assert ["--password", "!"] == command[command.index("--password"):command.index("--password") + 2]
    assert "sudo" not in command and "adm" not in command and "root" not in command


def test_fresh_conflict_inventory_owns_cfadmin_account():
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    wipe = (ROOT / "client/release/lib/clientflow_release/wipe.py").read_text(encoding="utf-8")
    assert '"cfadmin"' in source
    assert '"cfadmin"' in wipe


def test_status_diagnostics_projection_uses_canonical_existing_units():
    source = (ROOT / "backend/service1/routers/clients.py").read_text(encoding="utf-8")
    expected = {
        "service_clientflow_status": "clientflow-status-agent.service",
        "service_calendar_status": "clientflow-calendar.service",
        "service_browser_guard_status": "clientflow-display-runtime.service",
        "service_remote_terminal_status": "clientflow-terminal-agent.service",
        "service_admin_terminal_status": "clientflow-root-terminal-broker.socket",
        "service_remote_desktop_status": "clientflow-remote-desktop-agent.service",
        "service_livestream_status": "clientflow-livestream-producer.service",
        "service_selfupdate_status": "clientflow-updater.timer",
        "service_ubuntu_update_status": "clientflow-system-broker.socket",
    }
    systemd_units = {path.name for path in (ROOT / "client/systemd").iterdir() if path.is_file()}
    for field, unit in expected.items():
        assert f'"{field}": "{unit}"' in source
        assert unit in systemd_units
