#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile
from typing import BinaryIO, Iterator

VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RUNTIME_FILENAME = "python-runtime-amd64.tar"
MANIFEST_SCHEMA = 1
EXCLUDED_DIR_NAMES = {"__pycache__"}
EXCLUDED_FILE_SUFFIXES = {".pyc", ".pyo"}
MAX_FILES = 20_000
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 1024 * 1024 * 1024
MAX_PATH_LENGTH = 240


@dataclass(frozen=True, slots=True)
class SourceEntry:
    logical_path: PurePosixPath
    source_path: Path
    is_dir: bool
    mode: int
    size: int = 0


def _normalized_file_mode(metadata: os.stat_result) -> int:
    return 0o755 if metadata.st_mode & 0o111 else 0o644


def _ensure_within(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Runtime source link escapes source root: {candidate}") from exc
    return resolved


def _excluded(path: PurePosixPath, *, is_dir: bool) -> bool:
    if is_dir:
        return path.name in EXCLUDED_DIR_NAMES
    return path.suffix in EXCLUDED_FILE_SUFFIXES


def _walk_source(
    root: Path,
    current: Path,
    logical: PurePosixPath,
    *,
    ancestors: tuple[Path, ...],
) -> Iterator[SourceEntry]:
    metadata = current.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        resolved = _ensure_within(root, current)
        target_metadata = resolved.stat()
        if stat.S_ISDIR(target_metadata.st_mode):
            if resolved in ancestors:
                raise ValueError(f"Runtime source contains a symlink directory cycle: {current}")
            if _excluded(logical, is_dir=True):
                return
            yield SourceEntry(logical, resolved, True, 0o755)
            for child in sorted(resolved.iterdir(), key=lambda item: item.name):
                yield from _walk_source(
                    root,
                    child,
                    logical / child.name,
                    ancestors=(*ancestors, resolved),
                )
            return
        if stat.S_ISREG(target_metadata.st_mode):
            if _excluded(logical, is_dir=False):
                return
            yield SourceEntry(
                logical,
                resolved,
                False,
                _normalized_file_mode(target_metadata),
                target_metadata.st_size,
            )
            return
        raise ValueError(f"Runtime source link targets unsupported file type: {current}")

    if stat.S_ISDIR(metadata.st_mode):
        resolved = current.resolve(strict=True)
        if resolved in ancestors:
            raise ValueError(f"Runtime source contains a directory cycle: {current}")
        if _excluded(logical, is_dir=True):
            return
        yield SourceEntry(logical, current, True, 0o755)
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            yield from _walk_source(
                root,
                child,
                logical / child.name,
                ancestors=(*ancestors, resolved),
            )
        return

    if stat.S_ISREG(metadata.st_mode):
        if _excluded(logical, is_dir=False):
            return
        yield SourceEntry(
            logical,
            current,
            False,
            _normalized_file_mode(metadata),
            metadata.st_size,
        )
        return

    raise ValueError(f"Runtime source contains unsupported special file: {current}")


def collect_source_entries(source_runtime: Path) -> list[SourceEntry]:
    source_runtime = source_runtime.resolve(strict=True)
    if not source_runtime.is_dir():
        raise ValueError("Runtime source must be a directory")
    entries: list[SourceEntry] = []
    for child in sorted(source_runtime.iterdir(), key=lambda item: item.name):
        entries.extend(
            _walk_source(
                source_runtime,
                child,
                PurePosixPath(child.name),
                ancestors=(source_runtime,),
            )
        )
    logical_names = [entry.logical_path.as_posix() for entry in entries]
    if len(logical_names) != len(set(logical_names)):
        raise ValueError("Runtime source resolves to duplicate logical paths")
    if len(entries) + 1 > MAX_FILES:
        raise ValueError("Runtime source exceeds maximum archive member count")
    total_bytes = 0
    for entry in entries:
        if not entry.is_dir:
            if entry.size > MAX_MEMBER_BYTES:
                raise ValueError(f"Runtime source member exceeds maximum size: {entry.logical_path}")
            total_bytes += entry.size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Runtime source exceeds maximum total archive size")
    return entries


def _open_regular_no_follow(path: Path) -> BinaryIO:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise ValueError(f"Runtime source changed to a non-regular file: {path}")
    return os.fdopen(descriptor, "rb", closefd=True)


def _tar_info(name: str, *, mode: int, is_dir: bool, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    info.mode = mode
    if is_dir:
        info.type = tarfile.DIRTYPE
        info.size = 0
    else:
        info.type = tarfile.REGTYPE
        info.size = size
    return info


def _write_runtime_tar(
    fileobj: BinaryIO,
    entries: list[SourceEntry],
    *,
    version: str,
) -> None:
    root_name = f"python-{version}"
    with tarfile.open(fileobj=fileobj, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        archive.addfile(_tar_info(root_name, mode=0o755, is_dir=True))
        for entry in entries:
            name = f"{root_name}/{entry.logical_path.as_posix()}"
            if entry.is_dir:
                archive.addfile(_tar_info(name, mode=entry.mode, is_dir=True))
                continue
            current = entry.source_path.stat()
            if not stat.S_ISREG(current.st_mode) or current.st_size != entry.size:
                raise ValueError(f"Runtime source mutated during build: {entry.source_path}")
            with _open_regular_no_follow(entry.source_path) as source:
                archive.addfile(
                    _tar_info(name, mode=entry.mode, is_dir=False, size=entry.size),
                    source,
                )


def _validate_archive_name(name: str, *, expected_root: str) -> PurePosixPath:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or len(name) > MAX_PATH_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValueError(f"Runtime TAR contains invalid path: {name!r}")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or not path.parts
        or path.parts[0] != expected_root
    ):
        raise ValueError(f"Runtime TAR contains invalid path: {name}")
    return path


def _safe_extract_for_probe(runtime_tar: Path, destination: Path, *, version: str) -> Path:
    expected_root = f"python-{version}"
    destination.mkdir(mode=0o700, parents=True)
    seen: set[str] = set()
    with tarfile.open(runtime_tar, mode="r:") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("Runtime TAR is empty")
        for member in members:
            path = _validate_archive_name(member.name, expected_root=expected_root)
            if member.name in seen:
                raise ValueError(f"Runtime TAR contains duplicate path: {member.name}")
            seen.add(member.name)
            if member.uid != 0 or member.gid != 0:
                raise ValueError(f"Runtime TAR member is not root-owned: {member.name}")
            if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
                raise ValueError(f"Runtime TAR contains links or special files: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise ValueError(f"Runtime TAR contains unsupported member: {member.name}")

            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(mode=member.mode & 0o777, parents=True, exist_ok=True)
                os.chmod(target, member.mode & 0o777)
                continue
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Runtime TAR member could not be read: {member.name}")
            with target.open("xb") as output:
                while chunk := extracted.read(1024 * 1024):
                    output.write(chunk)
            os.chmod(target, member.mode & 0o777)

    root = destination / expected_root
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Runtime TAR has invalid root directory")
    return root


def _probe_runtime(runtime_root: Path, *, version: str) -> None:
    python3 = runtime_root / "bin" / "python3"
    if not python3.is_file() or python3.is_symlink():
        raise ValueError("Generated runtime is missing regular bin/python3")
    if not os.access(python3, os.X_OK):
        raise ValueError("Generated runtime bin/python3 is not executable")

    probe = """
import json
import pathlib
import platform
import sys
import _ssl
import _sqlite3
import ctypes
print(json.dumps({
    'version': platform.python_version(),
    'prefix': str(pathlib.Path(sys.prefix).resolve()),
    'executable': str(pathlib.Path(sys.executable).resolve()),
}, sort_keys=True))
"""
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    result = subprocess.run(
        [str(python3), "-I", "-c", probe],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Generated runtime execution probe failed:\n" + result.stdout[-4000:])
    try:
        observed = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ValueError("Generated runtime execution probe returned invalid output") from exc
    if observed.get("version") != version:
        raise ValueError(f"Generated runtime has wrong Python version: {observed.get('version')}")
    if Path(str(observed.get("prefix"))).resolve() != runtime_root.resolve():
        raise ValueError("Generated runtime is not relocatable: sys.prefix escaped runtime root")
    if Path(str(observed.get("executable"))).resolve() != python3.resolve():
        raise ValueError("Generated runtime executable probe resolved outside bin/python3")


def verify_runtime_tar(runtime_tar: Path, *, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="clientflow-python-runtime-probe-") as tmp:
        root = _safe_extract_for_probe(runtime_tar, Path(tmp) / "extract", version=version)
        _probe_runtime(root, version=version)


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def build_runtime(
    source_runtime: Path,
    output: Path,
    *,
    version: str,
) -> dict[str, object]:
    if not VERSION_RE.fullmatch(version):
        raise ValueError("Python version must be an exact X.Y.Z value")
    source_runtime = source_runtime.resolve(strict=True)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Runtime output already exists")

    entries = collect_source_entries(source_runtime)
    root_name = f"python-{version}"
    for entry in entries:
        archive_name = f"{root_name}/{entry.logical_path.as_posix()}"
        if len(archive_name) > MAX_PATH_LENGTH:
            raise ValueError(f"Runtime source path exceeds maximum length: {entry.logical_path}")
    required = {"bin/python3"}
    observed = {entry.logical_path.as_posix() for entry in entries if not entry.is_dir}
    missing = sorted(required - observed)
    if missing:
        raise ValueError("Runtime source is missing required files: " + ", ".join(missing))

    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "w+b", closefd=True) as target:
            _write_runtime_tar(target, entries, version=version)
            target.flush()
            os.fsync(target.fileno())
        verify_runtime_tar(tmp_path, version=version)
        os.link(tmp_path, output, follow_symlinks=False)
    finally:
        tmp_path.unlink(missing_ok=True)

    size, digest = sha256_file(output)
    return {
        "schema_version": MANIFEST_SCHEMA,
        "type": "python-runtime",
        "format": "tar",
        "architecture": "amd64",
        "version": version,
        "file": RUNTIME_FILENAME,
        "root": f"python-{version}",
        "size_bytes": size,
        "sha256": digest,
    }


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("Runtime manifest output already exists")
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb", closefd=True) as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, relocatable ClientFlow CPython runtime input"
    )
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--source-runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if args.output.name != RUNTIME_FILENAME:
        raise ValueError(f"Runtime output must be named {RUNTIME_FILENAME}")
    manifest = build_runtime(
        args.source_runtime,
        args.output,
        version=args.python_version,
    )
    _write_manifest(args.manifest, manifest)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
