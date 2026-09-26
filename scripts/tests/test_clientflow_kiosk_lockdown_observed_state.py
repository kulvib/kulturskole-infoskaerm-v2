from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from clientflow_runtime import kiosk_lockdown


def _account(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    record = SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_dir=str(home))
    return "clientflow-kiosk", record, home


def test_status_reports_drift_from_real_enforcement_not_saved_applied(tmp_path, monkeypatch):
    user, record, home = _account(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(
        '{"schema_version":1,"desired":true,"status":"applied","message":"old","updated_at":"2026-09-26T00:00:00Z"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(kiosk_lockdown, "STATE_PATH", state)
    monkeypatch.setattr(kiosk_lockdown, "_account", lambda: (user, record, home))
    monkeypatch.setattr(
        kiosk_lockdown,
        "_verify",
        lambda *_args, **_kwargs: {
            "ok": False,
            "checks": {"launchers": True, "acl": False, "polkit": True, "gsettings": True, "quick_guard": True},
            "drift": ["acl:/usr/bin/gnome-terminal"],
        },
    )

    result = kiosk_lockdown.status()

    assert result["desired"] is True
    assert result["status"] == "drifted"
    assert "acl:/usr/bin/gnome-terminal" in result["message"]
    assert result["enforcement"]["ok"] is False


def test_apply_refuses_to_publish_applied_when_verification_fails(tmp_path, monkeypatch):
    user, record, home = _account(tmp_path)
    monkeypatch.setattr(kiosk_lockdown, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(kiosk_lockdown, "_account", lambda: (user, record, home))
    monkeypatch.setattr(kiosk_lockdown, "_hide_launchers", lambda *_args: None)
    monkeypatch.setattr(kiosk_lockdown, "_apply_acl", lambda *_args: None)
    monkeypatch.setattr(kiosk_lockdown, "_apply_polkit", lambda *_args: None)
    monkeypatch.setattr(kiosk_lockdown, "_apply_gsettings", lambda *_args: None)
    monkeypatch.setattr(kiosk_lockdown, "_set_quick_guard_running", lambda *_args: None)
    monkeypatch.setattr(
        kiosk_lockdown,
        "_verify",
        lambda *_args, **_kwargs: {
            "ok": False,
            "checks": {"launchers": True, "acl": True, "polkit": False, "gsettings": True, "quick_guard": True},
            "drift": ["polkit"],
        },
    )

    try:
        kiosk_lockdown.apply()
    except kiosk_lockdown.KioskLockdownError:
        pass
    else:
        raise AssertionError("apply must fail closed when enforcement cannot be verified")

    saved = kiosk_lockdown._saved_state()
    assert saved is not None
    assert saved["desired"] is True
    assert saved["status"] == "error"
    assert saved["enforcement"]["ok"] is False


def test_disabled_status_detects_residual_policy(tmp_path, monkeypatch):
    user, record, home = _account(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(
        '{"schema_version":1,"desired":false,"status":"disabled","message":"old","updated_at":"2026-09-26T00:00:00Z"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(kiosk_lockdown, "STATE_PATH", state)
    monkeypatch.setattr(kiosk_lockdown, "_account", lambda: (user, record, home))
    monkeypatch.setattr(
        kiosk_lockdown,
        "_verify",
        lambda *_args, **_kwargs: {
            "ok": False,
            "checks": {"launchers": True, "acl": True, "polkit": False, "gsettings": True, "quick_guard": True},
            "drift": ["polkit-residual"],
        },
    )

    result = kiosk_lockdown.status()

    assert result["desired"] is False
    assert result["status"] == "drifted"
    assert "polkit-residual" in result["message"]
