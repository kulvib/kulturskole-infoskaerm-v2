from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


class FilesystemError(RuntimeError):
    pass


def ensure_real_directory(path: Path, *, mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise FilesystemError(f"Katalogstien er ikke et reelt katalog: {path}")
    os.chmod(path, mode)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    ensure_real_directory(
        path.parent,
        mode=0o700 if path.parent.name in {"credentials", "release", "update"} else 0o755,
    )
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        fsync_directory(path.parent)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise


def atomic_write_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write_bytes(path, data, mode=mode)


def load_secure_json(
    path: Path,
    *,
    max_bytes: int = 8 * 1024 * 1024,
    forbidden_mode_bits: int = 0o077,
) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & forbidden_mode_bits:
            raise FilesystemError(f"Usikker statefil: {path}")
        if metadata.st_size > max_bytes:
            raise FilesystemError(f"Statefil er for stor: {path}")
        raw = os.read(descriptor, max_bytes + 1)
    finally:
        os.close(descriptor)
    if len(raw) > max_bytes:
        raise FilesystemError(f"Statefil er for stor: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FilesystemError(f"Statefil er ugyldig: {path}") from exc
    if not isinstance(value, dict):
        raise FilesystemError(f"Statefil skal være et objekt: {path}")
    return value


def atomic_symlink(target: str, link: Path) -> None:
    ensure_real_directory(link.parent, mode=0o755)
    temporary = link.parent / f".{link.name}.{os.getpid()}.new"
    temporary.unlink(missing_ok=True)
    os.symlink(target, temporary)
    os.replace(temporary, link)
    fsync_directory(link.parent)


def remove_tree_no_symlink(path: Path) -> None:
    if not path.exists():
        return
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise FilesystemError(f"Nægtede at slette ikke-katalog: {path}")
    import shutil
    shutil.rmtree(path)
