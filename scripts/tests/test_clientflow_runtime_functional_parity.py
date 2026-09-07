from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "client/runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from clientflow_runtime import display_local_control, display_runtime  # noqa: E402


def test_presence_contract_is_15_seconds_and_120_seconds():
    runtime = (ROOT / "client/runtime/clientflow_runtime/constants.py").read_text(encoding="utf-8")
    backend = (ROOT / "backend/service1/client_presence.py").read_text(encoding="utf-8")
    assert "SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 15" in runtime
    assert "SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 15" in backend
    assert "SHARED_DOMAIN_MISSED_REPORT_LIMIT = 8" in backend


def test_canonical_kiosk_user_is_allowed_but_service_identities_are_not():
    source = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text(encoding="utf-8")
    assert 'value.startswith("clientflow") and value != "clientflow-kiosk"' in source


def test_bare_hostname_normalizes_to_https():
    assert display_runtime.DisplayRuntime._normalize_kiosk_url("example.dk") == "https://example.dk"
    assert display_runtime.DisplayRuntime._normalize_kiosk_url("https://example.dk/a") == "https://example.dk/a"
    with pytest.raises(ValueError):
        display_runtime.DisplayRuntime._normalize_kiosk_url("http://example.dk")


def test_display_sleep_stops_browser_before_countdown_and_power(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(display_local_control, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(display_local_control, "POWER_STATE_PATH", tmp_path / "power.json")
    monkeypatch.setattr(display_local_control, "call", lambda socket, payload, **kwargs: calls.append((socket, payload)) or {"ok": True})
    result = display_local_control.set_display_power("off")
    assert result == {"ok": True}
    assert [payload["action"] for _, payload in calls[:3]] == [
        "stop_browser",
        "display_sleep_countdown",
        "set_display_power",
    ]


def test_clean_uncommanded_browser_exit_becomes_manual_close(monkeypatch, tmp_path):
    source = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    clean_branch = source[source.index("if code == 0:"):source.index("if self.local_gui and self.local_gui.poll() is not None:")]
    assert "self.browser_requested = False" in clean_branch
    assert 'self._status("stopped", step="chrome_closed_manual"' in clean_branch
    assert "time.monotonic() + 5.0" in clean_branch  # crash retry remains in the non-zero branch


def test_manual_close_projects_separately_from_programmatic_stop():
    source = (ROOT / "backend/service1/display_control.py").read_text(encoding="utf-8")
    assert 'if runtime_step == "chrome_closed_manual":' in source
    assert 'chrome_status = "Browser lukket manuelt"' in source


def test_chrome_early_protection_uses_cdp_before_real_navigation():
    source = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    assert '"Page.addScriptToEvaluateOnNewDocument"' in source
    assert '"Page.navigate"' in source
    helper = source[source.index("async def _cdp_register_and_navigate"):source.index("def _install_early_protection_and_navigate")]
    assert helper.index('"Page.addScriptToEvaluateOnNewDocument"') < helper.index('"Page.navigate"')
    command = source[source.index("def _browser_command"):source.index("def _early_protection_script")]
    assert '"about:blank"' in command
    assert 'str(kiosk_url),' not in command


def test_chrome_early_protection_contains_legacy_hard_hide_surface():
    source = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    for selector in (
        "#coiOverlay",
        "#CybotCookiebotDialog",
        "#CookiebotWidgetUnderlay",
        "#usercentrics-root",
        "#onetrust-banner-sdk",
        ".qc-cmp2-container",
        '[id*="cookie-consent" i]',
        'iframe[src*="quantcast" i]',
    ):
        assert selector in source


def test_chrome_early_protection_failure_is_fail_closed_not_waiting_session():
    source = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    start = source[source.index("def start_browser"):source.index("def request_start_browser")]
    assert '_status("waiting_session"' in start
    assert '_install_early_protection_and_navigate(kiosk_url)' in start
    assert '_status("failed", error=f"early_protection_failed:' in start
    assert start.index('_status("waiting_session"') < start.index('_install_early_protection_and_navigate(kiosk_url)') < start.index('_status("failed"')
