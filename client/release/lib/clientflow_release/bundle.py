from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from clientflow_release_format.archive import FileRegion
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
) -> tuple[dict, FileRegion, int, str, BinaryIO]:
    """Deep-verify one bundle while retaining bounded access to its pinned payload."""
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
) -> tuple[dict, int, str]:
    """Canonical deep verification without returning payload-sized memory."""
    validated, _payload, size, digest, handle = open_verified_bundle(
        bundle,
        require_deployable=require_deployable,
        required_install_mode=required_install_mode,
    )
    handle.close()
    return validated, size, digest


def extract_verified_payload(payload: FileRegion, destination: Path, *, expected_root: str) -> Path:
    return safe_extract_payload(payload, destination, expected_root=expected_root)
