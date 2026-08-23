from __future__ import annotations

import os
from pathlib import Path
import tarfile
from typing import BinaryIO

from .archive import (
    ArchiveError,
    FileRegion,
    inspect_payload_region,
    read_bundle_artifact_regions_fd,
)
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
) -> tuple[dict, FileRegion, int, str, BinaryIO]:
    """Verify one pinned bundle structure with bounded memory.

    The payload is returned as a byte-range capability into the same open inode,
    never as a materialized bytes object. The returned handle owns that inode
    lifetime; callers must keep it open while using the payload region.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = -1
    try:
        descriptor = os.open(bundle, flags)
        size, bundle_sha256 = sha256_fd(descriptor, max_bytes=MAX_BUNDLE_BYTES)
        if size <= 0:
            raise BundleFormatError("Releasebundlen er tom")

        manifest, payload, installer = read_bundle_artifact_regions_fd(descriptor)
        validated = validate_manifest(
            manifest,
            require_deployable=require_deployable,
            required_install_mode=required_install_mode,
        )

        installer_contract = validated["fresh_installer"]
        if installer.size != int(installer_contract["size"]):
            raise BundleFormatError("Fresh installerens størrelse eller SHA-256 matcher ikke manifestet")
        if installer.sha256() != str(installer_contract["sha256"]):
            raise BundleFormatError("Fresh installerens størrelse eller SHA-256 matcher ikke manifestet")

        payload_contract = validated["payload"]
        if payload.size != int(payload_contract["size"]):
            raise BundleFormatError("Payloadens størrelse eller SHA-256 matcher ikke manifestet")
        if payload.sha256() != str(payload_contract["sha256"]):
            raise BundleFormatError("Payloadens størrelse eller SHA-256 matcher ikke manifestet")
        inspect_payload_region(payload, expected_root=str(payload_contract["root"]))

        # Re-hash after member parsing so all returned provenance is tied to the
        # same still-open inode and an in-place mutation fails closed.
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
) -> tuple[dict, int, str]:
    """Verify immutable bundle identity and outer/payload archive structure."""
    validated, _payload, size, bundle_sha256, handle = open_verified_bundle_structure(
        bundle,
        require_deployable=require_deployable,
        required_install_mode=required_install_mode,
    )
    handle.close()
    return validated, size, bundle_sha256
