"""Resolve the single manually maintained ClientFlow version from repository/install data."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path


_DISTRIBUTION_NAME = "clientflow-runtime"


def _valid_version(value: str) -> bool:
    return value.count(".") == 2 and all(part.isdigit() for part in value.split("."))


def _candidate_paths() -> tuple[Path, ...]:
    source_root = Path(__file__).resolve().parents[3]
    return (
        source_root / "VERSION",
        Path("/opt/clientflow/active/VERSION"),
        Path("/usr/lib/clientflow/VERSION"),
    )


def _installed_distribution_version() -> str | None:
    try:
        value = distribution_version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return None
    return value if _valid_version(value) else None


def _load_version() -> str:
    for path in _candidate_paths():
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if _valid_version(value):
            return value
    installed_version = _installed_distribution_version()
    if installed_version is not None:
        return installed_version
    raise RuntimeError("ClientFlow VERSION kunne ikke findes eller er ugyldig")


VERSION = _load_version()
