from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release.runtime_prepare import CLIENTFLOW_ENTRYPOINTS  # noqa: E402
from clientflow_release.systemd_contract import SystemdContractError, validate_release_systemd_contract  # noqa: E402


def _release_tree(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    shutil.copytree(ROOT / "client/systemd", root / "client-runtime/systemd")
    shutil.copytree(ROOT / "client/sysusers.d", root / "client-runtime/sysusers.d")
    shutil.copytree(ROOT / "client/libexec", root / "client-runtime/libexec")
    (root / "runtime/bin").mkdir(parents=True)
    for name in CLIENTFLOW_ENTRYPOINTS:
        path = root / "runtime/bin" / name
        path.write_text("#!/opt/clientflow/active/runtime/bin/python\n", encoding="utf-8")
        path.chmod(0o755)
    # The deterministic payload builder promotes only direct-exec helpers.
    for name in ("display-power", "update-os"):
        (root / "client-runtime/libexec" / name).chmod(0o755)
    (root / "release/updater").mkdir(parents=True)
    (root / "release/updater/clientflow-updater.pyz").write_text("updater\n", encoding="utf-8")
    return root


def test_release_systemd_contract_accepts_complete_canonical_tree(tmp_path):
    summary = validate_release_systemd_contract(_release_tree(tmp_path))
    assert summary["unit_count"] == len(list((ROOT / "client/systemd").iterdir()))
    assert "/opt/clientflow/active/runtime/bin/clientflow-calendar" in summary["exec_paths"]
    assert "/usr/bin/python3" in summary["exec_paths"]


def test_release_systemd_contract_rejects_missing_runtime_entrypoint(tmp_path):
    root = _release_tree(tmp_path)
    (root / "runtime/bin/clientflow-calendar").unlink()
    with pytest.raises(SystemdContractError, match="clientflow-calendar"):
        validate_release_systemd_contract(root)


def test_release_systemd_contract_rejects_non_executable_runtime_entrypoint(tmp_path):
    root = _release_tree(tmp_path)
    (root / "runtime/bin/clientflow-status-agent").chmod(0o644)
    with pytest.raises(SystemdContractError, match="ikke executable"):
        validate_release_systemd_contract(root)


def test_release_systemd_contract_rejects_missing_shell_owned_payload_helper(tmp_path):
    root = _release_tree(tmp_path)
    (root / "client-runtime/libexec/update-controller").unlink()
    with pytest.raises(SystemdContractError, match="update-controller"):
        validate_release_systemd_contract(root)


def test_release_systemd_contract_rejects_unknown_clientflow_unit_reference(tmp_path):
    root = _release_tree(tmp_path)
    target = root / "client-runtime/systemd/clientflow.target"
    target.write_text(target.read_text(encoding="utf-8") + "Wants=clientflow-does-not-exist.service\n", encoding="utf-8")
    with pytest.raises(SystemdContractError, match="clientflow-does-not-exist.service"):
        validate_release_systemd_contract(root)


def test_release_systemd_contract_rejects_unknown_service_account(tmp_path):
    root = _release_tree(tmp_path)
    unit = root / "client-runtime/systemd/clientflow-calendar.service"
    unit.write_text(unit.read_text(encoding="utf-8").replace("User=clientflow-display-agent", "User=legacy-static-user"), encoding="utf-8")
    with pytest.raises(SystemdContractError, match="legacy-static-user"):
        validate_release_systemd_contract(root)


def test_runtime_console_script_inventory_is_exact_not_subset_only():
    import tomllib

    project = tomllib.loads((ROOT / "client/runtime/pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert set(project["scripts"]) == set(CLIENTFLOW_ENTRYPOINTS)


def test_release_workflow_requires_target_host_candidate_gate_before_handoff():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release-build.yml").read_text(encoding="utf-8")
    assert "client-host-ubuntu-2604:" in ci
    assert "runs-on: ubuntu-26.04" in ci
    assert "verify_clientflow_ubuntu2604_host.py" in ci
    assert "candidate-runtime:" in release
    assert "verify_clientflow_release_candidate_runtime.py" in release
    assert "needs: [preflight, build, candidate-runtime]" in release


def test_platform_target_lock_is_exact_ubuntu_2604_amd64():
    release_input = json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "client/release/runtime-platform-inputs.lock.json").read_text(encoding="utf-8"))
    assert release_input["minimum_ubuntu_lts"] == "26.04"
    assert release_input["architecture"] == "amd64"
    assert lock["host_requirements"]["os_id"] == "ubuntu"
    assert lock["host_requirements"]["version_id"] == "26.04"
    assert lock["host_requirements"]["architecture"] == "amd64"


def test_release_systemd_contract_rejects_obsolete_parallel_activation_marker(tmp_path):
    root = _release_tree(tmp_path)
    unit = root / "client-runtime/systemd/clientflow-browser-guard.service"
    text = unit.read_text(encoding="utf-8")
    text = text.replace(
        "Requires=clientflow-display-runtime.service\n",
        "Requires=clientflow-display-runtime.service\nConditionPathExists=/etc/clientflow/activated\n",
        1,
    )
    unit.write_text(text, encoding="utf-8")
    with pytest.raises(SystemdContractError, match="parallel activation marker"):
        validate_release_systemd_contract(root)


@pytest.mark.parametrize(
    "unit_name",
    ["clientflow-platform-prepare.service", "clientflow-system-broker.service"],
)
def test_release_systemd_contract_rejects_nnp_on_apt_privilege_drop_paths(tmp_path, unit_name):
    root = _release_tree(tmp_path)
    unit = root / "client-runtime/systemd" / unit_name
    text = unit.read_text(encoding="utf-8")
    assert "NoNewPrivileges=no" in text
    unit.write_text(text.replace("NoNewPrivileges=no", "NoNewPrivileges=yes", 1), encoding="utf-8")
    with pytest.raises(SystemdContractError, match="NoNewPrivileges=yes"):
        validate_release_systemd_contract(root)


@pytest.mark.parametrize(
    "unit_name",
    ["clientflow-status-agent.service", "clientflow-display-runtime.service"],
)
def test_release_systemd_contract_rejects_missing_netlink_for_ip_consumers(tmp_path, unit_name):
    root = _release_tree(tmp_path)
    unit = root / "client-runtime/systemd" / unit_name
    text = unit.read_text(encoding="utf-8")
    assert "AF_NETLINK" in text
    unit.write_text(text.replace(" AF_NETLINK", "", 1), encoding="utf-8")
    with pytest.raises(SystemdContractError, match="AF_NETLINK"):
        validate_release_systemd_contract(root)


def test_release_systemd_contract_preserves_frozen_livestream_privilege_drop_capabilities(tmp_path):
    root = _release_tree(tmp_path)
    unit = root / "client-runtime/systemd/clientflow-livestream-producer.service"
    text = unit.read_text(encoding="utf-8")
    assert "AmbientCapabilities=CAP_KILL CAP_SETGID CAP_SETUID" in text
    unit.write_text(
        text.replace(
            "AmbientCapabilities=CAP_KILL CAP_SETGID CAP_SETUID",
            "AmbientCapabilities=CAP_KILL",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemdContractError, match="Frozen Livestream privilege-drop"):
        validate_release_systemd_contract(root)
