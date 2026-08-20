from __future__ import annotations

from pathlib import Path
import tempfile

from clientflow_release_format.bundle import BundleFormatError, verify_bundle_structure

from .archive import safe_extract_payload
from .runtime_artifacts import validate_runtime_artifacts


class BundleError(RuntimeError):
    pass


def verify_bundle(
    bundle: Path,
    *,
    require_deployable: bool = True,
    required_install_mode: str | None = None,
) -> tuple[dict, bytes]:
    """Canonical structural/hash verification plus client runtime-artifact validation."""
    try:
        validated, payload, _size, _sha256 = verify_bundle_structure(
            bundle,
            require_deployable=require_deployable,
            required_install_mode=required_install_mode,
        )
        if require_deployable:
            validate_runtime_artifacts(payload, validated)
        return validated, payload
    except (BundleFormatError, ValueError, OSError) as exc:
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
