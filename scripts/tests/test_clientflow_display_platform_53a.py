from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "client/runtime/clientflow_runtime/display_platform_prepare.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("display_platform_prepare_53a", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_prepare_verifies_embedded_lock_and_bytes(tmp_path: Path):
    module = _load_module()
    platform = tmp_path / "runtime-inputs/platform"
    platform.mkdir(parents=True)
    data = b"exact-chrome-deb"
    name = "google-chrome-stable_test_amd64.deb"
    (platform / name).write_bytes(data)
    lock = {
        "schema_version": 1,
        "platform_artifacts": [{
            "file": name,
            "package": "google-chrome-stable",
            "version": "151.0.7922.173-1",
            "architecture": "amd64",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }],
    }
    (platform / "runtime-platform-inputs.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    path, artifact = module._load_chrome_artifact(tmp_path)
    assert path == platform / name
    assert artifact["package"] == "google-chrome-stable"

    (platform / name).write_bytes(b"tampered")
    try:
        module._load_chrome_artifact(tmp_path)
    except module.DisplayPlatformPreparationError as exc:
        assert "matcher ikke release-lock" in str(exc)
    else:
        raise AssertionError("tampered Chrome bytes were accepted")


def test_google_repo_detection_distinguishes_disabled_sources(tmp_path: Path):
    module = _load_module()
    (tmp_path / "sources.list.d").mkdir()
    (tmp_path / "sources.list").write_text("# deb https://dl.google.com/linux/chrome/deb/ stable main\n")
    disabled = tmp_path / "sources.list.d/google-chrome.sources"
    disabled.write_text("Types: deb\nURIs: https://dl.google.com/linux/chrome/deb/\nSuites: stable\nEnabled: no\n")
    assert module._active_google_repo_files(tmp_path) == []
    disabled.write_text("Types: deb\nURIs: https://dl.google.com/linux/chrome/deb/\nSuites: stable\nEnabled: yes\n")
    assert module._active_google_repo_files(tmp_path) == [disabled]
    disabled.write_text("Types: deb\nURIs: https://dl-ssl.google.com/linux/chrome/deb/\nSuites: stable\nEnabled: yes\n")
    assert module._active_google_repo_files(tmp_path) == [disabled]
    backup = tmp_path / "sources.list.d/google-chrome.list.save"
    backup.write_text("deb https://dl.google.com/linux/chrome/deb/ stable main\n")
    assert module._active_google_repo_files(tmp_path) == [disabled]


def test_google_repo_opt_out_preserves_unrelated_defaults(tmp_path: Path):
    module = _load_module()
    defaults = tmp_path / "google-chrome"
    defaults.write_text('repo_add_once="true"\nother_setting="keep"\n', encoding="utf-8")
    module._preconfigure_google_repo_opt_out(defaults)
    text = defaults.read_text(encoding="utf-8")
    assert 'repo_add_once="false"' in text
    assert 'other_setting="keep"' in text
    assert module._repo_opt_out_is_false(defaults)


def test_gdm_and_accounts_service_updates_preserve_unrelated_keys():
    module = _load_module()
    gdm = "[daemon]\nTimedLoginEnable=false\nAutomaticLogin=old\n[security]\nDisallowTCP=true\n"
    updated = module._replace_section_keys(gdm, "daemon", {
        "AutomaticLoginEnable": "true",
        "AutomaticLogin": "kiosk",
        "WaylandEnable": "true",
    })
    assert "AutomaticLogin=kiosk" in updated
    assert "AutomaticLoginEnable=true" in updated
    assert "WaylandEnable=true" in updated
    assert "TimedLoginEnable=false" in updated
    assert "[security]\nDisallowTCP=true" in updated


def test_53a_source_uses_release_owned_chrome_and_display_only_prerequisite():
    runtime = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text()
    prepare = MODULE_PATH.read_text()
    unit = (ROOT / "client/systemd/clientflow-display-runtime.service").read_text()
    prep_unit = (ROOT / "client/systemd/clientflow-display-platform-prepare.service").read_text()
    pyproject = (ROOT / "client/runtime/pyproject.toml").read_text()
    runtime_prepare = (ROOT / "client/release/lib/clientflow_release/runtime_prepare.py").read_text()

    assert '/usr/bin/google-chrome-stable' in runtime
    assert '/var/lib/clientflow/display-runtime' in runtime
    assert '/usr/bin/chromium' not in runtime
    assert '"--remote-debugging-address=127.0.0.1"' in runtime
    assert '"--remote-debugging-port=9222"' in runtime
    assert 'browser_refresh_interval_sec' in runtime
    assert 'GOOGLE_REPOSITORY_MARKER = "google.com/linux/chrome"' in prepare
    assert 'repo_add_once="false"' in prepare
    assert 'Requires=clientflow-display-platform-prepare.service' in unit
    assert 'StateDirectory=clientflow/display-runtime' in unit
    assert 'CLIENTFLOW_KIOSK_USER=@CLIENTFLOW_KIOSK_USER@' in prep_unit
    assert 'Requires=clientflow-platform-prepare.service' in prep_unit
    assert 'clientflow-platform-prepare.service' in next(line for line in prep_unit.splitlines() if line.startswith('After='))
    assert 'clientflow-display-platform-prepare = "clientflow_runtime.display_platform_prepare:main"' in pyproject
    assert '"clientflow-display-platform-prepare"' in runtime_prepare
    for frozen in ("livestream", "remote-desktop", "terminal"):
        assert f"clientflow-{frozen}" not in prep_unit




def test_prepare_gdm_reports_only_real_configuration_changes(monkeypatch, tmp_path):
    module = _load_module()
    real_path = Path
    def platform_path(value):
        if str(value) == "/usr/sbin/gdm3":
            return type("ExistingBinary", (), {"exists": lambda self: True})()
        if str(value) == "/usr/share/wayland-sessions/ubuntu.desktop":
            return type("ExistingSession", (), {"is_file": lambda self: True})()
        return real_path(value)
    monkeypatch.setattr(module, "Path", platform_path)
    gdm = tmp_path / "custom.conf"
    gdm.write_text("[daemon]\nAutomaticLoginEnable=false\nAutomaticLogin=old\nWaylandEnable=true\n", encoding="utf-8")
    assert module._prepare_gdm("kiosk", gdm) is True
    first = gdm.read_text(encoding="utf-8")
    assert "AutomaticLoginEnable=true" in first and "AutomaticLogin=kiosk" in first
    assert module._prepare_gdm("kiosk", gdm) is False
    assert gdm.read_text(encoding="utf-8") == first


def test_display_platform_prepare_does_not_restart_gdm_inside_activation(monkeypatch, tmp_path):
    module = _load_module()
    calls = []
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setenv("CLIENTFLOW_KIOSK_USER", "kiosk")
    monkeypatch.setenv("CLIENTFLOW_RELEASE_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "_load_chrome_artifact", lambda _root: (tmp_path / "chrome.deb", {"package": "google-chrome-stable"}))
    monkeypatch.setattr(module, "_verify_deb_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_active_google_repo_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "_preconfigure_google_repo_opt_out", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_repo_opt_out_is_false", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "_ensure_exact_chrome", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_prepare_graphical_kiosk", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "_prepare_system_kiosk_policy", lambda: None)
    monkeypatch.setattr(module, "_run", lambda command, **_kwargs: calls.append(command) or "")

    module.prepare()

    assert ["/usr/sbin/groupadd", "--system", "--force", "input"] in calls
    assert ["/usr/bin/systemctl", "restart", "gdm3"] not in calls



def test_v2_kiosk_baseline_ports_legacy_golden_behaviour_without_chrome_kiosk_mode():
    module = _load_module()
    settings = set(module._gsettings_commands())
    expected = {
        ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
        ("org.gnome.desktop.screensaver", "idle-activation-enabled", "false"),
        ("org.gnome.desktop.session", "idle-delay", "uint32 0"),
        ("org.gnome.desktop.lockdown", "disable-lock-screen", "true"),
        ("org.gnome.desktop.lockdown", "disable-command-line", "true"),
        ("org.gnome.desktop.lockdown", "disable-user-switching", "false"),
        ("org.gnome.desktop.lockdown", "disable-log-out", "false"),
        ("org.gnome.settings-daemon.plugins.media-keys", "terminal", "[]"),
        ("org.gnome.settings-daemon.plugins.power", "idle-dim", "false"),
        ("org.gnome.settings-daemon.plugins.power", "power-button-action", "'nothing'"),
        ("org.gnome.desktop.notifications", "show-banners", "false"),
    }
    assert expected <= settings

    runtime = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    assert '"--start-fullscreen"' in runtime
    assert '"--kiosk"' not in runtime


def test_kiosk_logind_policy_is_always_on_and_preserves_technician_switching(tmp_path):
    module = _load_module()
    path = tmp_path / "90-clientflow-kiosk.conf"
    module._prepare_logind_kiosk_policy(path)
    text = path.read_text(encoding="utf-8")
    for line in (
        "IdleAction=ignore",
        "IdleActionSec=0",
        "HandlePowerKey=ignore",
        "HandleSuspendKey=ignore",
        "HandleHibernateKey=ignore",
        "HandleLidSwitch=ignore",
    ):
        assert line in text
    settings = set(module._gsettings_commands())
    assert ("org.gnome.desktop.lockdown", "disable-user-switching", "false") in settings
    assert ("org.gnome.desktop.lockdown", "disable-log-out", "false") in settings


def test_kiosk_autostart_suppression_is_scoped_to_kiosk_home(monkeypatch, tmp_path):
    module = _load_module()
    chowns = []
    monkeypatch.setattr(module.os, "chown", lambda path, uid, gid: chowns.append((Path(path), uid, gid)))
    module._prepare_kiosk_autostarts(tmp_path, uid=1000, gid=1000)
    autostart = tmp_path / ".config/autostart"
    assert len(list(autostart.glob("*.desktop"))) == len(module.KIOSK_DISABLED_AUTOSTARTS)
    for name in module.KIOSK_DISABLED_AUTOSTARTS:
        text = (autostart / name).read_text(encoding="utf-8")
        assert "Hidden=true" in text
        assert "X-GNOME-Autostart-enabled=false" in text
    assert all(uid == 1000 and gid == 1000 for _, uid, gid in chowns)


def test_system_kiosk_policy_blocks_bluetooth_and_masks_sleep(monkeypatch, tmp_path):
    module = _load_module()
    calls = []
    fake_rfkill = tmp_path / "rfkill"
    fake_rfkill.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_rfkill.chmod(0o755)
    monkeypatch.setattr(module, "RFKILL_EXECUTABLE", fake_rfkill)
    monkeypatch.setattr(module, "LOGIND_KIOSK_DROPIN", tmp_path / "logind.conf")
    monkeypatch.setattr(module, "_run", lambda command, **_kwargs: calls.append(command) or "")
    module._prepare_system_kiosk_policy()
    assert [str(fake_rfkill), "block", "bluetooth"] in calls
    assert ["/usr/bin/systemctl", "mask", *module.SLEEP_TARGETS] in calls
    assert (tmp_path / "logind.conf").is_file()


def test_display_chrome_dependency_preflight_is_non_mutating_and_rejects_extra_packages(monkeypatch, tmp_path):
    module = _load_module()
    calls = []
    package = tmp_path / "chrome.deb"
    package.write_bytes(b"deb")
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, **_kwargs: calls.append(command)
        or "Inst google-chrome-stable (151.0.7922.173-1 local-deb [amd64])\n",
    )

    module._simulate_local_deb_install(package)

    assert calls == [
        [
            "/usr/bin/apt-get",
            "-o",
            "DPkg::Lock::Timeout=120",
            "-s",
            "--no-install-recommends",
            "install",
            str(package),
        ]
    ]

    monkeypatch.setattr(
        module,
        "_run",
        lambda command, **_kwargs: "\n".join(
            [
                "Inst google-chrome-stable (151.0.7922.173-1 local-deb [amd64])",
                "Inst unexpected-runtime-dependency (1.0 Ubuntu:26.04 [amd64])",
            ]
        ),
    )
    try:
        module._simulate_local_deb_install(package)
    except module.DisplayPlatformPreparationError as exc:
        assert "live dependency-install er ikke tilladt" in str(exc)
        assert "unexpected-runtime-dependency" in str(exc)
    else:
        raise AssertionError("unexpected dependency install was accepted")


def test_display_chrome_exact_local_archive_is_installed_with_dpkg_after_preflight(monkeypatch, tmp_path):
    module = _load_module()
    calls = []
    preflight = []
    package = tmp_path / "chrome.deb"
    package.write_bytes(b"deb")
    states = iter([None, ("install ok installed", "151.0.7922.173-1", "amd64")])
    monkeypatch.setattr(module, "_installed_chrome", lambda: next(states))
    monkeypatch.setattr(module, "_simulate_local_deb_install", lambda path: preflight.append(path))
    monkeypatch.setattr(module, "_run", lambda command, **_kwargs: calls.append(command) or "")
    monkeypatch.setattr(module, "CHROME_EXECUTABLE", tmp_path / "google-chrome-stable")
    module.CHROME_EXECUTABLE.write_text("#!/bin/sh\n", encoding="utf-8")
    module.CHROME_EXECUTABLE.chmod(0o755)

    module._ensure_exact_chrome(package, {"version": "151.0.7922.173-1", "architecture": "amd64"})

    assert preflight == [package]
    assert calls == [["/usr/bin/dpkg", "--install", str(package)]]
    assert not any("--no-download" in command for command in calls)


def test_kiosk_application_lockdown_is_user_scoped(monkeypatch, tmp_path):
    module = _load_module()
    chowns = []
    monkeypatch.setattr(module.os, "chown", lambda path, uid, gid: chowns.append((Path(path), uid, gid)))
    module._prepare_kiosk_application_lockdown(tmp_path, uid=1000, gid=1000)
    applications = tmp_path / ".local/share/applications"
    assert len(list(applications.glob("*.desktop"))) == len(module.KIOSK_BLOCKED_DESKTOP_IDS)
    for desktop_id in module.KIOSK_BLOCKED_DESKTOP_IDS:
        text = (applications / desktop_id).read_text(encoding="utf-8")
        assert "Hidden=true" in text
        assert "X-ClientFlow-Kiosk-Lockdown=true" in text
    assert all(uid == 1000 and gid == 1000 for _, uid, gid in chowns)


def test_kiosk_polkit_lockdown_denies_admin_domains_but_not_generic_login1(tmp_path):
    module = _load_module()
    path = tmp_path / "90-clientflow-kiosk.rules"
    module._prepare_kiosk_polkit_policy("kiosk", path)
    text = path.read_text(encoding="utf-8")
    assert 'subject.user !== "kiosk"' in text
    for denied in (
        "org.freedesktop.packagekit.",
        "org.freedesktop.NetworkManager.",
        "org.bluez.",
        "org.freedesktop.systemd1.",
        "org.freedesktop.login1.power-off",
        "org.freedesktop.login1.reboot",
    ):
        assert denied in text
    assert '"org.freedesktop.login1."' not in text
    assert "polkit.Result.NOT_HANDLED" in text


def test_kiosk_binary_acl_is_only_applied_to_existing_non_symlink_targets(monkeypatch, tmp_path):
    module = _load_module()
    binary = tmp_path / "gnome-control-center"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(binary)
    missing = tmp_path / "missing"
    monkeypatch.setattr(module, "KIOSK_BLOCKED_BINARIES", (str(binary), str(symlink), str(missing)))
    calls = []
    monkeypatch.setattr(module, "_run", lambda command, **_kwargs: calls.append(command) or "")
    module._prepare_kiosk_binary_acl("kiosk")
    assert calls == [["/usr/bin/setfacl", "-m", "u:kiosk:---", str(binary)]]
