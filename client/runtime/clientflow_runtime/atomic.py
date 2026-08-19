"""Atomic file helpers with fail-closed permissions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


def atomic_write_bytes(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    atomic_write_bytes(path, data, mode=mode)
