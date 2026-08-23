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
    assert 'remote-debugging' not in runtime
    assert 'browser_refresh_interval_sec' not in runtime
    assert 'GOOGLE_REPOSITORY_MARKER = "google.com/linux/chrome"' in prepare
    assert 'repo_add_once="false"' in prepare
    assert 'Requires=clientflow-display-platform-prepare.service' in unit
    assert 'StateDirectory=clientflow/display-runtime' in unit
    assert 'CLIENTFLOW_KIOSK_USER=@CLIENTFLOW_KIOSK_USER@' in prep_unit
    assert 'clientflow-display-platform-prepare = "clientflow_runtime.display_platform_prepare:main"' in pyproject
    assert '"clientflow-display-platform-prepare"' in runtime_prepare
    for frozen in ("livestream", "remote-desktop", "terminal"):
        assert f"clientflow-{frozen}" not in prep_unit


