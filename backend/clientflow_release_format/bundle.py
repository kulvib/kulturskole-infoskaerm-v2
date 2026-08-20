from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tarfile
import tempfile
from typing import BinaryIO

from .archive import ArchiveError, inspect_payload_tar, read_bundle_fd
from .constants import MAX_BUNDLE_BYTES
from .crypto import sha256_fd
from .manifest import validate_manifest


class BundleFormatError(RuntimeError):
    pass


def open_verified_bundle_structure(
    bundle: Path,
    *,
    require_deployable: bool = True,
    required_install_mode: str | None = None,
) -> tuple[dict, bytes, int, str, BinaryIO]:
    """Verify one opened bundle identity and return a handle to those exact bytes."""
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = -1
    try:
        descriptor = os.open(bundle, flags)
        size, bundle_sha256 = sha256_fd(descriptor, max_bytes=MAX_BUNDLE_BYTES)
        if size <= 0:
            raise BundleFormatError("Releasebundlen er tom")
        manifest, payload = read_bundle_fd(descriptor)
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
        # Hash once more after structural parsing so the manifest/payload and
        # the returned immutable identity are proven against the same open inode.
        final_size, final_sha256 = sha256_fd(descriptor, max_bytes=MAX_BUNDLE_BYTES)
        if (final_size, final_sha256) != (size, bundle_sha256):
            raise BundleFormatError("Releasebundlen ændrede bytes under verifikation")
        os.lseek(descriptor, 0, os.SEEK_SET)
        handle = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        return validated, payload, size, bundle_sha256, handle
    except (ArchiveError, ValueError, OSError, tarfile.TarError) as exc:
        if isinstance(exc, BundleFormatError):
            raise
        raise BundleFormatError(str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def verify_bundle_structure(
    bundle: Path,
    *,
    require_deployable: bool = True,
    required_install_mode: str | None = None,
) -> tuple[dict, bytes, int, str]:
    """Verify immutable bundle bytes and canonical manifest/archive structure."""
    validated, payload, size, bundle_sha256, handle = open_verified_bundle_structure(
        bundle,
        require_deployable=require_deployable,
        required_install_mode=required_install_mode,
    )
    handle.close()
    return validated, payload, size, bundle_sha256
