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
