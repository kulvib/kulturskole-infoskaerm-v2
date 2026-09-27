from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_kiosk_notification_baseline_is_always_fail_closed() -> None:
    session = (ROOT / "client/runtime/clientflow_runtime/kiosk_session_policy.py").read_text(encoding="utf-8")
    lockdown = (ROOT / "client/runtime/clientflow_runtime/kiosk_lockdown.py").read_text(encoding="utf-8")

    assert '("org.gnome.desktop.notifications", "show-banners", "false")' in session
    assert '("org.gnome.desktop.notifications", "show-in-lock-screen", "false")' in session
    assert '("org.gnome.desktop.notifications", "show-banners", "true")' not in session

    assert 'KIOSK_NOTIFICATION_BASELINE' in lockdown
    assert '("org.gnome.desktop.notifications", "show-banners", "false")' in lockdown
    assert '("org.gnome.desktop.notifications", "show-in-lock-screen", "false")' in lockdown
    assert '("org.gnome.desktop.notifications", "show-banners", "true")' not in lockdown
    assert 'for schema, key, value in KIOSK_NOTIFICATION_BASELINE' in lockdown


def test_lockdown_verification_includes_notification_baseline() -> None:
    lockdown = (ROOT / "client/runtime/clientflow_runtime/kiosk_lockdown.py").read_text(encoding="utf-8")
    enforced = lockdown[lockdown.index("ENFORCED_GSETTINGS = (") : lockdown.index("OPTIONAL_GSETTINGS = (")]
    assert "*KIOSK_NOTIFICATION_BASELINE" in enforced
    verify = lockdown[lockdown.index("def _verify(") : lockdown.index("def _write_blocked(")]
    assert "for schema, key, expected in ENFORCED_GSETTINGS" in verify


def test_lockdown_rollback_does_not_reset_notification_baseline() -> None:
    lockdown = (ROOT / "client/runtime/clientflow_runtime/kiosk_lockdown.py").read_text(encoding="utf-8")
    apply_settings = lockdown[lockdown.index("def _apply_gsettings(") : lockdown.index("def _set_quick_guard_running(")]
    assert 'if enabled else [*base, "reset", schema, key]' in apply_settings
    assert 'for schema, key, value in KIOSK_NOTIFICATION_BASELINE' in apply_settings
    assert '_run([*base, "set", schema, key, value], required=False)' in apply_settings
