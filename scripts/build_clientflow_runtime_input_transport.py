#!/usr/bin/env python3
"""Build one deterministic runtime-input transport TAR from repo-locked platform bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TRANSPORT_BYTES = 512 * 1024 * 1024
FILE_MODE = 0o400
DIR_MODE = 0o700


def _load_lock(lock_path: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported runtime-platform-input lock schema")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("runtime-platform-input lock has no artifacts")
    expected: dict[str, dict[str, object]] = {}
    for raw in artifacts:
        if not isinstance(raw, dict):
            raise ValueError("Invalid artifact entry")
        name = str(raw.get("file") or "")
        digest = str(raw.get("sha256") or "")
        size = raw.get("size")
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError(f"Invalid locked artifact filename: {name!r}")
        if name.startswith("clientflow_runtime-"):
            raise ValueError("Source-specific ClientFlow wheel must not be a platform input")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Invalid SHA-256 for {name}")
        if not isinstance(size, int) or not 0 <= size <= MAX_MEMBER_BYTES:
            raise ValueError(f"Invalid size for {name}")
        if name in expected:
            raise ValueError(f"Duplicate locked artifact: {name}")
        expected[name] = raw
    return data, expected


def _artifact_path(input_dir: Path, name: str) -> Path:
    if name == "python-runtime-amd64.tar":
        return input_dir / name
    return input_dir / "wheelhouse" / name


def _sha256_fd(fd: int) -> tuple[int, str]:
    os.lseek(fd, 0, os.SEEK_SET)
    h = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        h.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return size, h.hexdigest()


def _open_locked_inputs(input_dir: Path, expected: dict[str, dict[str, object]]) -> dict[str, int]:
    input_dir = input_dir.resolve()
    if input_dir.is_symlink() or not input_dir.is_dir():
        raise ValueError("Runtime-input source must be a regular directory")
    wheelhouse = input_dir / "wheelhouse"
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise ValueError("Runtime-input wheelhouse must be a regular directory")

    allowed_paths = {_artifact_path(input_dir, name).resolve(strict=False) for name in expected}
    physical_files: set[Path] = set()
    for candidate in input_dir.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(f"Runtime-input source contains a symlink: {candidate}")
        if candidate.is_dir():
            if candidate != wheelhouse:
                raise ValueError(f"Unexpected runtime-input source directory: {candidate}")
            continue
        if not candidate.is_file():
            raise ValueError(f"Runtime-input source contains a non-regular file: {candidate}")
        physical_files.add(candidate.resolve())
    if physical_files != allowed_paths:
        extra = sorted(str(p.relative_to(input_dir)) for p in physical_files - allowed_paths)
        missing = sorted(str(p.relative_to(input_dir)) for p in allowed_paths - physical_files)
        details = []
        if extra:
            details.append("unexpected=" + ",".join(extra))
        if missing:
            details.append("missing=" + ",".join(missing))
        raise ValueError("Runtime-input source file set does not match lock: " + " ".join(details))

    opened: dict[str, int] = {}
    try:
        for name, declared in sorted(expected.items()):
            path = _artifact_path(input_dir, name)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                os.close(fd)
                raise ValueError(f"Runtime-input artifact is not a regular file: {name}")
            size, digest = _sha256_fd(fd)
            if size != int(declared["size"]) or digest != str(declared["sha256"]):
                os.close(fd)
                raise ValueError(f"Runtime-input artifact does not match lock: {name}")
            opened[name] = fd
        return opened
    except Exception:
        for fd in opened.values():
            os.close(fd)
        raise


def _tar_info(name: str, *, size: int = 0, directory: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    if directory:
        info.type = tarfile.DIRTYPE
        info.mode = DIR_MODE
        info.size = 0
    else:
        info.mode = FILE_MODE
        info.size = size
    return info


def _write_transport(fileobj: BinaryIO, opened: dict[str, int], expected: dict[str, dict[str, object]]) -> None:
    with tarfile.open(fileobj=fileobj, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        tf.addfile(_tar_info("wheelhouse", directory=True))
        for name, declared in sorted(expected.items()):
            member = name if name == "python-runtime-amd64.tar" else f"wheelhouse/{name}"
            fd = opened[name]
            os.lseek(fd, 0, os.SEEK_SET)
            with os.fdopen(os.dup(fd), "rb", closefd=True) as source:
                tf.addfile(_tar_info(member, size=int(declared["size"])), source)
            os.lseek(fd, 0, os.SEEK_SET)


def _verify_transport(path: Path, expected: dict[str, dict[str, object]]) -> None:
    seen: set[str] = set()
    with tarfile.open(path, mode="r:") as tf:
        for member in tf:
            if member.isdir():
                if member.name.rstrip("/") != "wheelhouse":
                    raise ValueError("Deterministic transport contains an unexpected directory")
                continue
            if not member.isfile():
                raise ValueError("Deterministic transport contains a non-regular member")
            if member.name == "python-runtime-amd64.tar":
                name = member.name
            elif member.name.startswith("wheelhouse/") and member.name.count("/") == 1:
                name = member.name.split("/", 1)[1]
            else:
                raise ValueError("Deterministic transport contains an unexpected member path")
            if name not in expected or name in seen:
                raise ValueError("Deterministic transport member set does not match lock")
            declared = expected[name]
            if member.size != int(declared["size"]):
                raise ValueError(f"Deterministic transport size mismatch: {name}")
            source = tf.extractfile(member)
            if source is None:
                raise ValueError(f"Unable to read deterministic transport member: {name}")
            h = hashlib.sha256()
            size = 0
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                h.update(chunk)
            if size != int(declared["size"]) or h.hexdigest() != str(declared["sha256"]):
                raise ValueError(f"Deterministic transport SHA-256 mismatch: {name}")
            seen.add(name)
    if seen != set(expected):
        raise ValueError("Deterministic transport is missing locked artifacts")


def build_transport(input_dir: Path, output: Path, lock_path: Path) -> tuple[int, str]:
    _, expected = _load_lock(lock_path.resolve())
    opened = _open_locked_inputs(input_dir, expected)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        for fd in opened.values():
            os.close(fd)
        raise ValueError("Runtime-input transport output already exists")

    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    tmp_path = Path(tmp_name)
    published = False
    try:
        os.fchmod(tmp_fd, FILE_MODE)
        with os.fdopen(tmp_fd, "w+b", closefd=True) as out:
            _write_transport(out, opened, expected)
            out.flush()
            os.fsync(out.fileno())
        if tmp_path.stat().st_size > MAX_TRANSPORT_BYTES:
            raise ValueError("Runtime-input transport exceeds maximum size")
        _verify_transport(tmp_path, expected)
        for name, declared in expected.items():
            size, digest = _sha256_fd(opened[name])
            if size != int(declared["size"]) or digest != str(declared["sha256"]):
                raise ValueError(f"Runtime-input source mutated during transport build: {name}")
        os.link(tmp_path, output, follow_symlinks=False)
        published = True
        os.unlink(tmp_path)
        dir_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        h = hashlib.sha256()
        size = 0
        with output.open("rb") as fh:
            while chunk := fh.read(1024 * 1024):
                size += len(chunk)
                h.update(chunk)
        return size, h.hexdigest()
    except Exception:
        tmp_path.unlink(missing_ok=True)
        if published:
            output.unlink(missing_ok=True)
        raise
    finally:
        for fd in opened.values():
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--lock",
        type=Path,
        default=ROOT / "client/release/runtime-platform-inputs.lock.json",
    )
    args = parser.parse_args()
    size, digest = build_transport(args.input_dir, args.output, args.lock)
    print(f"runtime_inputs_transport_size={size}")
    print(f"runtime_inputs_transport_sha256={digest}")
    print("RESULT: DETERMINISTIC RUNTIME INPUT TRANSPORT READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
