from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import BinaryIO

from clientflow_release_format.bundle import (
    BundleFormatError,
    open_verified_bundle_structure,
)
from clientflow_release_format.constants import MAX_BUNDLE_BYTES
from clientflow_release_format.crypto import sha256_fd

from .archive import safe_extract_payload
from .runtime_artifacts import validate_runtime_artifacts


class BundleError(RuntimeError):
    pass


def open_verified_bundle(
    bundle: Path,
    *,
    require_deployable: bool = True,
    required_install_mode: str | None = None,
) -> tuple[dict, bytes, int, str, BinaryIO]:
    """Verify one concrete bundle identity and keep those exact bytes open.

    The returned handle remains pinned to the same regular-file inode that
    supplied the manifest, payload, whole-bundle SHA-256 and runtime-artifact
    validation. Callers that must stream/copy the verified artifact can do so
    without reopening a mutable pathname.
    """
    handle: BinaryIO | None = None
    try:
        validated, payload, size, bundle_sha256, handle = open_verified_bundle_structure(
            bundle,
            require_deployable=require_deployable,
            required_install_mode=required_install_mode,
        )
        if require_deployable:
            validate_runtime_artifacts(payload, validated)

        final_size, final_sha256 = sha256_fd(handle.fileno(), max_bytes=MAX_BUNDLE_BYTES)
        if (final_size, final_sha256) != (size, bundle_sha256):
            raise BundleError("Releasebundlen ændrede sig under runtime-artifact-verifikation")
        os.lseek(handle.fileno(), 0, os.SEEK_SET)
        return validated, payload, size, bundle_sha256, handle
    except (BundleFormatError, ValueError, OSError) as exc:
        if handle is not None:
            handle.close()
        raise BundleError(str(exc)) from exc
    except Exception:
        if handle is not None:
            handle.close()
        raise


def verify_bundle(
    bundle: Path,
    *,
    require_deployable: bool = True,
    required_install_mode: str | None = None,
) -> tuple[dict, bytes]:
    """Canonical structural/hash verification plus client runtime-artifact validation."""
    validated, payload, _size, _sha256, handle = open_verified_bundle(
        bundle,
        require_deployable=require_deployable,
        required_install_mode=required_install_mode,
    )
    handle.close()
    return validated, payload


def extract_verified_payload(payload: bytes, destination: Path, *, expected_root: str) -> Path:
    with tempfile.NamedTemporaryFile(prefix="clientflow-payload-", suffix=".tar", delete=False) as temporary:
        temporary.write(payload)
        temporary.flush()
        path = Path(temporary.name)
    try:
        return safe_extract_payload(path, destination, expected_root=expected_root)
    finally:
        path.unlink(missing_ok=True)
