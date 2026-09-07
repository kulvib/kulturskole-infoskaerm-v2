"""Durable local state for the stable updater download/verification boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, BinaryIO
import uuid

from .filesystem import ensure_real_directory, fsync_directory

STATE_SCHEMA_VERSION = 1
MAX_STATE_BYTES = 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdaterStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeploymentSnapshot:
    deployment_id: str
    target_release_id: str
    target_version: str
    target_release_sequence: int
    bundle_sha256: str
    bundle_size: int
    release_approval_reference: str
    release_candidate_sha256: str | None
    source_commit: str | None

    @classmethod
    def from_backend(cls, value: dict[str, Any]) -> "DeploymentSnapshot":
        if not isinstance(value, dict):
            raise UpdaterStateError("Deployment snapshot skal være et objekt")
        try:
            deployment_id = str(uuid.UUID(str(value.get("id") or "")))
            release_sequence = int(value.get("target_release_sequence"))
            bundle_size = int(value.get("bundle_size"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise UpdaterStateError("Deployment snapshot identity er ugyldig") from exc
        target_release_id = str(value.get("target_release_id") or "").strip()
        target_version = str(value.get("target_version") or "").strip()
        bundle_sha256 = str(value.get("bundle_sha256") or "").strip().lower()
        approval_reference = str(value.get("release_approval_reference") or "").strip()
        release_candidate_sha256 = str(value.get("release_candidate_sha256") or "").strip().lower() or None
        source_commit = str(value.get("source_commit") or "").strip() or None
        if not target_release_id or len(target_release_id) > 160:
            raise UpdaterStateError("Deployment target_release_id er ugyldig")
        if not target_version or len(target_version) > 40 or release_sequence <= 0:
            raise UpdaterStateError("Deployment release-version/sequence er ugyldig")
        if not _SHA256_RE.fullmatch(bundle_sha256) or bundle_size <= 0:
            raise UpdaterStateError("Deployment bundle identity er ugyldig")
        if not approval_reference or len(approval_reference) > 200:
            raise UpdaterStateError("Deployment approval reference er ugyldig")
        if release_candidate_sha256 is not None and not _SHA256_RE.fullmatch(release_candidate_sha256):
            raise UpdaterStateError("Deployment release candidate SHA-256 er ugyldig")
        if source_commit is not None and len(source_commit) > 64:
            raise UpdaterStateError("Deployment source commit er ugyldig")
        return cls(
            deployment_id=deployment_id,
            target_release_id=target_release_id,
            target_version=target_version,
            target_release_sequence=release_sequence,
            bundle_sha256=bundle_sha256,
            bundle_size=bundle_size,
            release_approval_reference=approval_reference,
            release_candidate_sha256=release_candidate_sha256,
            source_commit=source_commit,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "target_release_id": self.target_release_id,
            "target_version": self.target_version,
            "target_release_sequence": self.target_release_sequence,
            "bundle_sha256": self.bundle_sha256,
            "bundle_size": self.bundle_size,
            "release_approval_reference": self.release_approval_reference,
            "release_candidate_sha256": self.release_candidate_sha256,
            "source_commit": self.source_commit,
        }

    @classmethod
    def from_state(cls, value: dict[str, Any]) -> "DeploymentSnapshot":
        translated = dict(value)
        translated["id"] = translated.pop("deployment_id", None)
        return cls.from_backend(translated)


class UpdaterStateStore:
    def __init__(self, state_root: Path):
        self.state_root = Path(state_root)
        self.artifact_root = self.state_root / "artifacts"
        self.state_path = self.state_root / "state.json"
        ensure_real_directory(self.state_root, mode=0o700)
        ensure_real_directory(self.artifact_root, mode=0o700)
        self._cleanup_orphan_partials()
        self._state = self._load()

    def _cleanup_orphan_partials(self) -> None:
        removed = False
        for path in self.artifact_root.iterdir():
            if path.name.startswith(".") and path.name.endswith(".part"):
                path.unlink(missing_ok=True)
                removed = True
        if removed:
            fsync_directory(self.artifact_root)

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "deployment": None,
            "pending_event": None,
            "artifact": None,
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._empty()
        descriptor = os.open(self.state_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise UpdaterStateError("Updater statefil har usikre rettigheder")
            if metadata.st_size > MAX_STATE_BYTES:
                raise UpdaterStateError("Updater statefil er for stor")
            raw = os.read(descriptor, MAX_STATE_BYTES + 1)
        finally:
            os.close(descriptor)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdaterStateError("Updater statefil er ugyldig JSON") from exc
        if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
            raise UpdaterStateError("Updater state schema er ugyldig")
        deployment = value.get("deployment")
        if deployment is not None:
            DeploymentSnapshot.from_state(deployment)
        pending = value.get("pending_event")
        if pending is not None:
            self._validate_pending_event(pending)
        artifact = value.get("artifact")
        if artifact is not None:
            self._validate_artifact_record(artifact)
        return value

    def _save(self) -> None:
        raw = (json.dumps(self._state, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(raw) > MAX_STATE_BYTES:
            raise UpdaterStateError("Updater state overskrider maksimumstørrelsen")
        descriptor, temporary = tempfile.mkstemp(prefix=".state.json.", dir=self.state_root)
        temporary_path = Path(temporary)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.state_path)
            fsync_directory(self.state_root)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_pending_event(value: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            raise UpdaterStateError("Pending updater-event er ugyldig")
        try:
            uuid.UUID(str(value.get("deployment_id") or ""))
            uuid.UUID(str(value.get("event_id") or ""))
        except (ValueError, AttributeError) as exc:
            raise UpdaterStateError("Pending updater-event identity er ugyldig") from exc
        if str(value.get("event_type") or "") not in {"download_started", "bundle_verified"}:
            raise UpdaterStateError("Pending updater-event type er ugyldig")
        if not isinstance(value.get("payload"), dict) or not str(value.get("occurred_at") or ""):
            raise UpdaterStateError("Pending updater-event payload/timestamp er ugyldig")

    @staticmethod
    def _validate_artifact_record(value: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            raise UpdaterStateError("Updater artifact-state er ugyldig")
        try:
            uuid.UUID(str(value.get("deployment_id") or ""))
        except (ValueError, AttributeError) as exc:
            raise UpdaterStateError("Updater artifact deployment_id er ugyldig") from exc
        sha256 = str(value.get("bundle_sha256") or "")
        if not _SHA256_RE.fullmatch(sha256):
            raise UpdaterStateError("Updater artifact SHA-256 er ugyldig")
        try:
            size = int(value.get("bundle_size"))
        except (TypeError, ValueError) as exc:
            raise UpdaterStateError("Updater artifact size er ugyldig") from exc
        if size <= 0 or Path(str(value.get("filename") or "")).name != str(value.get("filename") or ""):
            raise UpdaterStateError("Updater artifact record er ugyldig")

    @property
    def snapshot(self) -> DeploymentSnapshot | None:
        value = self._state.get("deployment")
        return DeploymentSnapshot.from_state(value) if isinstance(value, dict) else None

    @property
    def pending_event(self) -> dict[str, Any] | None:
        value = self._state.get("pending_event")
        return dict(value) if isinstance(value, dict) else None

    def bind_deployment(self, deployment: dict[str, Any]) -> DeploymentSnapshot:
        snapshot = DeploymentSnapshot.from_backend(deployment)
        current = self.snapshot
        if current is not None and current.deployment_id == snapshot.deployment_id:
            if current != snapshot:
                raise UpdaterStateError("Backend ændrede et immutable deployment snapshot")
            return current
        self._remove_artifact_file()
        self._state = self._empty()
        self._state["deployment"] = snapshot.to_dict()
        self._save()
        return snapshot

    def clear_inactive(self) -> None:
        self._remove_artifact_file()
        self._state = self._empty()
        self._save()

    def ensure_pending_event(
        self,
        *,
        deployment_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.pending_event
        normalized_payload = dict(payload or {})
        if existing is not None:
            if (
                existing["deployment_id"] == deployment_id
                and existing["event_type"] == event_type
                and existing["payload"] == normalized_payload
            ):
                return existing
            raise UpdaterStateError("Et andet updater-event afventer stadig backend-ack")
        event = {
            "deployment_id": str(uuid.UUID(deployment_id)),
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": normalized_payload,
        }
        self._validate_pending_event(event)
        self._state["pending_event"] = event
        self._save()
        return dict(event)

    def acknowledge_event(self, event_id: str) -> None:
        existing = self.pending_event
        if existing is None or existing["event_id"] != str(uuid.UUID(event_id)):
            raise UpdaterStateError("Updater-event ack matcher ikke pending event")
        self._state["pending_event"] = None
        self._save()

    def artifact_path(self, snapshot: DeploymentSnapshot) -> Path:
        filename = f"{snapshot.deployment_id}-{snapshot.bundle_sha256}.tar"
        return self.artifact_root / filename

    def _remove_artifact_file(self) -> None:
        record = self._state.get("artifact") if hasattr(self, "_state") else None
        if isinstance(record, dict):
            filename = str(record.get("filename") or "")
            if Path(filename).name == filename:
                (self.artifact_root / filename).unlink(missing_ok=True)
                fsync_directory(self.artifact_root)
        self._state["artifact"] = None if hasattr(self, "_state") else None

    def discard_artifact(self) -> None:
        self._remove_artifact_file()
        self._save()

    @staticmethod
    def _hash_open_file(handle: BinaryIO, *, expected_size: int) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = handle.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > expected_size:
                raise UpdaterStateError("Artifact-download overskrider autoriseret bundle_size")
            digest.update(chunk)
        return size, digest.hexdigest()

    def verify_local_artifact(self, snapshot: DeploymentSnapshot) -> Path | None:
        expected = {
            "deployment_id": snapshot.deployment_id,
            "bundle_sha256": snapshot.bundle_sha256,
            "bundle_size": snapshot.bundle_size,
            "filename": self.artifact_path(snapshot).name,
        }
        record = self._state.get("artifact")
        if isinstance(record, dict):
            self._validate_artifact_record(record)
            if any(record.get(key) != value for key, value in expected.items()):
                self.discard_artifact()
                return None
        else:
            # Crash recovery: atomic publication may have completed immediately
            # before state.json was fsynced.  The deterministic filename is not
            # trusted until the exact deployment hash/size is reverified below.
            record = dict(expected)
        path = self.artifact_root / str(record["filename"])
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            self.discard_artifact()
            return None
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size != snapshot.bundle_size:
                self.discard_artifact()
                return None
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                size, sha256 = self._hash_open_file(handle, expected_size=snapshot.bundle_size)
            after = os.fstat(descriptor)
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            if identity_before != identity_after or size != snapshot.bundle_size or sha256 != snapshot.bundle_sha256:
                self.discard_artifact()
                return None
        finally:
            os.close(descriptor)
        if self._state.get("artifact") != expected:
            self._state["artifact"] = dict(expected)
            self._save()
        return path

    def begin_download(self, snapshot: DeploymentSnapshot) -> tuple[Path, BinaryIO]:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{snapshot.deployment_id}.",
            suffix=".part",
            dir=self.artifact_root,
        )
        os.fchmod(descriptor, 0o600)
        return Path(temporary), os.fdopen(descriptor, "wb", closefd=True)

    def commit_download(
        self,
        snapshot: DeploymentSnapshot,
        temporary: Path,
        *,
        observed_size: int,
        observed_sha256: str,
    ) -> Path:
        if observed_size != snapshot.bundle_size or observed_sha256 != snapshot.bundle_sha256:
            Path(temporary).unlink(missing_ok=True)
            raise UpdaterStateError("Downloaded artifact matcher ikke deployment snapshot")
        destination = self.artifact_path(snapshot)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        fsync_directory(self.artifact_root)
        self._state["artifact"] = {
            "deployment_id": snapshot.deployment_id,
            "bundle_sha256": snapshot.bundle_sha256,
            "bundle_size": snapshot.bundle_size,
            "filename": destination.name,
        }
        self._save()
        verified = self.verify_local_artifact(snapshot)
        if verified is None:
            raise UpdaterStateError("Artifact kunne ikke genverificeres efter atomic publication")
        return verified
