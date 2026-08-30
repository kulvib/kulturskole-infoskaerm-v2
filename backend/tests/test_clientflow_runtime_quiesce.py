from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release import transaction  # noqa: E402
from clientflow_release.transaction import Layout, TransactionError  # noqa: E402


def _copy_units(layout: Layout) -> None:
    layout.unit_root.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "client/systemd").glob("clientflow*"):
        if source.is_file():
            shutil.copy2(source, layout.unit_root / source.name)


def test_runtime_quiesce_inventory_excludes_only_stable_update_control_plane(tmp_path):
    layout = Layout(tmp_path / "root")
    _copy_units(layout)

    names = set(transaction._runtime_unit_names(layout))

    assert "clientflow.target" in names
    assert "clientflow-system-broker.service" in names
    assert "clientflow-display-power-broker.service" in names
    assert "clientflow-standard-terminal-broker.service" in names
    assert "clientflow-remote-desktop-capture.service" in names
    assert "clientflow-updater.service" not in names
    assert "clientflow-updater.timer" not in names
    assert "clientflow-update-controller.service" not in names


def test_runtime_quiesce_stops_every_runtime_unit_and_verifies_inactive(monkeypatch):
    layout = Layout()
    paths = [
        Path("/etc/systemd/system/clientflow.target"),
        Path("/etc/systemd/system/clientflow-status-agent.service"),
        Path("/etc/systemd/system/clientflow-system-broker.service"),
        Path("/etc/systemd/system/clientflow-system-broker.socket"),
        Path("/etc/systemd/system/clientflow-updater.service"),
        Path("/etc/systemd/system/clientflow-updater.timer"),
        Path("/etc/systemd/system/clientflow-update-controller.service"),
    ]
    monkeypatch.setattr(transaction, "_managed_unit_paths", lambda _layout: paths)
    calls: list[list[str]] = []

    def fake_run(command, *, timeout=180, check=True):
        calls.append(list(command))
        if command[1] == "show":
            return subprocess.CompletedProcess(command, 0, stdout="inactive\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(transaction, "_run", fake_run)
    transaction._quiesce_runtime(layout)

    stop = calls[0]
    assert stop[:2] == ["/usr/bin/systemctl", "stop"]
    stopped = set(stop[2:])
    assert stopped == {
        "clientflow.target",
        "clientflow-status-agent.service",
        "clientflow-system-broker.service",
        "clientflow-system-broker.socket",
    }
    assert all(unit not in stopped for unit in transaction._UPDATE_CONTROL_PLANE_UNITS)
    shown = {call[2] for call in calls[1:] if call[1] == "show"}
    assert shown == stopped


def test_runtime_quiesce_fails_closed_if_any_unit_remains_active(monkeypatch):
    layout = Layout()
    paths = [
        Path("/etc/systemd/system/clientflow.target"),
        Path("/etc/systemd/system/clientflow-status-agent.service"),
    ]
    monkeypatch.setattr(transaction, "_managed_unit_paths", lambda _layout: paths)

    def fake_run(command, *, timeout=180, check=True):
        if command[1] == "show":
            state = "active" if command[2] == "clientflow-status-agent.service" else "inactive"
            return subprocess.CompletedProcess(command, 0, stdout=state + "\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(transaction, "_run", fake_run)
    with pytest.raises(TransactionError, match="kunne ikke quiesces"):
        transaction._quiesce_runtime(layout)


def test_activation_quiesces_before_definition_and_active_symlink_swap(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.11-seq-1212"
    approval = f"{release_id}/test-approval"
    layout = Layout(tmp_path / "root")
    release_root = layout.releases / release_id
    release_root.mkdir(parents=True)
    (release_root / "release-manifest.json").write_text(
        '{"activation":{"health_timeout_seconds":120}}\n', encoding="utf-8"
    )
    state = {
        "schema_version": transaction.STATE_SCHEMA,
        "installed": {release_id: {}},
        "active_release_id": None,
        "previous_release_id": None,
        "staged_release_id": release_id,
        "history": [],
    }
    order: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: None)
    monkeypatch.setattr(transaction, "_disable_target", lambda _layout: order.append("disable"))
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: order.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: order.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: order.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: order.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: order.append("start"))
    monkeypatch.setattr(transaction, "_health_check", lambda *_args, **_kwargs: order.append("health"))
    monkeypatch.setattr(transaction, "save_state", lambda *_args, **_kwargs: None)

    result = transaction._activate_release(layout, state, release_id, approval)

    assert result["status"] == "active"
    assert order == ["disable", "quiesce", "definitions", "switch", "prepare", "start", "health"]


def test_failed_first_activation_restores_pending_definitions_and_updater_plane(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.11-seq-1212"
    approval = f"{release_id}/test-approval"
    layout = Layout(tmp_path / "root")
    release_root = layout.releases / release_id
    release_root.mkdir(parents=True)
    (release_root / "release-manifest.json").write_text(
        '{"activation":{"health_timeout_seconds":120}}\n', encoding="utf-8"
    )
    state = {
        "schema_version": transaction.STATE_SCHEMA,
        "installed": {release_id: {}},
        "active_release_id": None,
        "previous_release_id": None,
        "staged_release_id": release_id,
        "history": [],
    }
    order: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: None)
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: order.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: order.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: order.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: order.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: order.append("start"))
    monkeypatch.setattr(transaction, "_health_check", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(transaction, "_disable_target", lambda _layout: order.append("disable"))
    monkeypatch.setattr(transaction, "_enable_stable_updater_timer", lambda _layout: order.append("updater"))
    monkeypatch.setattr(
        transaction,
        "_remove_definitions",
        lambda _layout: (_ for _ in ()).throw(AssertionError("pending rollback må ikke fjerne managed definitions")),
    )
    monkeypatch.setattr(transaction, "save_state", lambda *_args, **_kwargs: None)

    with pytest.raises(TransactionError, match="tidligere release blev automatisk gendannet"):
        transaction._activate_release(layout, state, release_id, approval)

    assert order == [
        "disable",
        "quiesce",
        "definitions",
        "switch",
        "prepare",
        "start",
        "quiesce",
        "definitions",
        "prepare",
        "disable",
        "updater",
    ]


def test_activation_disable_failure_prevents_any_runtime_mutation(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.11-seq-1212"
    approval = f"{release_id}/test-approval"
    previous = "clientflow-1.3.10-seq-1211"
    layout = Layout(tmp_path / "root")
    release_root = layout.releases / release_id
    release_root.mkdir(parents=True)
    (release_root / "release-manifest.json").write_text(
        '{"activation":{"health_timeout_seconds":120}}\n', encoding="utf-8"
    )
    state = {
        "schema_version": transaction.STATE_SCHEMA,
        "installed": {release_id: {}},
        "active_release_id": previous,
        "previous_release_id": None,
        "staged_release_id": release_id,
        "activation_intent": None,
        "history": [],
    }
    mutations: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: previous)
    monkeypatch.setattr(transaction, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        transaction,
        "_disable_target",
        lambda _layout: (_ for _ in ()).throw(TransactionError("disable failed")),
    )
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: mutations.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: mutations.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: mutations.append("switch"))

    with pytest.raises(TransactionError, match="disable failed"):
        transaction._activate_release(layout, state, release_id, approval)

    assert mutations == []
    assert state["activation_intent"]["release_id"] == release_id
    assert state["activation_intent"]["previous_release_id"] == previous
