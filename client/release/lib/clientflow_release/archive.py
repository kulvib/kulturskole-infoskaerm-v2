from __future__ import annotations

from pathlib import Path
import stat
import tarfile

from clientflow_release_format.archive import (
    ArchiveError,
    ArchiveLimits,
    inspect_payload_tar,
    read_bundle,
    validate_member_name,
)


def safe_extract_payload(path: Path, destination: Path, *, expected_root: str) -> Path:
    if destination.exists():
        raise ArchiveError("Ekstraktionsmålet findes allerede")
    destination.mkdir(mode=0o700, parents=True)
    inspect_payload_tar(path, expected_root=expected_root)
    with tarfile.open(path, mode="r:") as archive:
        archive.extractall(destination, filter="data")
    root = destination / expected_root
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArchiveError("Payload-root blev ikke ekstraheret som katalog")
    return root


__all__ = [
    "ArchiveError",
    "ArchiveLimits",
    "inspect_payload_tar",
    "read_bundle",
    "safe_extract_payload",
    "validate_member_name",
]
