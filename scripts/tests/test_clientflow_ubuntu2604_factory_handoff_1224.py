from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "client/bootstrap/clientflow_bootstrap_common.py"
FRESH = ROOT / "client/bootstrap/clientflow-fresh-install"
SYSTEM_BROKER = ROOT / "client/runtime/clientflow_runtime/system_broker.py"
CALENDAR_BROKER = ROOT / "client/runtime/clientflow_runtime/calendar_reboot_broker.py"


def _load_common():
    name = "clientflow_bootstrap_common_ubuntu2604_test"
    spec = importlib.util.spec_from_file_location(name, COMMON)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _pretend_accountsservice_record_is_root_owned(
    module, monkeypatch: pytest.MonkeyPatch, record: Path
) -> None:
    real_lstat = module.Path.lstat

    def lstat_with_root_owner(path: Path):
        meta = real_lstat(path)
        if path == record:
            return SimpleNamespace(st_mode=meta.st_mode, st_uid=0)
        return meta

    monkeypatch.setattr(module.Path, "lstat", lstat_with_root_owner)


def test_sudo_rs_activation_capability_is_exact_no_args_without_digest() -> None:
    source = COMMON.read_text(encoding="utf-8")
    fn = source[
        source.index("def install_customer_activation_sudoers") : source.index(
            "def remove_customer_activation_sudoers"
        )
    ]

    assert "sha256:" not in fn
    assert "hashlib" not in fn
    assert 'f"{KIOSK_USER} ALL=(root) NOPASSWD: {helper} \\\"\\\"\\n"' in fn
    assert "PERSISTENT_ROOT.lstat()" in fn
    assert "stat.S_ISLNK(parent_meta.st_mode)" in fn
    assert "parent_meta.st_uid != 0" in fn
    assert "parent_meta.st_mode & 0o022" in fn
    assert "stat.S_ISLNK(meta.st_mode)" in fn
    assert "meta.st_uid != 0" in fn
    assert "meta.st_mode & 0o022" in fn
    assert '[str(VISUDO), "-cf", str(FACTORY_ACTIVATION_SUDOERS)]' in fn
    assert "FACTORY_ACTIVATION_SUDOERS.unlink(missing_ok=True)" in fn


def test_netplan_cleanup_removes_all_shipping_connection_subtrees_and_regenerates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_common()
    netplan = tmp_path / "netplan"
    netplan.write_text("#!/bin/sh\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()

    monkeypatch.setattr(module, "NETPLAN", netplan)
    monkeypatch.setattr(module, "_NETWORKMANAGER_GENERATED_ROOT", generated)

    calls: list[tuple[list[str], int]] = []

    def fake_run(command: list[str], *, timeout: int = 30, check: bool = False):
        calls.append((command, timeout))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(module, "_run", fake_run)

    module._forget_persistent_netplan_networks()

    expected_keys = (
        "network.ethernets",
        "network.wifis",
        "network.modems",
        "network.tunnels",
        "network.nm-devices",
    )
    assert calls[:-1] == [
        ([str(netplan), "set", f"{key}=null"], 30) for key in expected_keys
    ]
    assert calls[-1] == ([str(netplan), "generate"], 60)


def test_persistent_cleanup_fails_closed_if_netplan_can_regenerate_shipping_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_common()
    netplan = tmp_path / "netplan"
    netplan.write_text("#!/bin/sh\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "netplan-wlo1-factory.nmconnection").write_text(
        "[connection]\nid=factory\ntype=wifi\nuuid=00000000-0000-4000-8000-000000000001\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "NETPLAN", netplan)
    monkeypatch.setattr(module, "_NETWORKMANAGER_GENERATED_ROOT", generated)
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, *, timeout=30, check=False: SimpleNamespace(returncode=0, stdout=""),
    )

    with pytest.raises(module.BootstrapError, match="kan regenereres"):
        module._validate_persistent_network_cleanup()


def test_factory_handoff_revalidates_persistent_netplan_before_ready_state() -> None:
    source = COMMON.read_text(encoding="utf-8")
    fn = source[source.index("def validate_factory_handoff") : source.index("def load_usb_state")]
    assert fn.index("_validate_persistent_network_cleanup()") < fn.index(
        "write_factory_state(client_name=client_name, operator_user=operator_user, handoff_ready=True)"
    )


def test_systemd_259_documented_inhibitor_override_is_used_by_all_reboot_authorities() -> None:
    common = COMMON.read_text(encoding="utf-8")
    fresh = FRESH.read_text(encoding="utf-8")
    system_broker = SYSTEM_BROKER.read_text(encoding="utf-8")
    calendar_broker = CALENDAR_BROKER.read_text(encoding="utf-8")
    sources = {
        "bootstrap common": common[common.index("def confirmed_reboot") : common.index("def install_persistent_bootstrap")],
        "fresh install": fresh[fresh.index("def _queue_controlled_pre_activation_reboot") : fresh.index("def _prompt")],
        "system broker": system_broker[system_broker.index("def _cross_update_reboot_boundary") : system_broker.index("def _execute")],
        "calendar broker": calendar_broker[calendar_broker.index("def handle") : calendar_broker.index("def main")],
    }
    for label, source in sources.items():
        assert "--ignore-inhibitors" not in source, label
        assert "--check-inhibitors=no" in source, label
        assert "--force" not in source, label


def test_factory_creates_gnome_first_login_and_upgrade_markers_before_first_reboot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_common()
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Ubuntu"\nVERSION_ID="26.04"\n', encoding="utf-8")

    users = {}
    for index, username in enumerate((module.KIOSK_USER, module.ADMIN_USER), start=1001):
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
        module.prepare_factory_gnome_initial_setup_markers(username, os_release=os_release)
        home = Path(users[username].pw_dir)
        first = home / ".config/gnome-initial-setup-done"
        upgrade = home / ".config/gnome-initial-setup/upgrade-26.04-done"
        assert first.read_text(encoding="utf-8") == "yes\n"
        assert upgrade.read_text(encoding="utf-8") == "yes\n"
        assert first.stat().st_mode & 0o777 == 0o600
        assert upgrade.stat().st_mode & 0o777 == 0o600
        module.validate_factory_gnome_initial_setup_markers(username, os_release=os_release)


def test_factory_provisioning_materializes_onboarding_markers_for_both_human_accounts() -> None:
    source = COMMON.read_text(encoding="utf-8")
    provision = source[source.index("def provision_factory_human_accounts") : source.index("def _replace_ini_section_keys")]
    assert "for username in (KIOSK_USER, ADMIN_USER):" in provision
    assert "prepare_factory_gnome_initial_setup_markers(username)" in provision


def test_factory_handoff_fails_closed_unless_both_onboarding_markers_are_validated() -> None:
    source = COMMON.read_text(encoding="utf-8")
    handoff = source[source.index("def validate_factory_handoff") : source.index("def load_usb_state")]
    marker_check = "validate_factory_gnome_initial_setup_markers(username)"
    ready = "write_factory_state(client_name=client_name, operator_user=operator_user, handoff_ready=True)"
    assert "for username in (KIOSK_USER, ADMIN_USER):" in handoff
    assert handoff.index(marker_check) < handoff.index(ready)


def test_factory_provisioning_hides_virtual_home_before_first_kiosk_login() -> None:
    source = COMMON.read_text(encoding="utf-8")
    provision = source[source.index("def provision_factory_human_accounts") : source.index("def _replace_ini_section_keys")]
    settings = source[source.index("def _factory_kiosk_desktop_settings") : source.index("def provision_factory_human_accounts")]
    assert '("org.gnome.shell.extensions.ding", "show-home", "false")' in settings
    assert '("org.gnome.shell.extensions.ding", "show-trash", "false")' in settings
    assert "prepare_factory_kiosk_desktop_settings(KIOSK_USER)" in provision


def test_factory_handoff_fails_closed_unless_kiosk_desktop_icons_are_hidden() -> None:
    source = COMMON.read_text(encoding="utf-8")
    handoff = source[source.index("def validate_factory_handoff") : source.index("def load_usb_state")]
    desktop_check = "validate_factory_kiosk_desktop_settings(KIOSK_USER)"
    ready = "write_factory_state(client_name=client_name, operator_user=operator_user, handoff_ready=True)"
    assert desktop_check in handoff
    assert handoff.index(desktop_check) < handoff.index(ready)


def test_factory_kiosk_desktop_settings_use_same_ding_contract_as_runtime() -> None:
    bootstrap = COMMON.read_text(encoding="utf-8")
    runtime = (ROOT / "client/runtime/clientflow_runtime/display_platform_prepare.py").read_text(encoding="utf-8")
    for setting in (
        '("org.gnome.shell.extensions.ding", "show-home", "false")',
        '("org.gnome.shell.extensions.ding", "show-trash", "false")',
    ):
        assert setting in bootstrap
        assert setting in runtime


def test_factory_kiosk_desktop_prepare_sets_and_reads_back_both_virtual_icons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_common()
    calls: list[tuple[str, str, str, str, str | None]] = []

    def fake_gsettings(user: str, action: str, schema: str, key: str, value: str | None = None) -> str:
        calls.append((user, action, schema, key, value))
        return "false" if action == "get" else ""

    monkeypatch.setattr(module, "_factory_user_gsettings", fake_gsettings)
    monkeypatch.setattr(module, "validate_local_user", lambda username: username)

    module.prepare_factory_kiosk_desktop_settings(module.KIOSK_USER)

    expected = [
        (module.KIOSK_USER, "set", "org.gnome.shell.extensions.ding", "show-home", "false"),
        (module.KIOSK_USER, "set", "org.gnome.shell.extensions.ding", "show-trash", "false"),
        (module.KIOSK_USER, "get", "org.gnome.shell.extensions.ding", "show-home", None),
        (module.KIOSK_USER, "get", "org.gnome.shell.extensions.ding", "show-trash", None),
    ]
    assert calls == expected


def test_factory_kiosk_desktop_validation_fails_closed_if_home_is_still_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_common()

    def fake_gsettings(user: str, action: str, schema: str, key: str, value: str | None = None) -> str:
        assert user == module.KIOSK_USER
        assert action == "get"
        return "true" if key == "show-home" else "false"

    monkeypatch.setattr(module, "_factory_user_gsettings", fake_gsettings)
    monkeypatch.setattr(module, "validate_local_user", lambda username: username)

    with pytest.raises(module.BootstrapError, match="show-home"):
        module.validate_factory_kiosk_desktop_settings(module.KIOSK_USER)

def test_factory_hides_exact_bootstrap_user_before_first_reboot() -> None:
    common = COMMON.read_text(encoding="utf-8")
    factory = (ROOT / "client/bootstrap/clientflow-factory-prepare").read_text(encoding="utf-8")
    handoff = common[common.index("def validate_factory_handoff") : common.index("def load_usb_state")]
    assert "prepare_factory_bootstrap_user_hidden(operator)" in factory
    assert "validate_factory_bootstrap_user_hidden(operator_user)" in handoff
    assert handoff.index("validate_factory_bootstrap_user_hidden(operator_user)") < handoff.index(
        "write_factory_state(client_name=client_name, operator_user=operator_user, handoff_ready=True)"
    )


def test_factory_bootstrap_user_accountsservice_record_is_hidden_and_preserves_other_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_common()
    username = "ubuntu-bootstrap"
    accounts_root = tmp_path / "AccountsService/users"
    accounts_root.mkdir(parents=True)
    record = accounts_root / username
    record.write_text(
        "[User]\nLanguage=da_DK.UTF-8\nSystemAccount=false\nIcon=/tmp/example.png\n",
        encoding="utf-8",
    )
    record.chmod(0o644)

    monkeypatch.setattr(module, "ACCOUNTS_SERVICE_ROOT", accounts_root)
    monkeypatch.setattr(module, "require_root", lambda: None)
    monkeypatch.setattr(module, "validate_local_user", lambda candidate: candidate)
    monkeypatch.setattr(module.os, "fchown", lambda *_args, **_kwargs: None)
    _pretend_accountsservice_record_is_root_owned(module, monkeypatch, record)

    module.prepare_factory_bootstrap_user_hidden(username)

    content = record.read_text(encoding="utf-8")
    assert "SystemAccount=true" in content
    assert "SystemAccount=false" not in content
    assert "Language=da_DK.UTF-8" in content
    assert "Icon=/tmp/example.png" in content
    module.validate_factory_bootstrap_user_hidden(username)


def test_factory_bootstrap_user_validation_fails_closed_if_still_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_common()
    username = "ubuntu-bootstrap"
    accounts_root = tmp_path / "AccountsService/users"
    accounts_root.mkdir(parents=True)
    record = accounts_root / username
    record.write_text("[User]\nSystemAccount=false\n", encoding="utf-8")
    record.chmod(0o644)

    monkeypatch.setattr(module, "ACCOUNTS_SERVICE_ROOT", accounts_root)
    monkeypatch.setattr(module, "validate_local_user", lambda candidate: candidate)
    _pretend_accountsservice_record_is_root_owned(module, monkeypatch, record)

    with pytest.raises(module.BootstrapError, match="stadig synlig"):
        module.validate_factory_bootstrap_user_hidden(username)


def test_factory_bootstrap_user_hiding_refuses_canonical_clientflow_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_common()
    monkeypatch.setattr(module, "require_root", lambda: None)
    monkeypatch.setattr(module, "validate_local_user", lambda candidate: candidate)
    for username in (module.KIOSK_USER, module.ADMIN_USER):
        with pytest.raises(module.BootstrapError, match="canonical ClientFlow-bruger"):
            module.prepare_factory_bootstrap_user_hidden(username)

