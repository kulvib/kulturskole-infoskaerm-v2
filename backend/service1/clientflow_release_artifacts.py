"""Backend authority over published, approved ClientFlow release artifacts.

The catalog describes release policy.  The exact deployable bytes are derived
from one immutable approved bundle in CLIENTFLOW_RELEASE_ARTIFACT_DIR and are
re-verified before deployment authorization and before download.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Any

from clientflow_release_format.bundle import BundleFormatError, verify_bundle_structure
from clientflow_release_format.constants import INSTALL_MODE_UPDATE, MAX_BUNDLE_BYTES

_RELEASE_ID_RE = re.compile(r"^clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*$")


class ClientFlowReleaseArtifactError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublishedReleaseArtifact:
    path: Path
    release_id: str
    version: str
    release_sequence: int
    bundle_size: int
    bundle_sha256: str
    approval_reference: str
    candidate_sha256: str
    source_commit: str
    manifest: dict[str, Any]


def _artifact_root() -> Path:
    raw = str(os.getenv("CLIENTFLOW_RELEASE_ARTIFACT_DIR") or "").strip()
    if not raw:
        raise ClientFlowReleaseArtifactError("CLIENTFLOW_RELEASE_ARTIFACT_DIR er ikke konfigureret")
    root = Path(raw)
    if not root.is_absolute():
        raise ClientFlowReleaseArtifactError("CLIENTFLOW_RELEASE_ARTIFACT_DIR skal være en absolut sti")
    try:
        metadata = root.lstat()
    except FileNotFoundError as exc:
        raise ClientFlowReleaseArtifactError("ClientFlow artifact-kataloget findes ikke") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ClientFlowReleaseArtifactError("ClientFlow artifact-kataloget skal være et rigtigt katalog")
    if metadata.st_mode & 0o022:
        raise ClientFlowReleaseArtifactError("ClientFlow artifact-kataloget må ikke være gruppe-/verdensskrivbart")
    allowed_owners = {0, os.geteuid()}
    if hasattr(metadata, "st_uid") and metadata.st_uid not in allowed_owners:
        raise ClientFlowReleaseArtifactError("ClientFlow artifact-kataloget har uventet ejer")
    return root


def _release_id(release: dict[str, Any]) -> str:
    release_id = str(release.get("release_id") or release.get("revision") or "").strip()
    if not _RELEASE_ID_RE.fullmatch(release_id):
        raise ClientFlowReleaseArtifactError("Releasekataloget mangler et gyldigt release_id")
    return release_id


def _artifact_path(release_id: str) -> Path:
    root = _artifact_root()
    path = root / f"{release_id}.tar"
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ClientFlowReleaseArtifactError(f"Godkendt artifact mangler for {release_id}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ClientFlowReleaseArtifactError("Publiceret ClientFlow artifact skal være en almindelig fil")
    if metadata.st_mode & 0o022:
        raise ClientFlowReleaseArtifactError("Publiceret ClientFlow artifact må ikke være gruppe-/verdensskrivbart")
    allowed_owners = {0, os.geteuid()}
    if hasattr(metadata, "st_uid") and metadata.st_uid not in allowed_owners:
        raise ClientFlowReleaseArtifactError("Publiceret ClientFlow artifact har uventet ejer")
    if not 1 <= metadata.st_size <= MAX_BUNDLE_BYTES:
        raise ClientFlowReleaseArtifactError("Publiceret ClientFlow artifact har ugyldig størrelse")
    return path


def inspect_published_release_artifact(release: dict[str, Any]) -> PublishedReleaseArtifact:
    release_id = _release_id(release)
    path = _artifact_path(release_id)
    try:
        manifest, _payload, bundle_size, bundle_sha256 = verify_bundle_structure(
            path,
            require_deployable=True,
            required_install_mode=INSTALL_MODE_UPDATE,
        )
    except BundleFormatError as exc:
        raise ClientFlowReleaseArtifactError(f"Publiceret ClientFlow artifact er ugyldigt: {exc}") from exc

    version = str(release.get("version") or "").strip()
    try:
        release_sequence = int(release.get("release_sequence"))
    except (TypeError, ValueError) as exc:
        raise ClientFlowReleaseArtifactError("Releasekatalogets release_sequence er ugyldig") from exc
    if manifest.get("release_id") != release_id:
        raise ClientFlowReleaseArtifactError("Artifactets release_id matcher ikke releasekataloget")
    if manifest.get("version") != version:
        raise ClientFlowReleaseArtifactError("Artifactets version matcher ikke releasekataloget")
    if int(manifest.get("release_sequence") or 0) != release_sequence:
        raise ClientFlowReleaseArtifactError("Artifactets release_sequence matcher ikke releasekataloget")

    approval = manifest.get("release_approval") or {}
    source = manifest.get("source") or {}
    return PublishedReleaseArtifact(
        path=path,
        release_id=release_id,
        version=version,
        release_sequence=release_sequence,
        bundle_size=bundle_size,
        bundle_sha256=bundle_sha256,
        approval_reference=str(approval["reference"]),
        candidate_sha256=str(approval["candidate_sha256"]),
        source_commit=str(source["commit"]),
        manifest=manifest,
    )


def verify_artifact_matches_deployment(
    release: dict[str, Any],
    *,
    deployment_release_id: str,
    bundle_sha256: str,
    bundle_size: int,
    approval_reference: str,
) -> PublishedReleaseArtifact:
    artifact = inspect_published_release_artifact(release)
    expected = (
        deployment_release_id,
        str(bundle_sha256).lower(),
        int(bundle_size),
        str(approval_reference),
    )
    actual = (
        artifact.release_id,
        artifact.bundle_sha256,
        artifact.bundle_size,
        artifact.approval_reference,
    )
    if actual != expected:
        raise ClientFlowReleaseArtifactError("Publiceret artifact matcher ikke deploymentens immutable authorization")
    return artifact
