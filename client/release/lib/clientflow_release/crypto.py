from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, *, max_bytes: int | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise ValueError(f"Filen er større end tilladt: {path}")
            digest.update(chunk)
    return size, digest.hexdigest()
