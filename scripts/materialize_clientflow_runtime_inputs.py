#!/usr/bin/env python3
"""Materialize hash-locked runtime/platform inputs from an untrusted transport tar."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MAX_TRANSPORT_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024


def _sha256_file(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def _validate_entry(raw: object, *, kind: str) -> tuple[str, dict[str, object]]:
    if not isinstance(raw, dict):
        raise ValueError("Invalid artifact entry")
    name = str(raw.get("file") or "")
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError(f"Invalid locked artifact filename: {name!r}")
    if name.startswith("clientflow_runtime-"):
        raise ValueError("Source-specific ClientFlow wheel must not be a platform input")
    digest = str(raw.get("sha256") or "")
    size = raw.get("size")
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


def _member_path(name: str, declared: dict[str, object]) -> str:
    if declared.get("_kind") == "platform":
        return f"platform/{name}"
    return name if name == "python-runtime-amd64.tar" else f"wheelhouse/{name}"


def _target_path(root: Path, name: str, declared: dict[str, object]) -> Path:
    return root / _member_path(name, declared)


def _member_to_artifact(member_name: str, expected: dict[str, dict[str, object]]) -> str:
    pure = PurePosixPath(member_name)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"Unsafe runtime-input member path: {member_name!r}")
    matches = [name for name, item in expected.items() if _member_path(name, item) == member_name]
    if len(matches) != 1:
        raise ValueError(f"Undeclared runtime-input artifact path: {member_name!r}")
    return matches[0]


def materialize(archive_path: Path, output_dir: Path, lock_path: Path) -> dict[str, object]:
    archive_path = archive_path.resolve()
    lock_path = lock_path.resolve()
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("Runtime-input transport must be a regular non-symlink file")
    st = archive_path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_TRANSPORT_BYTES:
        raise ValueError("Runtime-input transport has invalid type or size")

    lock, expected = _load_lock(lock_path)
    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="clientflow-runtime-materialize-") as tmp_name:
        tmp = Path(tmp_name)
        (tmp / "wheelhouse").mkdir(mode=0o700)
        if any(item.get("_kind") == "platform" for item in expected.values()):
            (tmp / "platform").mkdir(mode=0o700)
        allowed_dirs = {"wheelhouse"} | ({"platform"} if (tmp / "platform").exists() else set())

        with tarfile.open(archive_path, mode="r:") as tf:
            for member in tf:
                if member.isdir():
                    if member.name.rstrip("/") not in allowed_dirs:
                        raise ValueError(f"Unexpected directory in runtime-input transport: {member.name}")
                    continue
                if not member.isfile():
                    raise ValueError(f"Runtime-input member must be a regular file: {member.name}")
                name = _member_to_artifact(member.name, expected)
                if name in seen:
                    raise ValueError(f"Duplicate runtime-input artifact: {name}")
                declared = expected[name]
                if member.size != int(declared["size"]):
                    raise ValueError(f"Runtime-input size mismatch for {name}")
                source = tf.extractfile(member)
                if source is None:
                    raise ValueError(f"Unable to read runtime-input artifact: {name}")
                target = _target_path(tmp, name, declared)
                h = hashlib.sha256()
                written = 0
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
                try:
                    with os.fdopen(fd, "wb", closefd=True) as out:
                        while chunk := source.read(1024 * 1024):
                            written += len(chunk)
                            if written > int(declared["size"]):
                                raise ValueError(f"Runtime-input artifact exceeds declared size: {name}")
                            h.update(chunk)
                            out.write(chunk)
                        out.flush()
                        os.fsync(out.fileno())
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                if written != int(declared["size"]) or h.hexdigest() != str(declared["sha256"]):
                    target.unlink(missing_ok=True)
                    raise ValueError(f"Runtime-input SHA-256 mismatch for {name}")
                seen.add(name)

        missing = sorted(set(expected) - seen)
        if missing:
            raise ValueError("Missing runtime-input artifacts: " + ", ".join(missing))

        output_dir = output_dir.resolve()
        if output_dir.exists():
            if output_dir.is_symlink() or not output_dir.is_dir():
                raise ValueError("Runtime-input output path is not a safe directory")
            if any(output_dir.iterdir()):
                raise ValueError("Runtime-input output directory must be empty")
        else:
            output_dir.mkdir(parents=True, mode=0o700)
        for source in sorted(tmp.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(tmp)
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, target, follow_symlinks=False)
            os.chmod(target, 0o400)

    runtime_verified: list[dict[str, object]] = []
    platform_verified: list[dict[str, object]] = []
    for name, declared in sorted(expected.items()):
        path = _target_path(output_dir, name, declared)
        size, digest = _sha256_file(path)
        if size != int(declared["size"]) or digest != str(declared["sha256"]):
            raise ValueError(f"Post-materialization verification failed for {name}")
        item = {"file": name, "size": size, "sha256": digest}
        (platform_verified if declared.get("_kind") == "platform" else runtime_verified).append(item)
    return {
        "runtime_python": lock["runtime_python"],
        "architecture": lock["architecture"],
        "artifacts": runtime_verified,
        "platform_artifacts": platform_verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=ROOT / "client/release/runtime-platform-inputs.lock.json")
    args = parser.parse_args()
    result = materialize(args.archive, args.output_dir, args.lock)
    for item in [*result["artifacts"], *result["platform_artifacts"]]:
        print(f"OK {item['file']} size={item['size']} sha256={item['sha256']}")
    print("RESULT: HASH-LOCKED RUNTIME INPUTS MATERIALIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
