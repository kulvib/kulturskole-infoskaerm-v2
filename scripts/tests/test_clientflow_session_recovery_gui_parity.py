from __future__ import annotations

import json
import os
from pathlib import Path

from clientflow_runtime import display_platform_prepare as platform

ROOT = Path(__file__).resolve().parents[2]


def test_popup_baseline_matches_legacy_for_existing_human_profile(tmp_path):
    home = tmp_path / "human"
    profile = home / ".mozilla/firefox/abc.default-release"
    profile.mkdir(parents=True)
    platform._prepare_existing_firefox_profiles(home, uid=os.getuid(), gid=os.getgid())
    prefs = (profile / "user.js").read_text(encoding="utf-8")
    for token in (
        'browser.shell.checkDefaultBrowser', 'browser.sessionstore.resume_from_crash',
        'browser.aboutwelcome.enabled', 'dom.webnotifications.enabled',
        'permissions.default.desktop-notification', 'toolkit.telemetry.enabled', 'extensions.pocket.enabled',
    ):
        assert token in prefs


def test_firefox_enterprise_policy_and_apport_are_materialized(tmp_path):
    policy = tmp_path / "etc/firefox/policies/policies.json"
    install_policy = tmp_path / "usr/lib/firefox/distribution/policies.json"
    platform._prepare_firefox_popup_policy(policy, install_path=install_policy)
    assert policy.read_bytes() == install_policy.read_bytes()
    data = json.loads(policy.read_text(encoding="utf-8"))["policies"]
    assert data["DisableAppUpdate"] is True
    assert data["DisableFirefoxAccounts"] is True
    assert data["DisablePocket"] is True
    assert data["PasswordManagerEnabled"] is False
    assert data["Preferences"]["dom.webnotifications.enabled"]["Status"] == "locked"

    apport = tmp_path / "etc/default/apport"
    apport.parent.mkdir(parents=True)
    apport.write_text("enabled=1\n", encoding="utf-8")
    platform._prepare_apport_disabled(apport, disable_service=False)
    assert apport.read_text(encoding="utf-8") == "enabled=0\n"


def test_popup_baseline_applies_to_kiosk_and_cfadmin_source_contract():
    source = (ROOT / "client/runtime/clientflow_runtime/display_platform_prepare.py").read_text(encoding="utf-8")
    assert "for username in (kiosk_user, cfadmin_user)" in source
    assert "_prepare_existing_firefox_profiles" in source
    assert '"firefox.desktop"' in source
    assert '"/usr/bin/pkill"' in source
    assert "_prepare_apport_disabled()" in source


def test_local_gui_restores_legacy_status_surface_without_credentials():
    source = (ROOT / "client/libexec/local-gui").read_text(encoding="utf-8")
    for label in ("Backend sync", "Kalender service", "Aktuel skærm", "Backend-valgt", "Skærmstatus", "Dvale – online, skærm slukket"):
        assert label in source
    assert "RESOLUTION_DESIRED_PATH" in source
    assert "/etc/clientflow/credentials" not in source
    assert "DomainCredential" not in source


def test_backend_selected_resolution_is_materialized_as_local_non_secret_state():
    source = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    assert "DISPLAY_RESOLUTION_DESIRED_PATH" in source
    assert '"mode": str(payload.get("mode") or "auto")' in source
    assert '"width": payload.get("width")' in source
    assert '"rotation": str(payload.get("rotation") or "normal")' in source
