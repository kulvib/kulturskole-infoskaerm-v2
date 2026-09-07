from __future__ import annotations

import importlib.util
from pathlib import Path
import pwd
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "client/runtime/clientflow_runtime"
SYSTEMD = ROOT / "client/systemd"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RUNTIME / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_time_integrity_corrects_timezone_and_ntp(monkeypatch, tmp_path: Path):
    module = _load("clientflow_time_integrity_test", "time_integrity.py")
    fake = tmp_path / "timedatectl"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(module, "TIMEDATECTL", fake)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)

    state = {"timezone": "UTC", "ntp": "no"}
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int = 30) -> str:
        del timeout
        calls.append(command)
        if command[-3:] == ["show", "--property=Timezone", "--value"]:
            return state["timezone"] + "\n"
        if command[-3:] == ["show", "--property=NTP", "--value"]:
            return state["ntp"] + "\n"
        if command[-2:] == ["set-timezone", "Europe/Copenhagen"]:
            state["timezone"] = "Europe/Copenhagen"
            return ""
        if command[-2:] == ["set-ntp", "true"]:
            state["ntp"] = "yes"
            return ""
        raise AssertionError(command)

    monkeypatch.setattr(module, "_run", fake_run)
    module.enforce()

    assert [str(fake), "set-timezone", "Europe/Copenhagen"] in calls
    assert [str(fake), "set-ntp", "true"] in calls
    assert state == {"timezone": "Europe/Copenhagen", "ntp": "yes"}


def test_time_integrity_timer_is_persistent_boot_delayed_and_hourly():
    timer = (SYSTEMD / "clientflow-time-integrity.timer").read_text(encoding="utf-8")
    service = (SYSTEMD / "clientflow-time-integrity.service").read_text(encoding="utf-8")
    target = (SYSTEMD / "clientflow.target").read_text(encoding="utf-8")
    pyproject = (ROOT / "client/runtime/pyproject.toml").read_text(encoding="utf-8")

    assert "OnBootSec=10min" in timer
    assert "OnUnitActiveSec=1h" in timer
    assert "Persistent=true" in timer
    assert "Unit=clientflow-time-integrity.service" in timer
    assert "WantedBy=clientflow.target" in timer
    assert "clientflow-time-integrity.timer" in target
    assert "ExecStart=/opt/clientflow/active/runtime/bin/clientflow-time-integrity" in service
    assert 'clientflow-time-integrity = "clientflow_runtime.time_integrity:main"' in pyproject


def test_kiosk_session_policy_only_mutates_for_active_local_kiosk(monkeypatch, tmp_path: Path):
    module = _load("clientflow_kiosk_session_policy_test", "kiosk_session_policy.py")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)

    executables = {}
    for name in ("runuser", "gsettings", "nmcli", "rfkill", "powerprofilesctl", "wpctl"):
        path = tmp_path / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        executables[name] = path
    monkeypatch.setattr(module, "RUNUSER", executables["runuser"])
    monkeypatch.setattr(module, "GSETTINGS", executables["gsettings"])
    monkeypatch.setattr(module, "NMCLI", executables["nmcli"])
    monkeypatch.setattr(module, "RFKILL", executables["rfkill"])
    monkeypatch.setattr(module, "POWERPROFILESCTL", executables["powerprofilesctl"])
    monkeypatch.setattr(module, "WPCTL", executables["wpctl"])
    monkeypatch.setattr(module, "_active_local_kiosk_session", lambda: "7")

    record = pwd.struct_passwd(
        (module.KIOSK_USER, "x", 1000, 1000, "", f"/home/{module.KIOSK_USER}", "/bin/bash")
    )
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: record if name == module.KIOSK_USER else None)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, **_kwargs: calls.append(command)
        or subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )
    gsettings_calls = []
    audio_calls = []
    monkeypatch.setattr(
        module,
        "_apply_gsettings",
        lambda value, *, lockdown_quicksettings=False: gsettings_calls.append((value, lockdown_quicksettings)),
    )
    monkeypatch.setattr(module, "_apply_audio", lambda value: audio_calls.append(value))

    module.enforce()

    assert [str(executables["nmcli"]), "radio", "wifi", "on"] in calls
    assert [str(executables["rfkill"]), "block", "bluetooth"] in calls
    assert [str(executables["powerprofilesctl"]), "set", "balanced"] in calls
    assert gsettings_calls == [(record, False)]
    assert audio_calls == [record]

    calls.clear()
    monkeypatch.setattr(module, "_active_local_kiosk_session", lambda: None)
    module.enforce()
    assert calls == []


def test_kiosk_session_policy_source_contains_audio_and_gnome_baseline():
    source = (RUNTIME / "kiosk_session_policy.py").read_text(encoding="utf-8")
    timer = (SYSTEMD / "clientflow-kiosk-session-policy.timer").read_text(encoding="utf-8")
    service = (SYSTEMD / "clientflow-kiosk-session-policy.service").read_text(encoding="utf-8")
    target = (SYSTEMD / "clientflow.target").read_text(encoding="utf-8")

    for needle in (
        '"radio", "wifi", "on"',
        '"block", "bluetooth"',
        '"set", "balanced"',
        '"set-mute", "@DEFAULT_AUDIO_SINK@", "0"',
        '"set-volume", "@DEFAULT_AUDIO_SINK@", "0.60"',
        '"night-light-enabled", "false"',
        '"color-scheme", "\'default\'"',
    ):
        assert needle in source
    assert "clientflow-kiosk" in source
    enforce_source = source[source.index("def enforce(") : source.index("def main()") ]
    assert "cfadmin" not in enforce_source
    assert "OnUnitActiveSec=5min" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=clientflow.target" in timer
    assert "clientflow-kiosk-session-policy.timer" in target
    assert "ExecStart=/opt/clientflow/active/runtime/bin/clientflow-kiosk-session-policy" in service


def test_popup_baseline_applies_to_both_human_accounts_and_firefox(monkeypatch, tmp_path: Path):
    module = _load("display_popup_baseline_test", "display_platform_prepare.py")
    kiosk_home = tmp_path / "kiosk"
    admin_home = tmp_path / "admin"
    kiosk_home.mkdir()
    admin_home.mkdir()
    uid = kiosk_home.stat().st_uid
    gid = kiosk_home.stat().st_gid

    records = {
        "clientflow-kiosk": pwd.struct_passwd(("clientflow-kiosk", "x", uid, gid, "", str(kiosk_home), "/bin/bash")),
        "cfadmin": pwd.struct_passwd(("cfadmin", "x", uid, gid, "", str(admin_home), "/bin/bash")),
    }
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: records[name])
    monkeypatch.setattr(module.os, "chown", lambda *_args, **_kwargs: None)
    firefox = tmp_path / "etc/firefox/policies/policies.json"
    firefox_install = tmp_path / "usr/lib/firefox/distribution/policies.json"
    apport = tmp_path / "etc/default/apport"
    original_apport = module._prepare_apport_disabled
    original_firefox = module._prepare_firefox_popup_policy
    monkeypatch.setattr(
        module,
        "_prepare_apport_disabled",
        lambda: original_apport(apport, disable_service=False),
    )
    monkeypatch.setattr(
        module,
        "_prepare_firefox_popup_policy",
        lambda: original_firefox(firefox, install_path=firefox_install),
    )

    module._prepare_human_popup_baseline("clientflow-kiosk")

    for home in (kiosk_home, admin_home):
        autostart = home / ".config/autostart"
        assert len(list(autostart.glob("*.desktop"))) == len(module.KIOSK_DISABLED_AUTOSTARTS)
        for name in module.KIOSK_DISABLED_AUTOSTARTS:
            text = (autostart / name).read_text(encoding="utf-8")
            assert "Hidden=true" in text
            assert "X-GNOME-Autostart-enabled=false" in text
    assert apport.read_text(encoding="utf-8").strip() == "enabled=0"
    assert firefox_install.read_text(encoding="utf-8") == firefox.read_text(encoding="utf-8")
    policy = firefox.read_text(encoding="utf-8")
    for key in (
        "DisableAppUpdate",
        "DisableFirefoxStudies",
        "DisableTelemetry",
        "DontCheckDefaultBrowser",
        "OverrideFirstRunPage",
        "OverridePostUpdatePage",
    ):
        assert key in policy


def test_popup_policy_does_not_touch_frozen_domains_or_credentials():
    source = (RUNTIME / "display_platform_prepare.py").read_text(encoding="utf-8")
    popup_start = source.index("def _prepare_user_popup_autostarts")
    popup_end = source.index("def _prepare_kiosk_application_lockdown")
    popup_source = source[popup_start:popup_end]
    for forbidden in (
        "/etc/clientflow/credentials",
        "livestream",
        "remote_desktop",
        "remote-desktop",
        "terminal",
    ):
        assert forbidden not in popup_source
