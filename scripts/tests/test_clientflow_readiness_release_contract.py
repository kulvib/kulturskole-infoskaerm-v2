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

from clientflow_release import builder  # noqa: E402
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
        PurePosixPath("clientflow-9.9.9/client-runtime/libexec/clientflow-recovery"),
    ) == 0o755
    assert builder._payload_source_mode(
        source,
        PurePosixPath("clientflow-9.9.9/client-runtime/libexec/clientflow-switch-user-admin"),
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
    lock = json.loads((ROOT / "client/release/runtime-platform-inputs.lock.json").read_text(encoding="utf-8"))
    path = tmp_path / "runtime-platform-inputs.lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(platform_prepare, "LOCK_PATH", path)
    rows = platform_prepare._requirements()
    packages = {row["package"] for row in rows}
    assert {
        "acl",
        "rfkill",
        "polkitd",
        "python3-gi",
        "dbus",
        "libglib2.0-bin",
        "gir1.2-gstreamer-1.0",
        "gir1.2-gst-plugins-base-1.0",
        "gir1.2-gtk-4.0",
        "gstreamer1.0-plugins-base",
        "gstreamer1.0-plugins-good",
        "gstreamer1.0-plugins-bad",
        "gstreamer1.0-plugins-ugly",
        "gstreamer1.0-pipewire",
    } <= packages


def test_platform_probe_uses_system_python_and_all_frozen_capture_capabilities():
    source = (ROOT / "client/runtime/clientflow_runtime/platform_prepare.py").read_text(encoding="utf-8")
    assert 'SYSTEM_PYTHON = Path("/usr/bin/python3")' in source
    assert "RUNTIME_PYTHON" not in source
    for executable in (
        "/usr/bin/setfacl", "/usr/bin/setpriv", "/usr/bin/loginctl", "/usr/bin/gdbus",
        "/usr/bin/gsettings", "/usr/bin/dbus-run-session", "/usr/sbin/rfkill", "/usr/bin/timedatectl",
    ):
        assert executable in source
    for element in (
        "pipewiresrc", "queue", "videoconvert", "videorate", "videoscale",
        "jpegenc", "appsink", "x264enc", "h264parse", "mpegtsmux", "hlssink",
    ):
        assert f'"{element}"' in source
    for namespace in ("Gio", "Gst", "GstApp", "Gtk", "Pango"):
        assert f'gi.require_version("{namespace}"' in source


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
    platform = (ROOT / "client/systemd/clientflow-platform-prepare.service").read_text(encoding="utf-8")
    status = (ROOT / "client/systemd/clientflow-status-agent.service").read_text(encoding="utf-8")
    system = (ROOT / "client/systemd/clientflow-system-broker.service").read_text(encoding="utf-8")
    livestream = (ROOT / "client/systemd/clientflow-livestream-producer.service").read_text(encoding="utf-8")
    assert "MemoryDenyWriteExecute=no" in display
    assert "NoNewPrivileges=no" in power
    assert "NoNewPrivileges=no" in platform
    assert "NoNewPrivileges=no" in system
    for source in (display, status):
        families = next(line for line in source.splitlines() if line.startswith("RestrictAddressFamilies="))
        assert {"AF_UNIX", "AF_NETLINK", "AF_INET", "AF_INET6"} <= set(families.split("=", 1)[1].split())
    assert "NoNewPrivileges=yes" in livestream
    for key in ("CapabilityBoundingSet=", "AmbientCapabilities="):
        caps = next(line for line in livestream.splitlines() if line.startswith(key)).split("=", 1)[1].split()
        assert {"CAP_SETUID", "CAP_SETGID"} <= set(caps)


def test_target_services_do_not_depend_on_obsolete_parallel_activation_marker():
    marker = "/etc/clientflow/activated"
    for path in (ROOT / "client/systemd").iterdir():
        if path.is_file() and path.suffix in {".service", ".socket", ".target", ".timer"}:
            assert marker not in path.read_text(encoding="utf-8"), path.name


def test_ubuntu_2604_host_gate_executes_real_service_sandbox_probes():
    source = (ROOT / "scripts/verify_clientflow_ubuntu2604_host.py").read_text(encoding="utf-8")
    assert '"/usr/bin/systemd-run"' in source
    assert '"clientflow-platform-prepare.service", "platform-uid"' in source
    assert '"clientflow-system-broker.service", "system-uid"' in source
    assert '"clientflow-livestream-producer.service", "livestream-uid"' in source
    assert '"clientflow-status-agent.service", "status-netlink"' in source
    assert '"clientflow-display-runtime.service", "display-netlink"' in source
    assert 'os.setresuid(account.pw_uid, account.pw_uid, account.pw_uid)' in source
    assert '["/usr/sbin/ip", "-j", "route", "show", "default"]' in source


def test_fresh_human_accounts_restore_legacy_two_user_contract():
    source = (ROOT / "client/release/lib/clientflow_release/accounts.py").read_text(encoding="utf-8")
    cli_source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")

    assert 'KIOSK_USER = "clientflow-kiosk"' in source
    assert 'ADMIN_USER = "cfadmin"' in source
    assert '["/usr/sbin/usermod", "--append", "--groups", "sudo", ADMIN_USER]' in source
    assert '["/usr/bin/passwd", "--delete", KIOSK_USER]' in source
    assert 'provision_human_accounts(prompt_admin_password=True)' in cli_source
    assert 'install.add_argument("--kiosk-user", default=KIOSK_USER, choices=[KIOSK_USER])' in cli_source


def test_cfadmin_password_is_tty_prompted_and_not_persisted():
    source = (ROOT / "client/release/lib/clientflow_release/accounts.py").read_text(encoding="utf-8")
    cli_source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    assert 'getpass.getpass("Nyt password til cfadmin: ")' in source
    assert 'getpass.getpass("Gentag password til cfadmin: ")' in source
    assert 'chpasswd' in source
    assert 'cfadmin_password' not in cli_source


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
        "service_browser_guard_status": "clientflow-browser-guard.service",
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


def test_gui_readiness_is_part_of_display_service_start_job():
    unit = (ROOT / "client/systemd/clientflow-display-runtime.service").read_text(encoding="utf-8")
    runtime_prepare = (ROOT / "client/release/lib/clientflow_release/runtime_prepare.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "client/runtime/pyproject.toml").read_text(encoding="utf-8")
    assert "ExecStartPost=/opt/clientflow/active/runtime/bin/clientflow-display-readiness" in unit
    assert '"clientflow-display-readiness"' in runtime_prepare
    assert 'clientflow-display-readiness = "clientflow_runtime.display_readiness:main"' in pyproject


def test_legacy_countdown_and_cookie_contract_is_explicit_in_v2():
    runtime = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    control = (ROOT / "client/runtime/clientflow_runtime/display_local_control.py").read_text(encoding="utf-8")
    assert "BOOT_START_COUNTDOWN_SECONDS = 10" in runtime
    assert "CONFIGURATION_START_COUNTDOWN_SECONDS = 10" in runtime
    assert "MANUAL_START_COUNTDOWN_SECONDS = 10" in runtime
    assert "RESET_BROWSER_COUNTDOWN_SECONDS = 10" in runtime
    assert "DISPLAY_SLEEP_COUNTDOWN_SECONDS = 10" in runtime
    assert 'step="clear_cookies"' in runtime
    assert 'shutil.rmtree(profile' in runtime
    assert 'if state == "off"' in control and 'display_sleep_countdown' in control
    # Wake/Calendar remain non-destructive; clean profile is owned by boot,
    # explicit backend/GUI start, URL change and reset-browser.
    wake_block = control[control.index("def set_display_power"):control.index("def runtime_action")]
    assert "rmtree" not in wake_block and "clear_cookies" not in wake_block
    for reason in ("system_start", "configuration_change", "reset_browser"):
        assert reason in runtime
    assert 'source in {"backend", "gui"}' in runtime
    assert 'reason=f"{source}_start"' in runtime


def test_local_clientflow_gui_is_release_owned_and_readiness_gated():
    runtime = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    readiness = (ROOT / "client/runtime/clientflow_runtime/display_readiness.py").read_text(encoding="utf-8")
    gui = (ROOT / "client/libexec/local-gui").read_text(encoding="utf-8")
    unit = (ROOT / "client/systemd/clientflow-display-runtime.service").read_text(encoding="utf-8")
    transaction = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text(encoding="utf-8")
    assert 'LOCAL_GUI_SCRIPT = Path("/opt/clientflow/active/client-runtime/libexec/local-gui")' in runtime
    assert '[str(SYSTEM_PYTHON), str(LOCAL_GUI_SCRIPT)]' in runtime
    assert 'LOCAL_GUI_STATUS_PATH = STATE_DIR / "local-gui-status.json"' in readiness
    assert '_local_gui_ready()' in readiness
    assert 'CLIENTFLOW_CLIENT_ID=@CLIENTFLOW_CLIENT_ID@' in unit
    assert '@CLIENTFLOW_CLIENT_ID@' in transaction
    cli_source = (ROOT / 'client/release/lib/clientflow_release/cli.py').read_text(encoding='utf-8')
    assert 'client_id=int(response["client_id"])' in cli_source
    assert 'gi.require_version("Gtk", "4.0")' in gui
    assert 'Start kiosk' in gui and 'Stop kiosk' in gui
    assert 'Kalender – næste 7 dage' in gui
    assert '/etc/clientflow/credentials' not in gui and 'client_secret' not in gui
    compile(gui, "client/libexec/local-gui", "exec")


def test_first_activation_restarts_gdm_only_when_autologin_config_changes():
    prepare = (ROOT / "client/runtime/clientflow_runtime/display_platform_prepare.py").read_text(encoding="utf-8")
    assert 'def _prepare_gdm' in prepare and '-> bool' in prepare
    assert '["/usr/bin/systemctl", "restart", "gdm3"]' not in prepare
    assert 'activation transaction' in prepare


def test_platform_prepare_enforces_backend_time_integrity_contract(monkeypatch):
    calls = []
    responses = iter(["UTC\n", "yes\n"])
    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[-3:] == ["show", "--property=Timezone", "--value"]:
            return next(responses)
        if command[-3:] == ["show", "--property=NTP", "--value"]:
            return next(responses)
        return ""
    monkeypatch.setattr(platform_prepare, "_run", fake_run)
    platform_prepare._prepare_time_integrity()
    assert ["/usr/bin/timedatectl", "set-timezone", "Europe/Copenhagen"] in calls
    assert ["/usr/bin/timedatectl", "set-ntp", "true"] in calls
