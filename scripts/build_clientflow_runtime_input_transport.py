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


def _validate_entry(raw: object, *, kind: str) -> tuple[str, dict[str, object]]:
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
    item = dict(raw)
    item["_kind"] = kind
    if kind == "platform":
        for field in ("package", "version", "architecture"):
            if not str(raw.get(field) or "").strip():
                raise ValueError(f"Platform artifact {name} mangler {field}")
    return name, item


def _load_lock(lock_path: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported runtime-platform-input lock schema")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("runtime-platform-input lock has no artifacts")
    platform_artifacts = data.get("platform_artifacts", [])
    if not isinstance(platform_artifacts, list):
        raise ValueError("runtime-platform-input platform_artifacts must be a list")
    expected: dict[str, dict[str, object]] = {}
    for raw, kind in [(item, "runtime") for item in artifacts] + [(item, "platform") for item in platform_artifacts]:
        name, item = _validate_entry(raw, kind=kind)
        if name in expected:
            raise ValueError(f"Duplicate locked artifact: {name}")
        expected[name] = item
    return data, expected


def _artifact_path(input_dir: Path, name: str, declared: dict[str, object]) -> Path:
    if declared.get("_kind") == "platform":
        return input_dir / "platform" / name
    if name == "python-runtime-amd64.tar":
        return input_dir / name
    return input_dir / "wheelhouse" / name


def _member_path(name: str, declared: dict[str, object]) -> str:
    if declared.get("_kind") == "platform":
        return f"platform/{name}"
    return name if name == "python-runtime-amd64.tar" else f"wheelhouse/{name}"


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
    required_dirs = {input_dir / "wheelhouse"}
    if any(item.get("_kind") == "platform" for item in expected.values()):
        required_dirs.add(input_dir / "platform")
    for directory in required_dirs:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"Runtime-input directory mangler eller er usikker: {directory.name}")

    allowed_paths = {_artifact_path(input_dir, name, item).resolve(strict=False) for name, item in expected.items()}
    allowed_dirs = {path.resolve() for path in required_dirs}
    physical_files: set[Path] = set()
    for candidate in input_dir.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(f"Runtime-input source contains a symlink: {candidate}")
        if candidate.is_dir():
            if candidate.resolve() not in allowed_dirs:
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
            path = _artifact_path(input_dir, name, declared)
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
    info.uid = info.gid = 0
    info.uname = info.gname = ""
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
        if any(item.get("_kind") == "platform" for item in expected.values()):
            tf.addfile(_tar_info("platform", directory=True))
        for name, declared in sorted(expected.items()):
            member = _member_path(name, declared)
            fd = opened[name]
            os.lseek(fd, 0, os.SEEK_SET)
            with os.fdopen(os.dup(fd), "rb", closefd=True) as source:
                tf.addfile(_tar_info(member, size=int(declared["size"])), source)
            os.lseek(fd, 0, os.SEEK_SET)


def _verify_transport(path: Path, expected: dict[str, dict[str, object]]) -> None:
    seen: set[str] = set()
    allowed_dirs = {"wheelhouse"}
    if any(item.get("_kind") == "platform" for item in expected.values()):
        allowed_dirs.add("platform")
    member_map = {_member_path(name, item): name for name, item in expected.items()}
    with tarfile.open(path, mode="r:") as tf:
        for member in tf:
            if member.isdir():
                if member.name.rstrip("/") not in allowed_dirs:
                    raise ValueError("Deterministic transport contains an unexpected directory")
                continue
            if not member.isfile() or member.name not in member_map:
                raise ValueError("Deterministic transport contains an unexpected member path")
            name = member_map[member.name]
            if name in seen:
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
        size = output.stat().st_size
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        return size, digest
    finally:
        for fd in opened.values():
            os.close(fd)
        tmp_path.unlink(missing_ok=True)
        if not published and output.exists() and output.stat().st_size == 0:
            output.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=ROOT / "client/release/runtime-platform-inputs.lock.json")
    args = parser.parse_args()
    size, digest = build_transport(args.input_dir, args.output, args.lock)
    print(f"OK size={size} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
