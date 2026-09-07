from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import uuid

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = REPO_ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release.transaction import Layout, TransactionError  # noqa: E402
from clientflow_release.update_controller import (  # noqa: E402
    UpdateController,
    UpdateControllerError,
    secure_ingest_verified_artifact,
)
from clientflow_release.updater_config import UpdaterConfig  # noqa: E402
from clientflow_release.updater_state import DeploymentSnapshot  # noqa: E402
from clientflow_release.updater_transport import UpdaterTransportError  # noqa: E402


def _deployment(*, state: str = "verified", bundle: bytes = b"approved-bundle-controller") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "client_id": 23,
        "target_release_id": "clientflow-1.3.1-seq-1301",
        "target_version": "1.3.1",
        "target_release_sequence": 1301,
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "bundle_size": len(bundle),
        "release_approval_reference": "approval-controller-test",
        "release_candidate_sha256": hashlib.sha256(b"candidate-controller").hexdigest(),
        "source_commit": "b" * 40,
        "allow_downgrade": False,
        "reason": None,
        "requested_by_user_id": 1,
        "requested_at": "2026-08-21T08:00:00Z",
        "state": state,
        "state_updated_at": "2026-08-21T08:00:00Z",
        "completed_at": None,
        "observed_previous_release_id": None,
        "observed_release_id": None,
        "observed_release_sequence": None,
        "failure_code": None,
        "failure_message": None,
    }


def _config(tmp: Path) -> UpdaterConfig:
    return UpdaterConfig(
        backend_url="https://display.example.invalid",
        client_id=23,
        credential_id=str(uuid.uuid4()),
        key_id="test-key-id",
        private_key=tmp / "private-key.pem",
        state_root=tmp / "controller-state",
        ca_file=None,
    )


def _write_updater_state(root: Path, deployment: dict, bundle: bytes) -> DeploymentSnapshot:
    snapshot = DeploymentSnapshot.from_backend(deployment)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    artifacts.chmod(0o700)
    filename = f"{snapshot.deployment_id}-{snapshot.bundle_sha256}.tar"
    artifact = artifacts / filename
    artifact.write_bytes(bundle)
    artifact.chmod(0o600)
    state = {
        "schema_version": 1,
        "deployment": snapshot.to_dict(),
        "pending_event": None,
        "artifact": {
            "deployment_id": snapshot.deployment_id,
            "bundle_sha256": snapshot.bundle_sha256,
            "bundle_size": snapshot.bundle_size,
            "filename": filename,
        },
    }
    state_path = root / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state_path.chmod(0o600)
    return snapshot


def _manifest(snapshot: DeploymentSnapshot) -> dict:
    return {
        "release_id": snapshot.target_release_id,
        "version": snapshot.target_version,
        "release_sequence": snapshot.target_release_sequence,
        "release_approval": {
            "reference": snapshot.release_approval_reference,
            "candidate_sha256": snapshot.release_candidate_sha256,
        },
        "source": {"commit": snapshot.source_commit, "dirty": False},
    }


def _record(snapshot: DeploymentSnapshot, manifest: dict) -> dict:
    return {
        "version": snapshot.target_version,
        "release_sequence": snapshot.target_release_sequence,
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "bundle_sha256": snapshot.bundle_sha256,
        "bundle_size": snapshot.bundle_size,
        "release_approval_reference": snapshot.release_approval_reference,
        "release_candidate_sha256": snapshot.release_candidate_sha256,
        "source_commit": snapshot.source_commit,
        "staged_at": "2026-08-21T08:01:00Z",
    }


class FakeTransport:
    def __init__(
        self,
        deployment: dict,
        actions: list[str],
        *,
        fail_activation_start: bool = False,
        lose_activation_start_response: bool = False,
    ):
        self.deployment = dict(deployment)
        self.actions = actions
        self.fail_activation_start = fail_activation_start
        self.lose_activation_start_response = lose_activation_start_response

    def issue_access_token(self) -> str:
        return "token"

    def get_active_deployment(self, _access_token: str):
        if self.deployment.get("completed_at") is not None:
            return None
        return dict(self.deployment)

    def report_event(self, _access_token: str, event: dict):
        event_type = event["event_type"]
        self.actions.append(event_type)
        transitions = {
            ("verified", "staged"): "staged",
            ("activating", "health_check_started"): "health_check",
            ("health_check", "succeeded"): "succeeded",
            ("activating", "rollback_started"): "rolling_back",
            ("health_check", "rollback_started"): "rolling_back",
            ("rolling_back", "rolled_back"): "rolled_back",
            ("activating", "recovery_failed"): "recovery_failed",
            ("health_check", "recovery_failed"): "recovery_failed",
            ("rolling_back", "recovery_failed"): "recovery_failed",
        }
        key = (self.deployment["state"], event_type)
        if key not in transitions:
            raise AssertionError(f"Unexpected transition: {key}")
        self.deployment["state"] = transitions[key]
        if self.deployment["state"] in {"succeeded", "rolled_back", "recovery_failed"}:
            self.deployment["completed_at"] = "2026-08-21T08:05:00Z"
        return {"deployment": dict(self.deployment), "replayed": False}

    def start_activation(self, _access_token: str, *, deployment_id: str, event_id: str, occurred_at: str):
        assert deployment_id == self.deployment["id"]
        assert uuid.UUID(event_id)
        assert occurred_at.endswith("Z")
        self.actions.append("activation_start")
        if self.fail_activation_start:
            raise UpdaterTransportError("activation gate unavailable")
        assert self.deployment["state"] == "staged"
        self.deployment["state"] = "activating"
        if self.lose_activation_start_response:
            self.lose_activation_start_response = False
            raise UpdaterTransportError("activation response lost")
        return dict(self.deployment)


def _controller_fixture(
    tmp: Path,
    *,
    fail_activation_start: bool = False,
    lose_activation_start_response: bool = False,
):
    bundle = b"approved-bundle-controller"
    deployment = _deployment(bundle=bundle)
    updater_root = tmp / "updater"
    updater_root.mkdir(mode=0o700)
    snapshot = _write_updater_state(updater_root, deployment, bundle)
    layout = Layout(tmp / "root")
    layout.releases.mkdir(parents=True, mode=0o755)
    actions: list[str] = []
    transport = FakeTransport(
        deployment,
        actions,
        fail_activation_start=fail_activation_start,
        lose_activation_start_response=lose_activation_start_response,
    )
    local_state = {
        "schema_version": 2,
        "highest_release_sequence": 1200,
        "active_release_id": "clientflow-1.3.0-seq-1200",
        "active_symlink_release_id": "clientflow-1.3.0-seq-1200",
        "previous_release_id": None,
        "staged_release_id": None,
        "installed": {},
        "history": [],
    }

    def stage_func(bundle_path: Path, *, release_id: str, expected_bundle_sha256: str, install_mode: str, layout: Layout):
        actions.append("local_stage")
        assert bundle_path.read_bytes() == bundle
        assert release_id == snapshot.target_release_id
        assert expected_bundle_sha256 == snapshot.bundle_sha256
        assert install_mode == "in_place_update"
        manifest = _manifest(snapshot)
        release_root = layout.releases / snapshot.target_release_id
        release_root.mkdir(parents=True, exist_ok=True)
        manifest_path = release_root / "release-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_path.chmod(0o444)
        for relative in (
            "client-runtime/systemd/clientflow-update-controller.service",
            "client-runtime/libexec/update-controller",
            "release/lib/clientflow_release/update_controller.py",
            "release/lib/clientflow_release/update_controller_entrypoint.py",
        ):
            required = release_root / relative
            required.parent.mkdir(parents=True, exist_ok=True)
            required.write_text("controller-support\n", encoding="utf-8")
            required.chmod(0o444)
        local_state["installed"][snapshot.target_release_id] = _record(snapshot, manifest)
        local_state["highest_release_sequence"] = snapshot.target_release_sequence
        local_state["staged_release_id"] = snapshot.target_release_id
        return {"status": "staged"}

    def activate_func(release_id: str, *, expected_release_approval_reference: str, layout: Layout):
        actions.append("local_activate")
        assert transport.deployment["state"] == "activating"
        assert release_id == snapshot.target_release_id
        assert expected_release_approval_reference == snapshot.release_approval_reference
        previous = local_state["active_release_id"]
        local_state["previous_release_id"] = previous
        local_state["active_release_id"] = snapshot.target_release_id
        local_state["active_symlink_release_id"] = snapshot.target_release_id
        local_state["staged_release_id"] = None
        local_state["installed"][snapshot.target_release_id]["activated_at"] = "2026-08-21T08:03:00Z"
        return {"status": "active", "release_id": release_id, "previous_release_id": previous}

    controller = UpdateController(
        _config(tmp),
        transport=transport,
        source_state_root=updater_root,
        controller_state_root=tmp / "controller-state",
        layout=layout,
        stage_func=stage_func,
        activate_func=activate_func,
        status_func=lambda _layout: dict(local_state),
    )
    return controller, transport, snapshot, actions, local_state


def test_controller_secure_ingest_rejects_artifact_that_does_not_match_snapshot():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        bundle = b"approved-bundle-controller"
        deployment = _deployment(bundle=bundle)
        updater_root = tmp / "updater"
        updater_root.mkdir(mode=0o700)
        snapshot = _write_updater_state(updater_root, deployment, bundle)
        artifact = updater_root / "artifacts" / f"{snapshot.deployment_id}-{snapshot.bundle_sha256}.tar"
        artifact.write_bytes(b"tampered-bundle")
        artifact.chmod(0o600)
        with pytest.raises(UpdateControllerError, match="størrelse|SHA-256"):
            secure_ingest_verified_artifact(
                source_state_root=updater_root,
                controller_state_root=tmp / "controller-state",
                snapshot=snapshot,
            )


def test_controller_full_verified_to_succeeded_order_is_fail_closed():
    with tempfile.TemporaryDirectory() as raw_tmp:
        controller, transport, snapshot, actions, _local_state = _controller_fixture(Path(raw_tmp))
        result = controller.run_once()
        assert result["status"] == "succeeded"
        assert result["release_id"] == snapshot.target_release_id
        assert actions == [
            "local_stage",
            "staged",
            "activation_start",
            "local_activate",
            "health_check_started",
            "succeeded",
        ]
        assert transport.deployment["completed_at"] is not None


def test_controller_backend_activation_gate_failure_prevents_local_activation():
    with tempfile.TemporaryDirectory() as raw_tmp:
        controller, _transport, _snapshot, actions, _local_state = _controller_fixture(
            Path(raw_tmp), fail_activation_start=True
        )
        with pytest.raises(UpdaterTransportError, match="activation gate unavailable"):
            controller.run_once()
        assert actions == ["local_stage", "staged", "activation_start"]
        assert "local_activate" not in actions


def test_controller_automatic_local_rollback_is_reported_to_backend():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        controller, transport, snapshot, actions, local_state = _controller_fixture(tmp)

        def rollback_activate(release_id: str, *, expected_release_approval_reference: str, layout: Layout):
            actions.append("local_activate")
            assert transport.deployment["state"] == "activating"
            local_state["history"].append({
                "event": "automatic_rollback_completed",
                "failed_release_id": release_id,
                "restored_release_id": local_state["active_release_id"],
            })
            local_state["staged_release_id"] = release_id
            raise TransactionError("Aktivering fejlede; tidligere release blev automatisk gendannet")

        controller.activate_func = rollback_activate
        result = controller.run_once()
        assert result["status"] == "rolled_back"
        assert result["release_id"] == snapshot.target_release_id
        assert actions == [
            "local_stage",
            "staged",
            "activation_start",
            "local_activate",
            "rollback_started",
            "rolled_back",
        ]


def test_activation_start_response_loss_recovers_without_repeating_local_stage():
    with tempfile.TemporaryDirectory() as raw_tmp:
        controller, transport, snapshot, actions, _local_state = _controller_fixture(
            Path(raw_tmp), lose_activation_start_response=True
        )
        with pytest.raises(UpdaterTransportError, match="activation response lost"):
            controller.run_once()
        assert transport.deployment["state"] == "activating"
        assert controller.controller_state.phase == "staged"
        assert actions == ["local_stage", "staged", "activation_start"]

        result = controller.run_once()
        assert result["status"] == "succeeded"
        assert result["release_id"] == snapshot.target_release_id
        assert controller.controller_state.phase == "activation_succeeded"
        assert actions == [
            "local_stage",
            "staged",
            "activation_start",
            "local_activate",
            "health_check_started",
            "succeeded",
        ]


def test_old_rollback_history_before_activation_anchor_is_not_reused_for_current_deployment():
    with tempfile.TemporaryDirectory() as raw_tmp:
        controller, transport, snapshot, actions, local_state = _controller_fixture(Path(raw_tmp))
        local_state["history"].append({
            "event": "automatic_rollback_completed",
            "failed_release_id": snapshot.target_release_id,
            "restored_release_id": local_state["active_release_id"],
            "at": "2026-08-20T07:00:00Z",
        })

        def fail_without_transaction_outcome(
            release_id: str, *, expected_release_approval_reference: str, layout: Layout
        ):
            actions.append("local_activate")
            assert transport.deployment["state"] == "activating"
            raise TransactionError("synthetic crash without transaction outcome")

        controller.activate_func = fail_without_transaction_outcome
        with pytest.raises(UpdateControllerError, match="uden et entydigt deployment-bound recovery-resultat"):
            controller.run_once()
        assert controller.controller_state.phase == "activation_authorized"
        assert actions == ["local_stage", "staged", "activation_start", "local_activate"]
        assert "rollback_started" not in actions
        assert "rolled_back" not in actions


def test_crash_after_local_activation_recovers_from_exact_active_release_without_reactivation():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        controller, transport, snapshot, actions, local_state = _controller_fixture(tmp)

        # Materialize the verified/staged half and the backend activation gate,
        # then simulate a process death after the transaction made the exact
        # target active but before controller outcome state was persisted.
        controller.controller_state.bind(snapshot)
        controller._stage_verified(snapshot)
        deployment = controller._report_staged(snapshot)
        assert deployment is not None and deployment["state"] == "staged"
        deployment = controller._authorize_activation(snapshot)
        assert deployment is not None and deployment["state"] == "activating"
        assert controller.controller_state.phase == "activation_authorized"

        previous = local_state["active_release_id"]
        local_state["previous_release_id"] = previous
        local_state["active_release_id"] = snapshot.target_release_id
        local_state["active_symlink_release_id"] = snapshot.target_release_id
        local_state["staged_release_id"] = None
        local_state["installed"][snapshot.target_release_id]["activated_at"] = "2026-08-21T08:03:00Z"

        controller.activate_func = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("local activation must not run twice")
        )
        result = controller.run_once()
        assert result["status"] == "succeeded"
        assert controller.controller_state.phase == "activation_succeeded"
        assert actions == [
            "local_stage",
            "staged",
            "activation_start",
            "health_check_started",
            "succeeded",
        ]


def test_backend_inactive_clears_stale_root_handoff_state():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        controller, transport, snapshot, _actions, _local_state = _controller_fixture(tmp)
        controller.controller_state.bind(snapshot)
        handoff_root = controller.controller_state_root / "handoff"
        handoff_root.mkdir(mode=0o700)
        stale = handoff_root / "stale.tar"
        stale.write_bytes(b"stale")
        stale.chmod(0o600)
        transport.deployment["completed_at"] = "2026-08-21T08:05:00Z"
        transport.deployment["state"] = "cancelled"

        result = controller.run_once()
        assert result == {"status": "idle", "deployment_id": None, "release_id": None}
        assert controller.controller_state.phase == "idle"
        assert not stale.exists()


def test_target_release_without_controller_support_is_not_authorized_for_activation():
    with tempfile.TemporaryDirectory() as raw_tmp:
        controller, _transport, snapshot, actions, _local_state = _controller_fixture(Path(raw_tmp))
        original_stage = controller.stage_func

        def stage_without_helper(*args, **kwargs):
            result = original_stage(*args, **kwargs)
            missing = controller.layout.releases / snapshot.target_release_id / "client-runtime/libexec/update-controller"
            missing.unlink()
            return result

        controller.stage_func = stage_without_helper
        with pytest.raises(UpdateControllerError, match="mangler canonical update-controller support"):
            controller.run_once()
        assert actions == ["local_stage"]
        assert "staged" not in actions
        assert "activation_start" not in actions


def test_controller_resumes_exact_transaction_activation_intent_after_symlink_swap_crash():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        controller, transport, snapshot, actions, local_state = _controller_fixture(tmp)

        controller.controller_state.bind(snapshot)
        controller._stage_verified(snapshot)
        deployment = controller._report_staged(snapshot)
        assert deployment is not None and deployment["state"] == "staged"
        deployment = controller._authorize_activation(snapshot)
        assert deployment is not None and deployment["state"] == "activating"

        previous = local_state["active_release_id"]
        local_state["activation_intent"] = {
            "release_id": snapshot.target_release_id,
            "previous_release_id": previous,
            "release_approval_reference": snapshot.release_approval_reference,
            "started_at": "2026-08-26T10:00:00Z",
        }
        local_state["active_symlink_release_id"] = snapshot.target_release_id

        def resume_activate(release_id: str, *, expected_release_approval_reference: str, layout: Layout):
            actions.append("local_resume")
            assert release_id == snapshot.target_release_id
            assert expected_release_approval_reference == snapshot.release_approval_reference
            assert local_state["activation_intent"]["previous_release_id"] == previous
            local_state["previous_release_id"] = previous
            local_state["active_release_id"] = snapshot.target_release_id
            local_state["active_symlink_release_id"] = snapshot.target_release_id
            local_state["staged_release_id"] = None
            local_state["activation_intent"] = None
            local_state["installed"][snapshot.target_release_id]["activated_at"] = "2026-08-26T10:01:00Z"
            return {"status": "active", "release_id": release_id, "previous_release_id": previous}

        controller.activate_func = resume_activate
        result = controller.run_once()

        assert result["status"] == "succeeded"
        assert "local_resume" in actions
        assert controller.controller_state.phase == "activation_succeeded"
