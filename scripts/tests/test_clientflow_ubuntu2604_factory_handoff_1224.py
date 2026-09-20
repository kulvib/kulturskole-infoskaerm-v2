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
