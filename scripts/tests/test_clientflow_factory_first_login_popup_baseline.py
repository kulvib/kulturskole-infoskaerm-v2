from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "client/bootstrap/clientflow_bootstrap_common.py"
PLATFORM = ROOT / "client/runtime/clientflow_runtime/display_platform_prepare.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_factory_popup_list_matches_activation_time_popup_authority() -> None:
    common = _load(COMMON, "clientflow_factory_popup_common_list")
    platform = _load(PLATFORM, "clientflow_factory_popup_platform_list")
    assert common._FACTORY_DISABLED_AUTOSTARTS == platform.KIOSK_DISABLED_AUTOSTARTS
    # Ubuntu 26.04 update-notifier ships this additional XDG autostart.
    # It is specifically an Ubuntu Pro/Advantage notification launcher and
    # must be suppressed before either human account's first graphical login.
    assert "ubuntu-advantage-notification.desktop" in common._FACTORY_DISABLED_AUTOSTARTS


def test_factory_popup_autostarts_are_materialized_and_validated_before_first_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load(COMMON, "clientflow_factory_popup_common_materialize")
    users: dict[str, SimpleNamespace] = {}
    for username in (module.KIOSK_USER, module.ADMIN_USER):
        home = tmp_path / username
        home.mkdir(mode=0o700)
        users[username] = SimpleNamespace(
            pw_uid=home.stat().st_uid,
            pw_gid=home.stat().st_gid,
            pw_dir=str(home),
        )

    monkeypatch.setattr(module.pwd, "getpwnam", lambda username: users[username])
    monkeypatch.setattr(module, "validate_local_user", lambda username: username)
    monkeypatch.setattr(module.os, "chown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.os, "fchown", lambda *_args, **_kwargs: None)

    for username in (module.KIOSK_USER, module.ADMIN_USER):
        module.prepare_factory_popup_autostarts(username)
        module.validate_factory_popup_autostarts(username)
        autostart = Path(users[username].pw_dir) / ".config/autostart"
        assert autostart.stat().st_mode & 0o777 == 0o700
        assert {path.name for path in autostart.glob("*.desktop")} == set(module._FACTORY_DISABLED_AUTOSTARTS)
        for name in module._FACTORY_DISABLED_AUTOSTARTS:
            path = autostart / name
            assert path.stat().st_mode & 0o777 == 0o644
            text = path.read_text(encoding="utf-8")
            assert text == module._factory_disabled_autostart_content(name)
            assert "Hidden=true" in text
            assert "X-GNOME-Autostart-enabled=false" in text


def test_factory_provisioning_prepares_gnome_and_popup_suppression_for_both_accounts() -> None:
    source = COMMON.read_text(encoding="utf-8")
    provision = source[
        source.index("def provision_factory_human_accounts") : source.index("def _replace_ini_section_keys")
    ]
    assert "for username in (KIOSK_USER, ADMIN_USER):" in provision
    assert provision.index("prepare_factory_gnome_initial_setup_markers(username)") < provision.index(
        "prepare_factory_popup_autostarts(username)"
    )


def test_factory_handoff_fails_closed_on_gnome_and_popup_baselines() -> None:
    source = COMMON.read_text(encoding="utf-8")
    handoff = source[source.index("def validate_factory_handoff") : source.index("def load_usb_state")]
    ready = "write_factory_state(client_name=client_name, operator_user=operator_user, handoff_ready=True)"
    assert "for username in (KIOSK_USER, ADMIN_USER):" in handoff
    assert handoff.index("validate_factory_gnome_initial_setup_markers(username)") < handoff.index(
        "validate_factory_popup_autostarts(username)"
    )
    assert handoff.index("validate_factory_popup_autostarts(username)") < handoff.index(ready)
