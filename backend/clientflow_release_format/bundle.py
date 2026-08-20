from __future__ import annotations

import hashlib
from pathlib import Path
import tarfile
import tempfile

from .archive import ArchiveError, inspect_payload_tar, read_bundle
from .constants import MAX_BUNDLE_BYTES
from .crypto import sha256_file
from .manifest import validate_manifest


class BundleFormatError(RuntimeError):
    pass


def verify_bundle_structure(
    bundle: Path,
    *,
    require_deployable: bool = True,
    required_install_mode: str | None = None,
) -> tuple[dict, bytes, int, str]:
    """Verify immutable bundle bytes and canonical manifest/archive structure."""
    try:
        size, bundle_sha256 = sha256_file(bundle, max_bytes=MAX_BUNDLE_BYTES)
        if size <= 0:
            raise BundleFormatError("Releasebundlen er tom")
        manifest, payload = read_bundle(bundle)
        validated = validate_manifest(
            manifest,
            require_deployable=require_deployable,
            required_install_mode=required_install_mode,
        )
        expected_size = int(validated["payload"]["size"])
        expected_sha = str(validated["payload"]["sha256"])
        if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_sha:
            raise BundleFormatError("Payloadens størrelse eller SHA-256 matcher ikke manifestet")
        with tempfile.NamedTemporaryFile(prefix="clientflow-payload-", suffix=".tar") as temporary:
            temporary.write(payload)
            temporary.flush()
            inspect_payload_tar(Path(temporary.name), expected_root=str(validated["payload"]["root"]))
        return validated, payload, size, bundle_sha256
    except (ArchiveError, ValueError, OSError, tarfile.TarError) as exc:
        if isinstance(exc, BundleFormatError):
            raise
        raise BundleFormatError(str(exc)) from exc
