"""Resolve ClientFlow runtime version from one canonical product version authority."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path


_DISTRIBUTION_NAME = "clientflow-runtime"


def _valid_version(value: str) -> bool:
    return value.count(".") == 2 and all(part.isdigit() for part in value.split("."))


def _source_version() -> str | None:
    """Read client/VERSION only when running from the canonical source-tree layout."""
    package_root = Path(__file__).resolve().parent
    runtime_root = package_root.parent
    client_root = runtime_root.parent
    if package_root.name != "clientflow_runtime" or runtime_root.name != "runtime":
        return None
    path = client_root / "VERSION"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if _valid_version(value) else None


def _installed_distribution_version() -> str | None:
    try:
        value = distribution_version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return None
    return value if _valid_version(value) else None


def _load_version() -> str:
    # Source/build context must be bound to client/VERSION. Installed runtime
    # must report the version encoded in its own wheel metadata, not whatever
    # release happens to be pointed to by /opt/clientflow/active.
    source_version = _source_version()
    if source_version is not None:
        return source_version
    installed_version = _installed_distribution_version()
    if installed_version is not None:
        return installed_version
    raise RuntimeError("ClientFlow runtime-version kunne ikke bestemmes")


VERSION = _load_version()
