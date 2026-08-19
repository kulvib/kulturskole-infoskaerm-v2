from __future__ import annotations

import hashlib
from pathlib import Path
import tarfile
import tempfile

from .archive import ArchiveError, inspect_payload_tar, read_bundle, safe_extract_payload
from .constants import MAX_BUNDLE_BYTES
from .crypto import sha256_file
from .manifest import validate_manifest
from .runtime_artifacts import validate_runtime_artifacts


class BundleError(RuntimeError):
    pass


def verify_bundle(bundle: Path, *, require_deployable: bool = True) -> tuple[dict, bytes]:
    """Fail-closed structural and SHA-256 verification without a release signing key."""
    try:
        size, _ = sha256_file(bundle, max_bytes=MAX_BUNDLE_BYTES)
        if size <= 0:
            raise BundleError("Releasebundlen er tom")
        manifest, payload = read_bundle(bundle)
        validated = validate_manifest(manifest, require_deployable=require_deployable)
        expected_size = int(validated["payload"]["size"])
        expected_sha = str(validated["payload"]["sha256"])
        if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_sha:
            raise BundleError("Payloadens størrelse eller SHA-256 matcher ikke manifestet")
        if require_deployable:
            validate_runtime_artifacts(payload, validated)
        with tempfile.NamedTemporaryFile(prefix="clientflow-payload-", suffix=".tar") as temporary:
            temporary.write(payload)
            temporary.flush()
            inspect_payload_tar(Path(temporary.name), expected_root=str(validated["payload"]["root"]))
        return validated, payload
    except (ArchiveError, ValueError, OSError, tarfile.TarError) as exc:
        if isinstance(exc, BundleError):
            raise
        raise BundleError(str(exc)) from exc


def extract_verified_payload(payload: bytes, destination: Path, *, expected_root: str) -> Path:
    with tempfile.NamedTemporaryFile(prefix="clientflow-payload-", suffix=".tar", delete=False) as temporary:
        temporary.write(payload)
        temporary.flush()
        path = Path(temporary.name)
    try:
        return safe_extract_payload(path, destination, expected_root=expected_root)
    finally:
        path.unlink(missing_ok=True)
