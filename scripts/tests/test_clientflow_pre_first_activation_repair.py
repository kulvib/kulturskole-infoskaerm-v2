from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import cli  # noqa: E402
from clientflow_release.filesystem import atomic_write_json  # noqa: E402
from clientflow_release.transaction import Layout, save_state  # noqa: E402


BASELINE_ID = "clientflow-1.3.17-seq-1218"
TARGET_ID = "clientflow-1.3.18-seq-1219"
BASELINE_BINDING = {
    "release_id": BASELINE_ID,
    "version": "1.3.17",
    "release_sequence": 1218,
    "bundle_sha256": "a" * 64,
    "bundle_size": 12345,
    "release_approval_reference": "approval/1218",
    "release_candidate_sha256": "b" * 64,
    "source_commit": "c" * 40,
}


def _seed_pending(layout: Layout) -> None:
    state = {
        "schema_version": 1,
        "highest_release_sequence": 1218,
        "active_release_id": None,
        "previous_release_id": None,
        "staged_release_id": BASELINE_ID,
        "activation_intent": None,
        "installed": {
            BASELINE_ID: {
                "version": "1.3.17",
                "release_sequence": 1218,
                "bundle_sha256": "a" * 64,
                "bundle_size": 12345,
                "release_approval_reference": "approval/1218",
                "release_candidate_sha256": "b" * 64,
                "source_commit": "c" * 40,
                "manifest_sha256": "d" * 64,
            }
        },
        "history": [],
    }
    save_state(layout, state)
    atomic_write_json(
        layout.path("/var/lib/clientflow/release/install-state.json"),
        {
            "schema_version": cli.INSTALL_STATE_SCHEMA,
            "status": "pending_manual_activation",
            "fresh_install_binding": dict(BASELINE_BINDING),
            "bootstrap_user": "ubuntu-bootstrap",
        },
        mode=0o600,
    )


def test_repair_baseline_requires_exact_original_pending_binding(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    _seed_pending(layout)

    result = cli._pre_first_activation_repair_baseline(layout)
    assert result["binding"]["release_id"] == BASELINE_ID

    state = json.loads(layout.state_file.read_text())
    state["staged_release_id"] = TARGET_ID
    atomic_write_json(layout.state_file, state, mode=0o600)
    with pytest.raises(RuntimeError, match="oprindelige fresh-install claim-binding"):
        cli._pre_first_activation_repair_baseline(layout)


def test_repair_baseline_rejects_any_active_release(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    _seed_pending(layout)
    state = json.loads(layout.state_file.read_text())
    state["active_release_id"] = BASELINE_ID
    atomic_write_json(layout.state_file, state, mode=0o600)
    with pytest.raises(RuntimeError, match="uden aktiv release"):
        cli._pre_first_activation_repair_baseline(layout)


def test_repair_orchestrator_requires_strictly_newer_backend_snapshot(monkeypatch, tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    _seed_pending(layout)
    monkeypatch.setattr(cli, "_repair_updater_config", lambda _layout: SimpleNamespace(state_root=tmp_path / "updater"))

    class FakeUpdater:
        def __init__(self, _config):
            self.state = SimpleNamespace(
                snapshot=SimpleNamespace(
                    deployment_id="11111111-1111-1111-1111-111111111111",
                    target_release_id=BASELINE_ID,
                    target_release_sequence=1218,
                )
            )
        def run_once(self):
            return {"status": "verified"}

    monkeypatch.setattr(cli, "StableUpdaterClient", FakeUpdater)
    with pytest.raises(RuntimeError, match="ikke strengt nyere"):
        cli._run_pre_first_activation_repair(layout)


def test_repair_orchestrator_runs_existing_updater_controller_and_finalizes(monkeypatch, tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    _seed_pending(layout)
    config = SimpleNamespace(state_root=tmp_path / "updater")
    monkeypatch.setattr(cli, "_repair_updater_config", lambda _layout: config)

    snapshot = SimpleNamespace(
        deployment_id="11111111-1111-1111-1111-111111111111",
        target_release_id=TARGET_ID,
        target_release_sequence=1219,
    )

    class FakeUpdater:
        def __init__(self, _config):
            self.state = SimpleNamespace(snapshot=snapshot)
        def run_once(self):
            return {"status": "verified"}

    observed = {}

    class FakeController:
        def __init__(self, _config, **kwargs):
            observed.update(kwargs)
        def run_once(self):
            return {"status": "succeeded", "deployment_id": snapshot.deployment_id}

    monkeypatch.setattr(cli, "StableUpdaterClient", FakeUpdater)
    monkeypatch.setattr(cli, "UpdateController", FakeController)
    monkeypatch.setattr(cli, "_finalize_install_state_after_activation", lambda _layout, rid: observed.setdefault("finalized", rid))

    result = cli._run_pre_first_activation_repair(layout)
    assert result == {
        "status": "repaired_and_activated",
        "from_release_id": BASELINE_ID,
        "release_id": TARGET_ID,
        "deployment_id": snapshot.deployment_id,
    }
    assert observed["layout"] == layout
    assert observed["source_state_root"] == config.state_root
    assert observed["finalized"] == TARGET_ID
    assert observed["activate_func"] is cli._repair_activate


def test_repaired_first_activation_finalizes_install_state_without_rewriting_claim_binding(monkeypatch, tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    _seed_pending(layout)
    monkeypatch.setattr(
        cli,
        "status",
        lambda _layout: {
            "active_release_id": TARGET_ID,
            "active_symlink_release_id": TARGET_ID,
            "previous_release_id": None,
            "installed": {TARGET_ID: {"release_sequence": 1219}},
        },
    )

    cli._finalize_install_state_after_activation(layout, TARGET_ID)

    final = json.loads(layout.path("/var/lib/clientflow/release/install-state.json").read_text())
    assert final["status"] == "activated"
    assert final["activated_release_id"] == TARGET_ID
    assert final["first_activation_repair_from_release_id"] == BASELINE_ID
    assert final["fresh_install_binding"] == BASELINE_BINDING


def test_repair_activate_preserves_first_activation_backend_approval_gate(monkeypatch, tmp_path: Path) -> None:
    observed = {}

    def fake_activate(release_id, **kwargs):
        observed["release_id"] = release_id
        observed.update(kwargs)
        return {"status": "active", "release_id": release_id}

    monkeypatch.setattr(cli, "activate_release", fake_activate)
    layout = Layout(tmp_path)
    result = cli._repair_activate(
        TARGET_ID,
        expected_release_approval_reference="approval/1219",
        layout=layout,
    )

    assert result["status"] == "active"
    assert observed["first_activation_authorizer"] is cli._prove_backend_client_approved
    assert observed["layout"] == layout


def test_stable_updater_pyz_exposes_explicit_root_repair_dispatch(monkeypatch, capsys):
    from clientflow_release import repair_dispatch, updater_entrypoint

    observed: dict[str, bool] = {}
    monkeypatch.setattr(
        repair_dispatch,
        "exec_pre_first_activation_repair",
        lambda: observed.setdefault("dispatched", True),
    )

    # Production os.execv does not return. The test double returns so the
    # process-boundary branch can prove it selected the dedicated dispatcher.
    assert updater_entrypoint.main(["repair-first-activation"]) == 0
    assert observed == {"dispatched": True}
    assert capsys.readouterr().err == ""


def test_stable_updater_pyz_rejects_unknown_operator_mode(capsys):
    from clientflow_release import updater_entrypoint

    assert updater_entrypoint.main(["anything-else"]) == 2
    assert "ukendt operation" in capsys.readouterr().err


def test_stable_updater_repair_dispatch_resolves_exact_original_staged_wrapper(tmp_path: Path) -> None:
    from clientflow_release.repair_dispatch import resolve_repair_transaction

    layout = Layout(tmp_path)
    _seed_pending(layout)
    wrapper = (
        layout.releases
        / BASELINE_ID
        / "release/bin/clientflow-release-transaction"
    )
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("# canonical staged transaction\n", encoding="utf-8")
    wrapper.chmod(0o555)

    assert resolve_repair_transaction(root=tmp_path) == wrapper


def test_transaction_main_exposes_pre_first_activation_repair(monkeypatch, tmp_path: Path, capsys) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr(cli, "_require_root", lambda layout: observed.setdefault("root", layout.root))
    monkeypatch.setattr(
        cli,
        "_run_pre_first_activation_repair",
        lambda layout: {"status": "repaired", "root": str(layout.root)},
    )
    # transaction_main is intentionally rooted at / in production; avoid host
    # access by replacing both root guard and repair implementation.
    assert cli.transaction_main(["repair-first-activation"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "repaired"
    assert observed["root"] == Path("/")
