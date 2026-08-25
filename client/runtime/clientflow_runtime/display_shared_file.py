"""Display-only atomic files that preserve the local control-group boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


def atomic_write_shared_json(
    path: Path,
    value: Any,
    *,
    mode: int,
    group_gid: int | None,
) -> None:
    if group_gid is not None and (
        isinstance(group_gid, bool) or not isinstance(group_gid, int) or group_gid < 0
    ):
        raise ValueError("group_gid skal være et ikke-negativt gid")

    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        if group_gid is not None:
            os.fchown(fd, -1, group_gid)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
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
