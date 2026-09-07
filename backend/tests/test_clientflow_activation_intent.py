from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release import transaction  # noqa: E402
from clientflow_release.transaction import Layout, TransactionError  # noqa: E402


def _state(release_id: str, previous: str | None) -> dict:
    return {
        "schema_version": transaction.STATE_SCHEMA,
        "highest_release_sequence": 1212,
        "active_release_id": previous,
        "previous_release_id": None,
        "staged_release_id": release_id,
        "activation_intent": None,
        "installed": {release_id: {}},
        "history": [],
    }


def _release(layout: Layout, release_id: str) -> None:
    root = layout.releases / release_id
    root.mkdir(parents=True)
    (root / "release-manifest.json").write_text(
        '{"activation":{"health_timeout_seconds":120}}\n', encoding="utf-8"
    )


def test_activation_intent_is_durable_before_first_runtime_mutation(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.11-seq-1212"
    approval = f"{release_id}/approval"
    previous = "clientflow-1.3.10-seq-1211"
    layout = Layout(tmp_path / "root")
    _release(layout, release_id)
    state = _state(release_id, previous)
    order: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: previous)
    monkeypatch.setattr(transaction, "save_state", lambda _layout, _state: order.append("save"))
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: order.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: order.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: order.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: order.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: order.append("start"))
    monkeypatch.setattr(transaction, "_health_check", lambda *_args, **_kwargs: order.append("health"))

    transaction._activate_release(layout, state, release_id, approval)

    assert order[0:2] == ["save", "quiesce"]
    assert state["activation_intent"] is None
    assert state["active_release_id"] == release_id
    assert any(event["event"] == "activation_intent_committed" for event in state["history"])
    assert any(event["event"] == "activated" for event in state["history"])


def test_exact_activation_intent_resumes_when_symlink_already_points_to_target(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.11-seq-1212"
    approval = f"{release_id}/approval"
    previous = "clientflow-1.3.10-seq-1211"
    layout = Layout(tmp_path / "root")
    _release(layout, release_id)
    state = _state(release_id, previous)
    state["activation_intent"] = {
        "release_id": release_id,
        "previous_release_id": previous,
        "release_approval_reference": approval,
        "started_at": "2026-08-26T10:00:00Z",
    }
    calls: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: release_id)
    monkeypatch.setattr(transaction, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: calls.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: calls.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: calls.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: calls.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: calls.append("start"))
    monkeypatch.setattr(transaction, "_health_check", lambda *_args, **_kwargs: calls.append("health"))

    result = transaction._activate_release(layout, state, release_id, approval)

    assert result["status"] == "active"
    assert result["previous_release_id"] == previous
    assert calls == ["quiesce", "definitions", "switch", "prepare", "start", "health"]
    assert state["activation_intent"] is None
    assert state["active_release_id"] == release_id


def test_target_boot_enablement_occurs_only_after_durable_health_boundary(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.12-seq-1213"
    approval = f"{release_id}/approval"
    layout = Layout(tmp_path / "root")
    _release(layout, release_id)
    state = _state(release_id, None)
    order: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: None)

    def record_save(_layout, current_state):
        intent = current_state.get("activation_intent")
        if isinstance(intent, dict) and intent.get("health_verified_at"):
            order.append("save-health-verified")
        else:
            order.append("save")

    monkeypatch.setattr(transaction, "save_state", record_save)
    monkeypatch.setattr(transaction, "_disable_target", lambda _layout: order.append("disable-target"))
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: order.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: order.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: order.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: order.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: order.append("start-transient"))
    monkeypatch.setattr(transaction, "_health_check", lambda *_args, **_kwargs: order.append("health"))
    monkeypatch.setattr(transaction, "_enable_target", lambda _layout: order.append("enable-boot"))
    monkeypatch.setattr(transaction, "_enable_stable_updater_timer", lambda _layout: order.append("updater"))

    transaction._activate_release(layout, state, release_id, approval)

    assert order.index("health") < order.index("save-health-verified") < order.index("enable-boot")
    assert order.index("enable-boot") < order.index("updater")
    assert state["activation_intent"] is None
    assert state["active_release_id"] == release_id
    assert any(event["event"] == "activation_health_verified" for event in state["history"])


def test_abrupt_loss_before_health_commit_never_boot_enables_target(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.12-seq-1213"
    approval = f"{release_id}/approval"
    layout = Layout(tmp_path / "root")
    _release(layout, release_id)
    state = _state(release_id, None)
    calls: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: None)
    monkeypatch.setattr(transaction, "save_state", lambda *_args, **_kwargs: calls.append("save"))
    monkeypatch.setattr(transaction, "_disable_target", lambda _layout: calls.append("disable-target"))
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: calls.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: calls.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: calls.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: calls.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: calls.append("start-transient"))
    monkeypatch.setattr(transaction, "_enable_target", lambda _layout: calls.append("enable-boot"))

    def abrupt_loss(*_args, **_kwargs):
        calls.append("health-entered")
        raise SystemExit("synthetic abrupt power/process loss")

    monkeypatch.setattr(transaction, "_health_check", abrupt_loss)

    with pytest.raises(SystemExit, match="abrupt"):
        transaction._activate_release(layout, state, release_id, approval)

    assert "start-transient" in calls
    assert "health-entered" in calls
    assert "enable-boot" not in calls
    assert state["activation_intent"] is not None
    assert state["active_release_id"] is None


def test_start_and_boot_enable_are_separate_systemd_operations(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        transaction,
        "_run",
        lambda command, **_kwargs: calls.append(list(command)),
    )

    transaction._start_target(Layout())
    transaction._enable_target(Layout())

    assert calls == [
        ["/usr/bin/systemctl", "start", "clientflow.target"],
        ["/usr/bin/systemctl", "enable", "clientflow.target"],
    ]


def test_first_activation_enables_updater_only_after_runtime_health(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.12-seq-1213"
    approval = f"{release_id}/approval"
    layout = Layout(tmp_path / "root")
    _release(layout, release_id)
    state = _state(release_id, None)
    order: list[str] = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: None)
    monkeypatch.setattr(transaction, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_disable_target", lambda _layout: order.append("disable-target"))
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: order.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: order.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: order.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: order.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: order.append("start"))
    monkeypatch.setattr(transaction, "_health_check", lambda *_args, **_kwargs: order.append("health"))
    monkeypatch.setattr(transaction, "_enable_target", lambda _layout: order.append("enable-target"))
    monkeypatch.setattr(transaction, "_enable_stable_updater_timer", lambda _layout: order.append("updater"))

    result = transaction._activate_release(layout, state, release_id, approval)

    assert result["status"] == "active"
    assert order == [
        "disable-target",
        "quiesce",
        "definitions",
        "switch",
        "prepare",
        "start",
        "health",
        "enable-target",
        "updater",
    ]


def test_activation_intent_rejects_different_release_or_approval(tmp_path):
    layout = Layout(tmp_path / "root")
    release_id = "clientflow-1.3.11-seq-1212"
    previous = "clientflow-1.3.10-seq-1211"
    state = _state(release_id, previous)
    state["activation_intent"] = {
        "release_id": release_id,
        "previous_release_id": previous,
        "release_approval_reference": f"{release_id}/approval-a",
        "started_at": "2026-08-26T10:00:00Z",
    }

    with pytest.raises(TransactionError, match="anden activation"):
        transaction._activation_intent(
            layout,
            state,
            release_id=release_id,
            release_approval_reference=f"{release_id}/approval-b",
            current_release_id=previous,
        )


def test_stable_updater_host_materializes_but_disables_pending_timer(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.12-seq-1213"
    layout = Layout(tmp_path / "root")
    source = layout.releases / release_id / "release/updater/clientflow-updater.pyz"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"stable-updater-test")
    source.chmod(0o555)
    transaction.save_state(
        layout,
        {
            "schema_version": transaction.STATE_SCHEMA,
            "highest_release_sequence": 1213,
            "active_release_id": None,
            "previous_release_id": None,
            "staged_release_id": release_id,
            "activation_intent": None,
            "installed": {release_id: {}},
            "history": [],
        },
    )
    timer_calls: list[str] = []
    monkeypatch.setattr(
        transaction,
        "_disable_stable_updater_timer",
        lambda _layout: timer_calls.append("disabled"),
    )
    monkeypatch.setattr(
        transaction,
        "_enable_stable_updater_timer",
        lambda _layout: pytest.fail("pending updater host must not enable timer"),
    )

    result = transaction.install_stable_updater_host(release_id, layout=layout)

    assert result["status"] == "stable_updater_host_installed"
    assert layout.stable_updater_pyz.read_bytes() == b"stable-updater-test"
    assert timer_calls == ["disabled"]


def test_failed_first_activation_restores_pending_definitions_and_disables_updater_plane(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.12-seq-1213"
    approval = f"{release_id}/approval"
    layout = Layout(tmp_path / "root")
    release_root = layout.releases / release_id
    unit_source = release_root / "client-runtime/systemd"
    unit_source.mkdir(parents=True)
    (unit_source / "clientflow.target").write_text("[Unit]\nDescription=target\n", encoding="utf-8")
    (unit_source / "clientflow-updater.service").write_text("[Service]\nType=oneshot\n", encoding="utf-8")
    (unit_source / "clientflow-updater.timer").write_text("[Timer]\nOnActiveSec=1min\n", encoding="utf-8")
    sysusers = release_root / "client-runtime/sysusers.d/clientflow.conf"
    sysusers.parent.mkdir(parents=True)
    sysusers.write_text("g clientflow-updater -\n", encoding="utf-8")
    tmpfiles = release_root / "client-runtime/tmpfiles.d/clientflow.conf"
    tmpfiles.parent.mkdir(parents=True)
    tmpfiles.write_text("d /var/lib/clientflow 0755 root root -\n", encoding="utf-8")

    timer_calls: list[str] = []
    monkeypatch.setattr(
        transaction,
        "_disable_stable_updater_timer",
        lambda _layout: timer_calls.append("disabled"),
    )
    monkeypatch.setattr(
        transaction,
        "_enable_stable_updater_timer",
        lambda _layout: pytest.fail("pending rollback must not enable updater timer"),
    )

    layout.install_root.mkdir(parents=True, exist_ok=True)
    transaction.atomic_symlink(f"releases/{release_id}", layout.active)
    transaction._restore_pending_first_activation(layout, release_root)

    assert timer_calls == ["disabled"]
    assert not (layout.active.exists() or layout.active.is_symlink())
    assert (layout.unit_root / "clientflow.target").is_file()
    assert (layout.unit_root / "clientflow-updater.service").is_file()
    assert (layout.unit_root / "clientflow-updater.timer").is_file()


def test_first_activation_failure_uses_pending_restore_not_definition_removal(tmp_path, monkeypatch):
    release_id = "clientflow-1.3.12-seq-1213"
    approval = f"{release_id}/approval"
    layout = Layout(tmp_path / "root")
    _release(layout, release_id)
    state = _state(release_id, None)
    calls = []

    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: None)
    monkeypatch.setattr(transaction, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_disable_target", lambda _layout: calls.append("disable"))
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda _layout: calls.append("quiesce"))
    monkeypatch.setattr(transaction, "_apply_definitions", lambda *_args, **_kwargs: calls.append("definitions"))
    monkeypatch.setattr(transaction, "_switch_active", lambda *_args, **_kwargs: calls.append("switch"))
    monkeypatch.setattr(transaction, "_systemd_prepare", lambda _layout: calls.append("prepare"))
    monkeypatch.setattr(transaction, "_start_target", lambda _layout: (_ for _ in ()).throw(RuntimeError("start failed")))
    monkeypatch.setattr(transaction, "_restore_pending_first_activation", lambda *_args, **_kwargs: calls.append("restore-pending"))
    monkeypatch.setattr(transaction, "_remove_definitions", lambda *_args, **_kwargs: pytest.fail("must not remove pending updater definitions"))

    with pytest.raises(TransactionError, match="automatisk gendannet"):
        transaction._activate_release(layout, state, release_id, approval)

    assert "restore-pending" in calls
    assert state["active_release_id"] is None
    assert state["activation_intent"] is None
    assert any(event["event"] == "automatic_rollback_completed" for event in state["history"])

def test_stage_bundle_rejects_new_release_while_activation_intent_is_unresolved_before_staging(
    tmp_path, monkeypatch
):
    layout = Layout(tmp_path / "root")
    layout.state_root.mkdir(parents=True, exist_ok=True)
    current_release_id = "clientflow-1.3.15-seq-1216"
    target_release_id = "clientflow-1.3.16-seq-1217"
    transaction.save_state(
        layout,
        {
            "schema_version": transaction.STATE_SCHEMA,
            "highest_release_sequence": 1216,
            "active_release_id": None,
            "previous_release_id": None,
            "staged_release_id": current_release_id,
            "activation_intent": {
                "release_id": current_release_id,
                "previous_release_id": None,
                "release_approval_reference": f"{current_release_id}/approval",
                "started_at": "2026-09-03T20:00:00Z",
                "health_verified_at": "2026-09-03T20:01:00Z",
            },
            "installed": {},
            "history": [],
        },
    )

    manifest = {
        "version": "1.3.16",
        "release_id": target_release_id,
        "release_sequence": 1217,
        "release_approval": {
            "reference": f"{target_release_id}/approval",
            "candidate_sha256": "a" * 64,
        },
        "source": {"commit": "b" * 40},
    }

    class _Handle:
        def close(self):
            pass

    monkeypatch.setattr(
        transaction,
        "open_verified_bundle",
        lambda *_args, **_kwargs: (
            manifest,
            object(),
            1234,
            "c" * 64,
            _Handle(),
        ),
    )
    monkeypatch.setattr(
        transaction.tempfile,
        "mkdtemp",
        lambda *_args, **_kwargs: pytest.fail(
            "filesystem staging må ikke begynde under unresolved activation_intent"
        ),
    )

    with pytest.raises(TransactionError, match="activation transaction er uafsluttet"):
        transaction.stage_bundle(
            tmp_path / "unused-bundle.tar",
            release_id=target_release_id,
            expected_bundle_sha256="c" * 64,
            install_mode="in_place_update",
            layout=layout,
        )

