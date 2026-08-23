from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = REPO_ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release.transaction import Layout, TransactionError  # noqa: E402
from clientflow_release.update_controller import UpdateController  # noqa: E402
from clientflow_release.updater_client import StableUpdaterClient  # noqa: E402
from clientflow_release.updater_config import UpdaterConfig  # noqa: E402
from clientflow_release.updater_state import DeploymentSnapshot  # noqa: E402
from service1.clientflow_deployments import (  # noqa: E402
    active_deployment,
    authorize_activation,
    create_authorized_deployment,
    report_updater_event,
    utcnow,
)
from service1.clientflow_update_models import (  # noqa: E402
    ClientFlowDeployment,
    ClientFlowDeploymentEvent,
    ClientFlowUpdateCredential,
)
from service1.models import Client  # noqa: E402
from tests.test_clientflow_updater_51d import _valid_bundle_bytes  # noqa: E402


CLIENT_ID = 7301
PREVIOUS_RELEASE_ID = "clientflow-1.2.9-seq-1299"
TARGET_RELEASE_ID = "clientflow-1.3.0-seq-1300"
TARGET_VERSION = "1.3.0"
TARGET_SEQUENCE = 1300
APPROVAL_REFERENCE = "approval-51d-test"
CANDIDATE_SHA256 = hashlib.sha256(b"candidate").hexdigest()
SOURCE_COMMIT = "a" * 40
UPDATE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAzU6003WsShJbh/Yk3H4tAwXd4ep+A128YEJSAYemC68=
-----END PUBLIC KEY-----
"""


def _deployment_dict(row: ClientFlowDeployment) -> dict:
    def timestamp(value: datetime | None):
        if value is None:
            return None
        return value.isoformat() + ("Z" if value.tzinfo is None else "")

    return {
        "id": row.id,
        "client_id": row.client_id,
        "target_release_id": row.target_release_id,
        "target_version": row.target_version,
        "target_release_sequence": row.target_release_sequence,
        "bundle_sha256": row.bundle_sha256,
        "bundle_size": row.bundle_size,
        "release_approval_reference": row.release_approval_reference,
        "release_candidate_sha256": row.release_candidate_sha256,
        "source_commit": row.source_commit,
        "allow_downgrade": row.allow_downgrade,
        "reason": row.reason,
        "requested_by_user_id": row.requested_by_user_id,
        "requested_at": timestamp(row.requested_at),
        "state": row.state,
        "state_updated_at": timestamp(row.state_updated_at),
        "completed_at": timestamp(row.completed_at),
        "observed_previous_release_id": row.observed_previous_release_id,
        "observed_release_id": row.observed_release_id,
        "observed_release_sequence": row.observed_release_sequence,
        "failure_code": row.failure_code,
        "failure_message": row.failure_message,
    }


def _occurred_at(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class _BackendStateTransport:
    """Test adapter around the real backend-owned deployment state machine.

    Update crypto/HTTP binding is covered by the claim operational HTTP gate;
    this adapter deliberately exercises the backend transition functions so
    controller expectations cannot drift behind a hand-maintained fake map.
    """

    def __init__(self, engine, *, credential_id: str, artifact: bytes):
        self.engine = engine
        self.credential_id = credential_id
        self.artifact = artifact

    def issue_access_token(self) -> str:
        return "already-covered-by-update-auth-http-gate"

    def get_active_deployment(self, _access_token: str):
        with Session(self.engine) as session:
            row = active_deployment(session, client_id=CLIENT_ID)
            return _deployment_dict(row) if row is not None else None

    def report_event(self, _access_token: str, event: dict):
        with Session(self.engine) as session:
            deployment, _stored_event, replayed = report_updater_event(
                session,
                deployment_id=str(event["deployment_id"]),
                credential_id=self.credential_id,
                event_id=str(event["event_id"]),
                event_type=str(event["event_type"]),
                occurred_at=_occurred_at(str(event.get("occurred_at") or "")),
                payload=dict(event.get("payload") or {}),
            )
            session.commit()
            session.refresh(deployment)
            return {"deployment": _deployment_dict(deployment), "replayed": replayed}

    def start_activation(
        self,
        _access_token: str,
        *,
        deployment_id: str,
        event_id: str,
        occurred_at: str,
    ):
        with Session(self.engine) as session:
            deployment = authorize_activation(
                session,
                deployment_id=deployment_id,
                credential_id=self.credential_id,
                event_id=event_id,
                occurred_at=_occurred_at(occurred_at),
            )
            session.commit()
            session.refresh(deployment)
            return _deployment_dict(deployment)

    def authorize_artifact(self, _access_token: str, snapshot: DeploymentSnapshot):
        assert snapshot.target_release_id == TARGET_RELEASE_ID
        return {
            "access_token": "artifact-capability-covered-by-artifact-auth-tests",
            "token_type": "dpop",
            "expires_in": 60,
            "release_id": snapshot.target_release_id,
            "bundle_sha256": snapshot.bundle_sha256,
            "bundle_size": snapshot.bundle_size,
            "artifact_url": f"/api/clientflow/release-artifacts/{snapshot.target_release_id}",
        }

    def download_artifact(self, authorization: dict, snapshot: DeploymentSnapshot, destination):
        assert authorization["release_id"] == snapshot.target_release_id
        destination.write(self.artifact)
        return len(self.artifact), hashlib.sha256(self.artifact).hexdigest()


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


def _local_record(snapshot: DeploymentSnapshot, manifest: dict) -> dict:
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
        "staged_at": "2026-08-23T20:00:00Z",
    }


def _create_backend(engine, *, bundle: bytes) -> str:
    with Session(engine) as session:
        client = Client(id=CLIENT_ID, name="Update Chain Integration", status="approved")
        credential_id = str(uuid.uuid4())
        credential = ClientFlowUpdateCredential(
            id=credential_id,
            client_id=CLIENT_ID,
            key_id=uuid.uuid4().hex,
            public_key_pem=UPDATE_PUBLIC_KEY_PEM,
            algorithm="Ed25519",
            created_at=utcnow(),
        )
        session.add(client)
        session.add(credential)
        session.commit()

        deployment = create_authorized_deployment(
            session,
            client_id=CLIENT_ID,
            requested_by_user_id=None,
            target_release_id=TARGET_RELEASE_ID,
            target_version=TARGET_VERSION,
            target_release_sequence=TARGET_SEQUENCE,
            bundle_sha256=hashlib.sha256(bundle).hexdigest(),
            bundle_size=len(bundle),
            release_approval_reference=APPROVAL_REFERENCE,
            release_candidate_sha256=CANDIDATE_SHA256,
            source_commit=SOURCE_COMMIT,
            allow_downgrade=False,
            reason=None,
        )
        session.commit()
        assert deployment.state == "authorized"
        return credential_id


def _config(tmp: Path, *, credential_id: str) -> UpdaterConfig:
    return UpdaterConfig(
        backend_url="https://display.example.invalid",
        client_id=CLIENT_ID,
        credential_id=credential_id,
        key_id="integration-key-id",
        private_key=tmp / "unused-private-key.pem",
        state_root=tmp / "updater-state",
        ca_file=None,
    )


def _controller(
    tmp: Path,
    *,
    transport: _BackendStateTransport,
    config: UpdaterConfig,
    fail_activation: bool,
):
    layout = Layout(tmp / "root")
    layout.releases.mkdir(parents=True, mode=0o755)
    local_state = {
        "schema_version": 2,
        "highest_release_sequence": 1299,
        "active_release_id": PREVIOUS_RELEASE_ID,
        "active_symlink_release_id": PREVIOUS_RELEASE_ID,
        "previous_release_id": None,
        "staged_release_id": None,
        "installed": {},
        "history": [],
    }

    def stage_func(bundle_path: Path, *, release_id: str, expected_bundle_sha256: str, install_mode: str, layout: Layout):
        assert bundle_path.read_bytes() == transport.artifact
        assert release_id == TARGET_RELEASE_ID
        assert expected_bundle_sha256 == hashlib.sha256(transport.artifact).hexdigest()
        assert install_mode == "in_place_update"
        deployment = transport.get_active_deployment("token")
        assert deployment is not None and deployment["state"] == "verified"
        snapshot = DeploymentSnapshot.from_backend(deployment)
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
            path = release_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("operational-update-chain\n", encoding="utf-8")
            path.chmod(0o444)
        local_state["installed"][snapshot.target_release_id] = _local_record(snapshot, manifest)
        local_state["highest_release_sequence"] = snapshot.target_release_sequence
        local_state["staged_release_id"] = snapshot.target_release_id
        return {"status": "staged", "release_id": snapshot.target_release_id}

    def activate_func(release_id: str, *, expected_release_approval_reference: str, layout: Layout):
        backend = transport.get_active_deployment("token")
        assert backend is not None and backend["state"] == "activating"
        assert release_id == TARGET_RELEASE_ID
        assert expected_release_approval_reference == APPROVAL_REFERENCE
        if fail_activation:
            local_state["history"].append(
                {
                    "event": "automatic_rollback_completed",
                    "failed_release_id": release_id,
                    "restored_release_id": PREVIOUS_RELEASE_ID,
                }
            )
            local_state["staged_release_id"] = release_id
            raise TransactionError("Aktivering fejlede; tidligere release blev automatisk gendannet")
        local_state["previous_release_id"] = PREVIOUS_RELEASE_ID
        local_state["active_release_id"] = release_id
        local_state["active_symlink_release_id"] = release_id
        local_state["staged_release_id"] = None
        local_state["installed"][release_id]["activated_at"] = "2026-08-23T20:03:00Z"
        return {"status": "active", "release_id": release_id, "previous_release_id": PREVIOUS_RELEASE_ID}

    return UpdateController(
        config,
        transport=transport,
        source_state_root=config.state_root,
        controller_state_root=tmp / "controller-state",
        layout=layout,
        stage_func=stage_func,
        activate_func=activate_func,
        status_func=lambda _layout: dict(local_state),
    ), local_state


def _event_types(engine) -> list[str]:
    with Session(engine) as session:
        return [
            row.event_type
            for row in session.exec(
                select(ClientFlowDeploymentEvent).order_by(ClientFlowDeploymentEvent.received_at, ClientFlowDeploymentEvent.id)
            ).all()
        ]


def _run_verified_handoff(tmp: Path):
    bundle = _valid_bundle_bytes()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    credential_id = _create_backend(engine, bundle=bundle)
    config = _config(tmp, credential_id=credential_id)
    transport = _BackendStateTransport(engine, credential_id=credential_id, artifact=bundle)

    updater = StableUpdaterClient(config, transport=transport)
    updater_result = updater.run_once()
    assert updater_result["status"] == "verified"
    artifact = Path(str(updater_result["artifact"]))
    assert artifact.is_file()
    assert artifact.read_bytes() == bundle

    with Session(engine) as session:
        deployment = active_deployment(session, client_id=CLIENT_ID)
        assert deployment is not None and deployment.state == "verified"
    return engine, config, transport


def test_operational_update_chain_real_backend_state_machine_reaches_succeeded():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        engine, config, transport = _run_verified_handoff(tmp)
        controller, local_state = _controller(
            tmp,
            transport=transport,
            config=config,
            fail_activation=False,
        )

        result = controller.run_once()
        assert result == {
            "status": "succeeded",
            "deployment_id": result["deployment_id"],
            "release_id": TARGET_RELEASE_ID,
        }
        assert local_state["active_release_id"] == TARGET_RELEASE_ID
        assert local_state["previous_release_id"] == PREVIOUS_RELEASE_ID
        assert local_state["staged_release_id"] is None

        with Session(engine) as session:
            deployment = session.exec(select(ClientFlowDeployment).where(ClientFlowDeployment.client_id == CLIENT_ID)).one()
            assert deployment.state == "succeeded"
            assert deployment.completed_at is not None
            assert deployment.observed_release_id == TARGET_RELEASE_ID
            assert deployment.observed_release_sequence == TARGET_SEQUENCE
            assert deployment.observed_previous_release_id == PREVIOUS_RELEASE_ID

        assert _event_types(engine) == [
            "authorized",
            "download_started",
            "bundle_verified",
            "staged",
            "activation_started",
            "health_check_started",
            "succeeded",
        ]


def test_operational_update_chain_real_backend_state_machine_records_automatic_rollback():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        engine, config, transport = _run_verified_handoff(tmp)
        controller, local_state = _controller(
            tmp,
            transport=transport,
            config=config,
            fail_activation=True,
        )

        result = controller.run_once()
        assert result["status"] == "rolled_back"
        assert result["release_id"] == TARGET_RELEASE_ID
        assert local_state["active_release_id"] == PREVIOUS_RELEASE_ID
        assert local_state["staged_release_id"] == TARGET_RELEASE_ID

        with Session(engine) as session:
            deployment = session.exec(select(ClientFlowDeployment).where(ClientFlowDeployment.client_id == CLIENT_ID)).one()
            assert deployment.state == "rolled_back"
            assert deployment.completed_at is not None

        assert _event_types(engine) == [
            "authorized",
            "download_started",
            "bundle_verified",
            "staged",
            "activation_started",
            "rollback_started",
            "rolled_back",
        ]
