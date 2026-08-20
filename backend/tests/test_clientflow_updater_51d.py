from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
import sys
import tempfile
import uuid

import jwt
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = REPO_ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release.update_auth import generate_update_key, public_material  # noqa: E402
from clientflow_release.updater_client import StableUpdaterClient, UpdaterClientError  # noqa: E402
from clientflow_release.updater_config import UpdaterConfig  # noqa: E402
from clientflow_release.updater_state import DeploymentSnapshot, UpdaterStateStore  # noqa: E402
from clientflow_release.updater_transport import (  # noqa: E402
    UPDATE_SCOPES,
    UpdaterHTTPError,
    UpdaterTransport,
    UpdaterTransportError,
    _NoRedirectHandler,
)


def _tar_member(name: str, data: bytes, *, mode: int = 0o644, epoch: int = 1_700_000_000):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = epoch
    return info, io.BytesIO(data)


def _valid_bundle_bytes() -> bytes:
    from clientflow_release_format.constants import (
        ARTIFACT_TYPE_RUNTIME_RELEASE,
        CHANNEL,
        DOMAIN_NAMES,
        INSTALL_MODE_FRESH,
        INSTALL_MODE_UPDATE,
        INTEGRITY_ALGORITHM,
        MANIFEST_SCHEMA,
        PRODUCT,
    )

    epoch = 1_700_000_000
    root = "clientflow-1.3.0"
    payload_buffer = io.BytesIO()
    with tarfile.open(fileobj=payload_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        directory.uid = 0
        directory.gid = 0
        directory.uname = "root"
        directory.gname = "root"
        directory.mtime = epoch
        archive.addfile(directory)
    payload = payload_buffer.getvalue()
    manifest = {
        "manifest_schema": MANIFEST_SCHEMA,
        "product": PRODUCT,
        "channel": CHANNEL,
        "version": "1.3.0",
        "release_id": "clientflow-1.3.0-seq-1300",
        "release_sequence": 1300,
        "source_date_epoch": epoch,
        "artifact_type": ARTIFACT_TYPE_RUNTIME_RELEASE,
        "install_modes": [INSTALL_MODE_FRESH, INSTALL_MODE_UPDATE],
        "deployable": True,
        "integrity_algorithm": INTEGRITY_ALGORITHM,
        "release_approval": {
            "reference": "approval-51d-test",
            "candidate_sha256": hashlib.sha256(b"candidate").hexdigest(),
        },
        "source": {"commit": "a" * 40, "dirty": False},
        "fresh_installer": {
            "file": "clientflow-installer-1.3.0.pyz",
            "format": "python-zipapp",
            "size": 123,
            "sha256": "d" * 64,
        },
        "payload": {
            "file": "clientflow-payload.tar",
            "format": "tar",
            "root": root,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "runtime": {
            "python": "3.13.14",
            "architecture": "amd64",
            "offline_wheelhouse_complete": True,
            "artifacts": [],
        },
        "platform": {
            "os": "ubuntu-desktop-lts",
            "minimum_lts": "26.04",
            "architecture": "amd64",
            "requires_preflight": True,
        },
        "credential_domains": list(DOMAIN_NAMES),
        "activation": {
            "automatic": False,
            "requires_manual_approval": True,
            "automatic_reboot": False,
            "health_timeout_seconds": 120,
        },
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    bundle_buffer = io.BytesIO()
    with tarfile.open(fileobj=bundle_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        info, stream = _tar_member("manifest.json", manifest_bytes, epoch=epoch)
        archive.addfile(info, stream)
        info, stream = _tar_member("clientflow-payload.tar", payload, epoch=epoch)
        archive.addfile(info, stream)
    return bundle_buffer.getvalue()


def _deployment(*, state: str = "authorized", deployment_id: str | None = None, payload: bytes = b"artifact"):
    return {
        "id": deployment_id or str(uuid.uuid4()),
        "client_id": 23,
        "target_release_id": "clientflow-1.3.0-seq-1300",
        "target_version": "1.3.0",
        "target_release_sequence": 1300,
        "bundle_sha256": hashlib.sha256(payload).hexdigest(),
        "bundle_size": len(payload),
        "release_approval_reference": "approval-51d-test",
        "release_candidate_sha256": hashlib.sha256(b"candidate").hexdigest(),
        "source_commit": "a" * 40,
        "allow_downgrade": False,
        "reason": None,
        "requested_by_user_id": 1,
        "requested_at": "2026-08-20T08:00:00Z",
        "state": state,
        "state_updated_at": "2026-08-20T08:00:00Z",
        "completed_at": None,
        "observed_previous_release_id": None,
        "observed_release_id": None,
        "observed_release_sequence": None,
        "failure_code": None,
        "failure_message": None,
    }


def _config(tmp: Path) -> UpdaterConfig:
    key = tmp / "private-key.pem"
    _pem, key_id, _jwk, _thumbprint = generate_update_key(key)
    return UpdaterConfig(
        backend_url="https://display.example.invalid",
        client_id=23,
        credential_id=str(uuid.uuid4()),
        key_id=key_id,
        private_key=key,
        state_root=tmp / "state",
        ca_file=None,
    )


class _Response:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def read(self, amount: int = -1):
        return self._body.read(amount)

    def getcode(self):
        return self.status

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class _CapturingOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=30):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _header(request, name: str) -> str:
    for key, value in request.header_items():
        if key.lower() == name.lower():
            return value
    return ""


def test_51d_transport_uses_private_key_assertion_and_unique_dpop_per_request():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        active = _deployment()
        opener = _CapturingOpener([
            _Response(json.dumps({
                "access_token": "update-access-token",
                "token_type": "DPoP",
                "expires_in": 300,
                "scope": " ".join(sorted(UPDATE_SCOPES)),
            }).encode()),
            _Response(json.dumps(active).encode()),
            _Response(json.dumps(active).encode()),
        ])
        transport = UpdaterTransport(config, opener=opener)

        token = transport.issue_access_token()
        assert token == "update-access-token"
        transport.get_active_deployment(token)
        transport.get_active_deployment(token)

        token_request = opener.requests[0][0]
        assert token_request.full_url == "https://display.example.invalid/api/clientflow-update/token"
        assert not _header(token_request, "Authorization")
        token_dpop = _header(token_request, "DPoP")
        assert token_dpop
        public_pem = public_material(config.private_key)[0]
        token_dpop_claims = jwt.decode(
            token_dpop,
            public_pem,
            algorithms=["EdDSA"],
            options={"verify_aud": False, "verify_exp": False},
        )
        assert token_dpop_claims["htm"] == "POST"
        assert token_dpop_claims["htu"] == token_request.full_url
        assert "ath" not in token_dpop_claims

        body = json.loads(token_request.data.decode())
        assert set(body["scope"].split()) == UPDATE_SCOPES
        assertion_claims = jwt.decode(
            body["client_assertion"],
            public_pem,
            algorithms=["EdDSA"],
            audience="urn:planiq:clientflow-update:token",
        )
        assert assertion_claims["iss"] == config.credential_id
        assert assertion_claims["sub"] == config.credential_id

        resource_proofs = []
        for request, _timeout in opener.requests[1:]:
            assert _header(request, "Authorization") == "DPoP update-access-token"
            proof = _header(request, "DPoP")
            claims = jwt.decode(
                proof,
                public_pem,
                algorithms=["EdDSA"],
                options={"verify_aud": False, "verify_exp": False},
            )
            assert claims["htm"] == "GET"
            assert claims["htu"] == request.full_url
            assert "ath" in claims
            resource_proofs.append(claims["jti"])
        assert resource_proofs[0] != resource_proofs[1]


def test_51d_transport_forbids_redirects_and_absolute_artifact_authority():
    handler = _NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil.invalid/") is None

    with tempfile.TemporaryDirectory() as raw_tmp:
        config = _config(Path(raw_tmp))
        transport = UpdaterTransport(config, opener=_CapturingOpener([]))
        with pytest.raises(UpdaterTransportError, match="canonical backend-path"):
            transport._url("https://evil.invalid/api/clientflow/release-artifacts/x")

        deployment = _deployment(state="downloading")
        snapshot = DeploymentSnapshot.from_backend(deployment)
        with pytest.raises(UpdaterTransportError, match="matcher ikke deployment snapshot"):
            transport.download_artifact(
                {
                    "artifact_url": "https://evil.invalid/artifact",
                    "access_token": "artifact-token",
                },
                snapshot,
                io.BytesIO(),
            )


class _FakeTransport:
    def __init__(self, deployment: dict | None, artifact: bytes):
        self.deployment = dict(deployment) if deployment else None
        self.artifact = artifact
        self.events = []
        self.authorizations = 0
        self.downloads = 0
        self.report_failures = []
        self.active_sequence = []

    def issue_access_token(self):
        return "opaque-update-token"

    def get_active_deployment(self, access_token):
        assert access_token == "opaque-update-token"
        if self.active_sequence:
            value = self.active_sequence.pop(0)
            return dict(value) if value else None
        return dict(self.deployment) if self.deployment else None

    def report_event(self, access_token, event):
        self.events.append(dict(event))
        if self.report_failures:
            failure = self.report_failures.pop(0)
            if failure is not None:
                raise failure
        if self.deployment is None:
            raise AssertionError("No active deployment")
        if event["event_type"] == "download_started" and self.deployment["state"] == "authorized":
            self.deployment["state"] = "downloading"
        elif event["event_type"] == "bundle_verified" and self.deployment["state"] == "downloading":
            self.deployment["state"] = "verified"
        return {"deployment": dict(self.deployment), "replayed": False}

    def authorize_artifact(self, access_token, snapshot):
        self.authorizations += 1
        return {
            "access_token": "opaque-artifact-token",
            "token_type": "DPoP",
            "expires_in": 120,
            "release_id": snapshot.target_release_id,
            "bundle_sha256": snapshot.bundle_sha256,
            "bundle_size": snapshot.bundle_size,
            "artifact_url": f"/api/clientflow/release-artifacts/{snapshot.target_release_id}",
        }

    def download_artifact(self, authorization, snapshot, destination):
        import hashlib

        self.downloads += 1
        destination.write(self.artifact)
        destination.flush()
        os.fsync(destination.fileno())
        return len(self.artifact), hashlib.sha256(self.artifact).hexdigest()


def test_51d_authorized_to_verified_persists_exact_artifact_and_events():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="authorized", payload=payload)
        transport = _FakeTransport(deployment, payload)
        state = UpdaterStateStore(config.state_root)
        client = StableUpdaterClient(config, transport=transport, state=state)

        result = client.run_once()

        assert result["status"] == "verified"
        artifact = Path(result["artifact"])
        assert artifact.read_bytes() == payload
        assert [event["event_type"] for event in transport.events] == ["download_started", "bundle_verified"]
        assert state.pending_event is None
        assert state.verify_local_artifact(DeploymentSnapshot.from_backend(transport.deployment)) == artifact


def test_51d_persists_event_id_before_network_and_replays_same_id_after_lost_response():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="authorized", payload=payload)
        transport = _FakeTransport(deployment, payload)

        class CommitThenDisconnect(_FakeTransport):
            def __init__(self, deployment, artifact):
                super().__init__(deployment, artifact)
                self.disconnect_once = True

            def report_event(self, access_token, event):
                self.events.append(dict(event))
                if event["event_type"] == "download_started" and self.deployment["state"] == "authorized":
                    self.deployment["state"] = "downloading"
                    if self.disconnect_once:
                        self.disconnect_once = False
                        raise UpdaterHTTPError(599, "connection lost after commit")
                return {"deployment": dict(self.deployment), "replayed": True}

        transport = CommitThenDisconnect(deployment, payload)
        state = UpdaterStateStore(config.state_root)
        client = StableUpdaterClient(config, transport=transport, state=state)

        with pytest.raises(UpdaterHTTPError, match="connection lost"):
            client.run_once()
        pending = state.pending_event
        assert pending is not None
        first_event_id = pending["event_id"]

        result = client.run_once()
        assert result["status"] == "downloading"
        assert transport.events[0]["event_id"] == first_event_id
        assert transport.events[1]["event_id"] == first_event_id
        assert state.pending_event is None


def test_51d_cancellation_conflict_discards_downloaded_artifact():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="downloading", payload=payload)
        transport = _FakeTransport(deployment, payload)
        transport.report_failures = [UpdaterHTTPError(409, "deployment cancelled")]
        transport.active_sequence = [deployment, None]
        state = UpdaterStateStore(config.state_root)
        client = StableUpdaterClient(config, transport=transport, state=state)

        result = client.run_once()

        assert result == {"status": "inactive", "deployment_id": None, "artifact": None}
        assert state.snapshot is None
        assert list(state.artifact_root.iterdir()) == []


def test_51d_verified_state_redownloads_corrupt_local_artifact_without_replaying_transition():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="verified", payload=payload)
        transport = _FakeTransport(deployment, payload)
        state = UpdaterStateStore(config.state_root)
        snapshot = state.bind_deployment(deployment)

        temporary, handle = state.begin_download(snapshot)
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        artifact = state.commit_download(
            snapshot,
            temporary,
            observed_size=len(payload),
            observed_sha256=hashlib.sha256(payload).hexdigest(),
        )
        artifact.write_bytes(b"corrupt")

        client = StableUpdaterClient(config, transport=transport, state=state)
        result = client.run_once()

        assert result["status"] == "verified"
        assert Path(result["artifact"]).read_bytes() == payload
        assert transport.authorizations == 1
        assert transport.downloads == 1
        assert transport.events == []


def test_51d_artifact_download_is_dpop_bound_to_artifact_token_and_exact_bytes():
    payload = b"artifact-dpop-bytes"
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="downloading", payload=payload)
        snapshot = DeploymentSnapshot.from_backend(deployment)
        opener = _CapturingOpener([
            _Response(payload, headers={"Content-Length": str(len(payload))}),
        ])
        transport = UpdaterTransport(config, opener=opener)
        authorization = {
            "artifact_url": f"/api/clientflow/release-artifacts/{snapshot.target_release_id}",
            "access_token": "deployment-bound-artifact-token",
        }
        target = tmp / "download.part"
        with target.open("wb") as handle:
            size, sha256 = transport.download_artifact(authorization, snapshot, handle)

        assert size == len(payload)
        assert sha256 == hashlib.sha256(payload).hexdigest()
        assert target.read_bytes() == payload
        request = opener.requests[0][0]
        assert _header(request, "Authorization") == "DPoP deployment-bound-artifact-token"
        public_pem = public_material(config.private_key)[0]
        claims = jwt.decode(
            _header(request, "DPoP"),
            public_pem,
            algorithms=["EdDSA"],
            options={"verify_aud": False, "verify_exp": False},
        )
        assert claims["htm"] == "GET"
        assert claims["htu"] == request.full_url
        assert "ath" in claims



def test_51d_state_recovers_atomic_artifact_and_cleans_crash_partials():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="downloading", payload=payload)
        state = UpdaterStateStore(config.state_root)
        snapshot = state.bind_deployment(deployment)

        orphan = state.artifact_root / f".{snapshot.deployment_id}.dead.part"
        orphan.write_bytes(b"partial")
        os.chmod(orphan, 0o600)
        destination = state.artifact_path(snapshot)
        destination.write_bytes(payload)
        os.chmod(destination, 0o600)

        recovered = UpdaterStateStore(config.state_root)
        assert not orphan.exists()
        assert recovered.verify_local_artifact(snapshot) == destination
        assert recovered.verify_local_artifact(snapshot).read_bytes() == payload


def test_51d_rejects_manifest_snapshot_mismatch_before_bundle_verified_event():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="downloading", payload=payload)
        deployment["source_commit"] = "b" * 40
        transport = _FakeTransport(deployment, payload)
        state = UpdaterStateStore(config.state_root)
        client = StableUpdaterClient(config, transport=transport, state=state)

        with pytest.raises(UpdaterClientError, match="manifest matcher ikke deployment snapshot"):
            client.run_once()
        assert transport.events == []


def test_51d_rejects_cross_client_deployment_even_if_backend_response_shape_is_valid():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        config = _config(Path(raw_tmp))
        deployment = _deployment(state="authorized", payload=payload)
        deployment["client_id"] = 999
        transport = _FakeTransport(deployment, payload)
        client = StableUpdaterClient(config, transport=transport)

        with pytest.raises(UpdaterClientError, match="client_id matcher ikke update identity"):
            client.run_once()


def test_51d_cancellation_before_artifact_authorization_is_reconciled_without_download():
    payload = _valid_bundle_bytes()
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        config = _config(tmp)
        deployment = _deployment(state="downloading", payload=payload)

        class CancelBeforeAuthorize(_FakeTransport):
            def authorize_artifact(self, access_token, snapshot):
                self.authorizations += 1
                self.deployment = None
                raise UpdaterHTTPError(409, "deployment cancelled")

        transport = CancelBeforeAuthorize(deployment, payload)
        state = UpdaterStateStore(config.state_root)
        client = StableUpdaterClient(config, transport=transport, state=state)

        result = client.run_once()
        assert result == {"status": "inactive", "deployment_id": None, "artifact": None}
        assert transport.downloads == 0
        assert state.snapshot is None
