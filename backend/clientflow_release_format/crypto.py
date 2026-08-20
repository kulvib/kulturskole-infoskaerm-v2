from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat


def sha256_file(path: Path, *, max_bytes: int | None = None) -> tuple[int, str]:
    """Hash one concrete regular file without following a final symlink."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Filen er ikke en almindelig fil: {path}")
    if max_bytes is not None and metadata.st_size > max_bytes:
        raise ValueError(f"Filen er større end tilladt: {path}")
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise ValueError(f"Filen er større end tilladt: {path}")
            digest.update(chunk)
    finally:
        os.close(descriptor)
    if size != metadata.st_size:
        raise ValueError(f"Filen ændrede størrelse under hashing: {path}")
    return size, digest.hexdigest()
