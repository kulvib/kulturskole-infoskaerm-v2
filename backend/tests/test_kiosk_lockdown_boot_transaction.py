from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "client/runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from clientflow_runtime import kiosk_lockdown as lockdown  # noqa: E402


def _account(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    return "clientflow-kiosk", SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_dir=str(home)), home


def test_nautilus_is_never_denied_but_legacy_acl_is_cleanup_authority() -> None:
    assert "/usr/bin/nautilus" not in lockdown.TARGET_BINARIES
    assert "/usr/bin/nautilus" in lockdown.ACL_CLEANUP_BINARIES


def test_apply_rejects_unready_gnome_session_before_restrictive_mutations(monkeypatch, tmp_path: Path) -> None:
    account = _account(tmp_path)
    monkeypatch.setattr(lockdown, "_account", lambda: account)
    monkeypatch.setattr(
        lockdown,
        "_require_gsettings_baseline_ready",
        lambda *_args: (_ for _ in ()).throw(lockdown.KioskLockdownError("GNOME ikke klar")),
    )
    mutations: list[str] = []
    monkeypatch.setattr(lockdown, "_hide_launchers", lambda *_args: mutations.append("launchers"))
    monkeypatch.setattr(lockdown, "_apply_acl", lambda *_args: mutations.append("acl"))
    monkeypatch.setattr(lockdown, "_apply_polkit", lambda *_args: mutations.append("polkit"))
    monkeypatch.setattr(lockdown, "_set_quick_guard_running", lambda *_args: mutations.append("guard"))

    with pytest.raises(lockdown.KioskLockdownError, match="GNOME ikke klar"):
        lockdown.apply()

    assert mutations == []


def test_apply_failure_rolls_back_every_owned_surface_before_retry(monkeypatch, tmp_path: Path) -> None:
    account = _account(tmp_path)
    monkeypatch.setattr(lockdown, "_account", lambda: account)
    monkeypatch.setattr(lockdown, "_require_gsettings_baseline_ready", lambda *_args: None)

    calls: list[str] = []
    states: list[tuple[bool, str]] = []
    monkeypatch.setattr(lockdown, "_write_state", lambda desired, status, *_args, **_kwargs: states.append((desired, status)) or {})
    monkeypatch.setattr(lockdown, "_apply_gsettings", lambda *_args, **_kwargs: calls.append(f"gsettings:{_args[-1] if _args else '?'}"))
    monkeypatch.setattr(lockdown, "_hide_launchers", lambda *_args: calls.append("launchers:on"))
    monkeypatch.setattr(lockdown, "_restore_launchers", lambda *_args: calls.append("launchers:off"))
    monkeypatch.setattr(lockdown, "_apply_acl", lambda _user, enabled: calls.append(f"acl:{enabled}"))
    monkeypatch.setattr(lockdown, "_apply_polkit", lambda _user, enabled: calls.append(f"polkit:{enabled}"))

    def guard(enabled: bool) -> None:
        calls.append(f"guard:{enabled}")
        if enabled:
            raise lockdown.KioskLockdownError("guard apply failed")

    monkeypatch.setattr(lockdown, "_set_quick_guard_running", guard)
    monkeypatch.setattr(
        lockdown,
        "_verify",
        lambda *_args, enabled, **_kwargs: {"ok": not enabled, "checks": {}, "drift": []},
    )

    with pytest.raises(lockdown.KioskLockdownError, match="guard apply failed"):
        lockdown.apply()

    assert calls[:5] == ["gsettings:True", "launchers:on", "acl:True", "polkit:True", "guard:True"]
    assert "guard:False" in calls
    assert "launchers:off" in calls
    assert "acl:False" in calls
    assert "polkit:False" in calls
    assert "gsettings:False" in calls
    assert states[0] == (True, "applying")
    assert states[-1] == (True, "error")
