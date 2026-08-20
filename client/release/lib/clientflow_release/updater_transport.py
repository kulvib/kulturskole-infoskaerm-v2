"""DPoP-only HTTPS transport for the stable ClientFlow updater."""
from __future__ import annotations

import hashlib
import json
import ssl
from typing import Any, BinaryIO
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .update_auth import build_client_assertion, build_dpop_proof
from .updater_config import UpdaterConfig
from .updater_state import DeploymentSnapshot, DOWNLOAD_CHUNK_BYTES, UpdaterStateError

CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
UPDATE_SCOPES = frozenset({"deployment:read", "deployment:report", "artifact:authorize"})
MAX_JSON_RESPONSE_BYTES = 1024 * 1024


class UpdaterTransportError(RuntimeError):
    pass


class UpdaterHTTPError(UpdaterTransportError):
    def __init__(self, status: int, detail: str):
        self.status = int(status)
        self.detail = str(detail)
        super().__init__(f"HTTP {self.status}: {self.detail}")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UpdaterTransport:
    def __init__(self, config: UpdaterConfig, *, opener=None):
        self.config = config
        if opener is None:
            context = ssl.create_default_context(cafile=str(config.ca_file) if config.ca_file else None)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=context),
                _NoRedirectHandler(),
            )
        self._opener = opener

    def _url(self, path: str) -> str:
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path.startswith("/api/"):
            raise UpdaterTransportError("Updater endpoint skal være en canonical backend-path")
        return f"{self.config.backend_url}{parsed.path}"

    @staticmethod
    def _error_detail(exc: urllib.error.HTTPError) -> str:
        try:
            raw = exc.read(MAX_JSON_RESPONSE_BYTES + 1)
            if len(raw) > MAX_JSON_RESPONSE_BYTES:
                return "HTTP-fejlrespons er for stor"
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict) and str(value.get("detail") or "").strip():
                return str(value["detail"])
        except Exception:
            pass
        return str(exc.reason or "HTTP request fejlede")

    def _open(self, request: urllib.request.Request, *, timeout: int = 30):
        try:
            response = self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise UpdaterHTTPError(exc.code, self._error_detail(exc)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpdaterTransportError(f"Updater HTTPS request fejlede: {exc}") from exc
        status = int(getattr(response, "status", response.getcode()))
        if 300 <= status <= 399:
            response.close()
            raise UpdaterHTTPError(status, "HTTP redirects er ikke tilladt for updater-auth/download")
        if status < 200 or status >= 300:
            response.close()
            raise UpdaterHTTPError(status, "Updater endpoint returnerede ikke success")
        return response

    def _json_request(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        access_token: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any] | None:
        url = self._url(path)
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "ClientFlow-Stable-Updater/51D",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if access_token is not None:
            headers["Authorization"] = f"DPoP {access_token}"
        headers["DPoP"] = build_dpop_proof(
            self.config.private_key,
            method=method,
            url=url,
            access_token=access_token,
        )
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        with self._open(request, timeout=timeout) as response:
            raw = response.read(MAX_JSON_RESPONSE_BYTES + 1)
        if len(raw) > MAX_JSON_RESPONSE_BYTES:
            raise UpdaterTransportError("Updater JSON-respons er for stor")
        if not raw and method == "GET":
            return None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdaterTransportError("Updater endpoint returnerede ugyldig JSON") from exc
        if value is None:
            return None
        if not isinstance(value, dict):
            raise UpdaterTransportError("Updater JSON-respons skal være et objekt eller null")
        return value

    def issue_access_token(self) -> str:
        path = "/api/clientflow-update/token"
        url = self._url(path)
        assertion = build_client_assertion(
            self.config.private_key,
            credential_id=self.config.credential_id,
            key_id=self.config.key_id,
        )
        payload = {
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "client_assertion": assertion,
            "scope": " ".join(sorted(UPDATE_SCOPES)),
        }
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "ClientFlow-Stable-Updater/51D",
                "DPoP": build_dpop_proof(self.config.private_key, method="POST", url=url),
            },
        )
        with self._open(request, timeout=30) as response:
            raw = response.read(MAX_JSON_RESPONSE_BYTES + 1)
        if len(raw) > MAX_JSON_RESPONSE_BYTES:
            raise UpdaterTransportError("Update token-respons er for stor")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdaterTransportError("Update token-respons er ugyldig JSON") from exc
        if not isinstance(value, dict):
            raise UpdaterTransportError("Update token-respons skal være et objekt")
        token = str(value.get("access_token") or "").strip()
        token_type = str(value.get("token_type") or "")
        scopes = frozenset(str(value.get("scope") or "").split())
        try:
            expires_in = int(value.get("expires_in"))
        except (TypeError, ValueError) as exc:
            raise UpdaterTransportError("Update token-respons har ugyldig expires_in") from exc
        if not token or token_type.lower() != "dpop" or expires_in <= 0:
            raise UpdaterTransportError("Update token-respons er ugyldig")
        if scopes != UPDATE_SCOPES:
            raise UpdaterTransportError("Update access-token scopes matcher ikke den krævede least-privilege request")
        return token

    def get_active_deployment(self, access_token: str) -> dict[str, Any] | None:
        return self._json_request(
            method="GET",
            path="/api/clientflow-update/deployments/active",
            access_token=access_token,
        )

    def report_event(self, access_token: str, event: dict[str, Any]) -> dict[str, Any]:
        deployment_id = str(event["deployment_id"])
        response = self._json_request(
            method="POST",
            path=f"/api/clientflow-update/deployments/{deployment_id}/events",
            access_token=access_token,
            payload={
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "occurred_at": event["occurred_at"],
                "payload": event["payload"],
            },
        )
        if not isinstance(response, dict) or not isinstance(response.get("deployment"), dict):
            raise UpdaterTransportError("Deployment event-respons mangler deployment")
        return response

    def authorize_artifact(
        self,
        access_token: str,
        snapshot: DeploymentSnapshot,
    ) -> dict[str, Any]:
        response = self._json_request(
            method="POST",
            path=f"/api/clientflow-update/deployments/{snapshot.deployment_id}/artifact-authorization",
            access_token=access_token,
            payload=None,
        )
        if not isinstance(response, dict):
            raise UpdaterTransportError("Artifact authorization-respons mangler")
        try:
            bundle_size = int(response.get("bundle_size"))
        except (TypeError, ValueError) as exc:
            raise UpdaterTransportError("Artifact authorization bundle_size er ugyldig") from exc
        expected_path = f"/api/clientflow/release-artifacts/{snapshot.target_release_id}"
        try:
            expires_in = int(response.get("expires_in"))
        except (TypeError, ValueError) as exc:
            raise UpdaterTransportError("Artifact authorization expires_in er ugyldig") from exc
        if (
            str(response.get("token_type") or "").lower() != "dpop"
            or expires_in <= 0
            or not str(response.get("access_token") or "").strip()
            or str(response.get("release_id") or "") != snapshot.target_release_id
            or str(response.get("bundle_sha256") or "").lower() != snapshot.bundle_sha256
            or bundle_size != snapshot.bundle_size
            or str(response.get("artifact_url") or "") != expected_path
        ):
            raise UpdaterTransportError("Artifact authorization matcher ikke deployment snapshot")
        return response

    def download_artifact(
        self,
        authorization: dict[str, Any],
        snapshot: DeploymentSnapshot,
        destination: BinaryIO,
    ) -> tuple[int, str]:
        path = str(authorization["artifact_url"])
        expected_path = f"/api/clientflow/release-artifacts/{snapshot.target_release_id}"
        if path != expected_path:
            raise UpdaterTransportError("Artifact URL matcher ikke deployment snapshot")
        url = self._url(path)
        artifact_token = str(authorization["access_token"])
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/octet-stream",
                "Authorization": f"DPoP {artifact_token}",
                "DPoP": build_dpop_proof(
                    self.config.private_key,
                    method="GET",
                    url=url,
                    access_token=artifact_token,
                ),
                "User-Agent": "ClientFlow-Stable-Updater/51D",
            },
        )
        digest = hashlib.sha256()
        observed_size = 0
        try:
            with self._open(request, timeout=120) as response:
                raw_length = str(response.headers.get("Content-Length") or "").strip()
                if raw_length:
                    try:
                        if int(raw_length) != snapshot.bundle_size:
                            raise UpdaterStateError("Artifact Content-Length matcher ikke deployment snapshot")
                    except ValueError as exc:
                        raise UpdaterStateError("Artifact Content-Length er ugyldig") from exc
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    observed_size += len(chunk)
                    if observed_size > snapshot.bundle_size:
                        raise UpdaterStateError("Artifact-download overskrider autoriseret bundle_size")
                    destination.write(chunk)
                    digest.update(chunk)
            destination.flush()
            fileno = destination.fileno()
            import os
            os.fsync(fileno)
        except Exception:
            raise
        return observed_size, digest.hexdigest()
