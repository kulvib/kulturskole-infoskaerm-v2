from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def sha256_fd(descriptor: int, *, max_bytes: int | None = None) -> tuple[int, str]:
    """Hash one already-open regular file and reject in-place mutation."""
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Filen er ikke en almindelig fil")
    if max_bytes is not None and metadata.st_size > max_bytes:
        raise ValueError("Filen er større end tilladt")
    digest = hashlib.sha256()
    size = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise ValueError("Filen er større end tilladt")
        digest.update(chunk)
    after = os.fstat(descriptor)
    if size != metadata.st_size or _stat_signature(after) != _stat_signature(metadata):
        raise ValueError("Filen ændrede sig under hashing")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return size, digest.hexdigest()


def sha256_file(path: Path, *, max_bytes: int | None = None) -> tuple[int, str]:
    """Hash one concrete regular file without following a final symlink."""
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        return sha256_fd(descriptor, max_bytes=max_bytes)
    except ValueError as exc:
        raise ValueError(f"{exc}: {path}") from exc
    finally:
        os.close(descriptor)
