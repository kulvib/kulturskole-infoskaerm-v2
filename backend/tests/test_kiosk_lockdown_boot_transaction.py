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




def test_ready_wayland_session_converges_gnome_baseline_before_lockdown(monkeypatch, tmp_path: Path) -> None:
    user, record, _home = _account(tmp_path)
    monkeypatch.setattr(lockdown, "_active_local_kiosk_session", lambda: "2")
    original_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: True if str(self) == f"/run/user/{record.pw_uid}/bus" else original_exists(self),
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        lockdown,
        "_run",
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(returncode=0, stdout=""),
    )
    monkeypatch.setattr(
        lockdown,
        "_gsettings_value",
        lambda _user, _record, schema, key: next(
            expected for expected_schema, expected_key, expected in lockdown.ENFORCED_GSETTINGS
            if expected_schema == schema and expected_key == key
        ),
    )

    lockdown._require_gsettings_baseline_ready(user, record)

    writes = [command for command in commands if "/usr/bin/gsettings" in command and "set" in command]
    assert len(writes) == len(lockdown.ENFORCED_GSETTINGS)
    for schema, key, expected in lockdown.ENFORCED_GSETTINGS:
        assert any(command[-4:] == ["set", schema, key, expected] for command in writes)


def test_unready_wayland_session_does_not_attempt_gsettings_convergence(monkeypatch, tmp_path: Path) -> None:
    user, record, _home = _account(tmp_path)
    monkeypatch.setattr(lockdown, "_active_local_kiosk_session", lambda: None)
    commands: list[list[str]] = []
    monkeypatch.setattr(lockdown, "_run", lambda command, **_kwargs: commands.append(command))

    with pytest.raises(lockdown.KioskLockdownError, match="seat0 Wayland"):
        lockdown._require_gsettings_baseline_ready(user, record)

    assert commands == []


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


@pytest.mark.parametrize(
    ("actual", "expected", "matches"),
    [
        ("[]", "[]", True),
        ("@as []", "[]", True),
        ("['<Primary><Alt>t']", "[]", False),
        ("@as ['<Primary><Alt>t']", "[]", False),
        ("", "[]", False),
        (None, "[]", False),
        ("false", "false", True),
        ("true", "false", False),
        ("@as []", "false", False),
    ],
)
def test_gsettings_comparison_accepts_typed_empty_array_without_weaker_enforcement(
    actual, expected, matches
) -> None:
    assert lockdown._gsettings_matches(actual, expected) is matches


def test_gnome_baseline_accepts_actual_typed_empty_terminal_shortcut(monkeypatch, tmp_path: Path) -> None:
    user, record, _home = _account(tmp_path)
    monkeypatch.setattr(lockdown, "_active_local_kiosk_session", lambda: "1")
    original_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: True if str(self) == f"/run/user/{record.pw_uid}/bus" else original_exists(self),
    )
    monkeypatch.setattr(lockdown, "_run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0))

    def readback(_user, _record, schema, key):
        expected = next(value for s, k, value in lockdown.ENFORCED_GSETTINGS if (s, k) == (schema, key))
        return "@as []" if key == "terminal" else expected

    monkeypatch.setattr(lockdown, "_gsettings_value", readback)
    lockdown._require_gsettings_baseline_ready(user, record)

    monkeypatch.setattr(
        lockdown, "_gsettings_value",
        lambda _u, _r, schema, key: "['<Primary><Alt>t']" if key == "terminal" else readback(_u, _r, schema, key),
    )
    with pytest.raises(lockdown.KioskLockdownError, match="media-keys/terminal"):
        lockdown._require_gsettings_baseline_ready(user, record)
