"""Canonical Step 51D updater orchestration through verified local artifact state."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from clientflow_release_format.bundle import BundleFormatError, verify_bundle_structure

from .constants import INSTALL_MODE_UPDATE
from .updater_config import UpdaterConfig
from .updater_state import DeploymentSnapshot, UpdaterStateStore
from .updater_transport import UpdaterHTTPError, UpdaterTransport


class UpdaterClientError(RuntimeError):
    pass


class StableUpdaterClient:
    def __init__(
        self,
        config: UpdaterConfig,
        *,
        transport: UpdaterTransport | None = None,
        state: UpdaterStateStore | None = None,
    ):
        self.config = config
        self.transport = transport or UpdaterTransport(config)
        self.state = state or UpdaterStateStore(config.state_root)

    @staticmethod
    def _deployment_state(deployment: dict[str, Any]) -> str:
        value = str(deployment.get("state") or "").strip()
        if value not in {
            "authorized", "downloading", "verified", "staged", "activating",
            "health_check", "succeeded", "failed", "cancelled", "rolling_back",
            "rolled_back", "recovery_failed",
        }:
            raise UpdaterClientError(f"Backend returnerede ukendt deployment state {value!r}")
        return value

    def _bind_deployment(self, deployment: dict[str, Any]) -> DeploymentSnapshot:
        try:
            client_id = int(deployment.get("client_id"))
        except (TypeError, ValueError) as exc:
            raise UpdaterClientError("Deployment client_id er ugyldig") from exc
        if client_id != self.config.client_id:
            raise UpdaterClientError("Deployment client_id matcher ikke update identity")
        return self.state.bind_deployment(deployment)

    def _reconcile_after_conflict(self, access_token: str, original: UpdaterHTTPError) -> dict[str, Any] | None:
        if original.status != 409:
            raise original
        active = self.transport.get_active_deployment(access_token)
        if active is None:
            self.state.clear_inactive()
            return None
        raise original

    def _report_pending(self, access_token: str, deployment: dict[str, Any]) -> dict[str, Any] | None:
        pending = self.state.pending_event
        if pending is None:
            return deployment
        if pending["deployment_id"] != str(deployment.get("id") or ""):
            raise UpdaterClientError("Pending event matcher ikke backendens aktive deployment")
        try:
            response = self.transport.report_event(access_token, pending)
        except UpdaterHTTPError as exc:
            return self._reconcile_after_conflict(access_token, exc)
        acknowledged = response["deployment"]
        self._bind_deployment(acknowledged)
        self.state.acknowledge_event(pending["event_id"])
        return acknowledged

    def _send_event(
        self,
        access_token: str,
        deployment: dict[str, Any],
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        event = self.state.ensure_pending_event(
            deployment_id=str(deployment["id"]),
            event_type=event_type,
            payload=payload,
        )
        try:
            response = self.transport.report_event(access_token, event)
        except UpdaterHTTPError as exc:
            return self._reconcile_after_conflict(access_token, exc)
        updated = response["deployment"]
        self._bind_deployment(updated)
        self.state.acknowledge_event(event["event_id"])
        return updated

    def _verify_bundle_contract(self, artifact: Path, snapshot: DeploymentSnapshot) -> None:
        try:
            manifest, bundle_size, bundle_sha256 = verify_bundle_structure(
                artifact,
                require_deployable=True,
                required_install_mode=INSTALL_MODE_UPDATE,
            )
        except BundleFormatError as exc:
            raise UpdaterClientError(f"Downloaded bundle-kontrakt er ugyldig: {exc}") from exc
        if bundle_size != snapshot.bundle_size or bundle_sha256 != snapshot.bundle_sha256:
            raise UpdaterClientError("Downloaded bundle identity matcher ikke deployment snapshot")
        approval = manifest.get("release_approval") or {}
        source = manifest.get("source") or {}
        actual = (
            str(manifest.get("release_id") or ""),
            str(manifest.get("version") or ""),
            int(manifest.get("release_sequence") or 0),
            str(approval.get("reference") or ""),
            str(approval.get("candidate_sha256") or "") or None,
            str(source.get("commit") or "") or None,
        )
        expected = (
            snapshot.target_release_id,
            snapshot.target_version,
            snapshot.target_release_sequence,
            snapshot.release_approval_reference,
            snapshot.release_candidate_sha256,
            snapshot.source_commit,
        )
        if actual != expected:
            raise UpdaterClientError("Downloaded bundle manifest matcher ikke deployment snapshot")
        if self.state.verify_local_artifact(snapshot) is None:
            raise UpdaterClientError("Downloaded bundle ændrede exact bytes under lokal verifikation")

    def _ensure_artifact(self, access_token: str, snapshot: DeploymentSnapshot) -> Path:
        artifact = self.state.verify_local_artifact(snapshot)
        if artifact is None:
            authorization = self.transport.authorize_artifact(access_token, snapshot)
            temporary, handle = self.state.begin_download(snapshot)
            try:
                with handle:
                    observed_size, observed_sha256 = self.transport.download_artifact(
                        authorization,
                        snapshot,
                        handle,
                    )
                artifact = self.state.commit_download(
                    snapshot,
                    temporary,
                    observed_size=observed_size,
                    observed_sha256=observed_sha256,
                )
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        self._verify_bundle_contract(artifact, snapshot)
        return artifact


    def _ensure_artifact_or_reconcile(
        self,
        access_token: str,
        snapshot: DeploymentSnapshot,
    ) -> Path | None:
        try:
            return self._ensure_artifact(access_token, snapshot)
        except UpdaterHTTPError as exc:
            if exc.status not in {401, 409}:
                raise
            try:
                active = self.transport.get_active_deployment(access_token)
            except Exception:
                raise exc
            if active is None:
                self.state.clear_inactive()
                return None
            raise exc

    def run_once(self) -> dict[str, Any]:
        access_token = self.transport.issue_access_token()
        deployment = self.transport.get_active_deployment(access_token)
        if deployment is None:
            self.state.clear_inactive()
            return {"status": "idle", "deployment_id": None, "artifact": None}

        snapshot = self._bind_deployment(deployment)
        deployment = self._report_pending(access_token, deployment)
        if deployment is None:
            return {"status": "inactive", "deployment_id": None, "artifact": None}
        snapshot = self._bind_deployment(deployment)
        state = self._deployment_state(deployment)

        if state == "authorized":
            deployment = self._send_event(access_token, deployment, event_type="download_started")
            if deployment is None:
                return {"status": "inactive", "deployment_id": None, "artifact": None}
            snapshot = self._bind_deployment(deployment)
            state = self._deployment_state(deployment)

        if state == "downloading":
            artifact = self._ensure_artifact_or_reconcile(access_token, snapshot)
            if artifact is None:
                return {"status": "inactive", "deployment_id": None, "artifact": None}
            deployment = self._send_event(
                access_token,
                deployment,
                event_type="bundle_verified",
                payload={
                    "release_id": snapshot.target_release_id,
                    "bundle_sha256": snapshot.bundle_sha256,
                    "bundle_size": snapshot.bundle_size,
                },
            )
            if deployment is None:
                return {"status": "inactive", "deployment_id": None, "artifact": None}
            state = self._deployment_state(deployment)
            return {
                "status": state,
                "deployment_id": snapshot.deployment_id,
                "artifact": str(artifact),
            }

        if state in {"verified", "staged"}:
            artifact = self._ensure_artifact_or_reconcile(access_token, snapshot)
            if artifact is None:
                return {"status": "inactive", "deployment_id": None, "artifact": None}
            return {
                "status": state,
                "deployment_id": snapshot.deployment_id,
                "artifact": str(artifact),
            }

        # Step 51D stops before staged -> activating and remains observer-only
        # for any later state that can still appear from the active endpoint.
        return {
            "status": state,
            "deployment_id": snapshot.deployment_id,
            "artifact": None,
        }
