#!/usr/bin/env python3
"""Prepare one deterministic ClientFlow runtime-input transport from locked bytes.

The previous transport is untrusted transport only. Runtime/bootstrap members are
accepted solely when their individual size/SHA-256 match the current canonical
lock. Current platform artifacts are fetched from operator-supplied HTTPS URLs
and likewise accepted solely by the current lock. The final tar is built twice
with the canonical deterministic builder and must be byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
MAX_FETCH_BYTES = 512 * 1024 * 1024
CHUNK = 1024 * 1024


def _load_script(name: str, filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def _validate_url(url: str, *, initial: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Runtime-input artifact URL must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Runtime-input artifact URL must not contain credentials or fragments")
    if initial and parsed.query:
        raise ValueError("Runtime-input artifact URL must not contain a query string")


class _HttpsOnlyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_url(newurl, initial=False)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_exact(url: str, target: Path, *, expected_size: int, expected_sha256: str) -> None:
    _validate_url(url, initial=True)
    if target.exists():
        raise ValueError(f"Output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(_HttpsOnlyRedirects())
    request = Request(url, headers={"User-Agent": "ClientFlow-Runtime-Input-Prepare/1"})
    h = hashlib.sha256()
    size = 0
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        with opener.open(request, timeout=60) as response, os.fdopen(fd, "wb", closefd=True) as out:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != expected_size:
                raise ValueError("Runtime-input artifact Content-Length mismatch")
            while chunk := response.read(CHUNK):
                size += len(chunk)
                if size > expected_size or size > MAX_FETCH_BYTES:
                    raise ValueError("Runtime-input artifact exceeds declared size")
                h.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if size != expected_size or h.hexdigest() != expected_sha256:
        target.unlink(missing_ok=True)
        raise ValueError("Runtime-input artifact does not match canonical lock")
    if not stat.S_ISREG(target.stat().st_mode):
        target.unlink(missing_ok=True)
        raise ValueError("Runtime-input artifact output is not a regular file")


def _load_lock(lock_path: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported runtime-input lock schema")
    expected: dict[str, dict[str, object]] = {}
    for key, kind in (
        ("artifacts", "runtime"),
        ("platform_artifacts", "platform"),
        ("preclaim_bootstrap_artifacts", "bootstrap"),
    ):
        rows = data.get(key, [])
        if not isinstance(rows, list):
            raise ValueError(f"Invalid {key} in runtime-input lock")
        for raw in rows:
            if not isinstance(raw, dict):
                raise ValueError("Invalid runtime-input lock entry")
            name = str(raw.get("file") or "")
            digest = str(raw.get("sha256") or "")
            size = raw.get("size")
            if not name or "/" in name or "\\" in name or name in {".", ".."}:
                raise ValueError(f"Invalid runtime-input filename: {name!r}")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError(f"Invalid SHA-256 for {name}")
            if not isinstance(size, int) or size < 0 or size > MAX_FETCH_BYTES:
                raise ValueError(f"Invalid size for {name}")
            if name in expected:
                raise ValueError(f"Duplicate runtime-input artifact: {name}")
            item = dict(raw)
            item["_kind"] = kind
            expected[name] = item
    if not expected:
        raise ValueError("Runtime-input lock contains no artifacts")
    return data, expected


def _member_path(name: str, item: dict[str, object]) -> str:
    kind = item["_kind"]
    if kind == "platform":
        return f"platform/{name}"
    if kind == "bootstrap":
        return f"bootstrap/{name}"
    return name if name == "python-runtime-amd64.tar" else f"wheelhouse/{name}"


def _target_path(root: Path, name: str, item: dict[str, object]) -> Path:
    return root / _member_path(name, item)


def seed_reusable_inputs(base_archive: Path, source_dir: Path, lock_path: Path) -> None:
    """Copy only current runtime/bootstrap bytes from a previous transport.

    Previous platform members are deliberately ignored. Every reused byte is
    independently verified against the *current* lock before publication.
    """
    _, expected = _load_lock(lock_path)
    reusable = {name: item for name, item in expected.items() if item["_kind"] != "platform"}
    member_map = {_member_path(name, item): name for name, item in reusable.items()}
    source_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    (source_dir / "wheelhouse").mkdir(mode=0o700)
    if any(item["_kind"] == "bootstrap" for item in reusable.values()):
        (source_dir / "bootstrap").mkdir(mode=0o700)
    (source_dir / "platform").mkdir(mode=0o700)

    seen: set[str] = set()
    with tarfile.open(base_archive, mode="r:") as tf:
        for member in tf:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                raise ValueError(f"Unsafe base transport member path: {member.name!r}")
            if member.isdir():
                if member.name.rstrip("/") not in {"wheelhouse", "platform", "bootstrap"}:
                    raise ValueError(f"Unexpected base transport directory: {member.name}")
                continue
            if not member.isfile():
                raise ValueError(f"Base transport member must be regular: {member.name}")
            name = member_map.get(member.name)
            if name is None:
                if len(pure.parts) == 2 and pure.parts[0] == "platform":
                    continue
                raise ValueError(f"Unexpected reusable base transport member: {member.name}")
            if name in seen:
                raise ValueError(f"Duplicate reusable base transport member: {name}")
            item = reusable[name]
            if member.size != int(item["size"]):
                raise ValueError(f"Reusable runtime-input size mismatch: {name}")
            src = tf.extractfile(member)
            if src is None:
                raise ValueError(f"Unable to read reusable runtime-input: {name}")
            target = _target_path(source_dir, name, item)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            h = hashlib.sha256()
            written = 0
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
            try:
                with os.fdopen(fd, "wb", closefd=True) as out:
                    while chunk := src.read(CHUNK):
                        written += len(chunk)
                        if written > int(item["size"]):
                            raise ValueError(f"Reusable runtime-input exceeds declared size: {name}")
                        h.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
            except Exception:
                target.unlink(missing_ok=True)
                raise
            if written != int(item["size"]) or h.hexdigest() != str(item["sha256"]):
                target.unlink(missing_ok=True)
                raise ValueError(f"Reusable runtime-input SHA-256 mismatch: {name}")
            seen.add(name)
    missing = sorted(set(reusable) - seen)
    if missing:
        raise ValueError("Base transport is missing reusable locked artifacts: " + ", ".join(missing))


def _parse_platform_urls(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        name, sep, url = raw.partition("=")
        if not sep or not name or not url or name in result:
            raise ValueError("--platform-url must be supplied as unique FILE=https://...")
        result[name] = url
    return result


def fetch_platform_inputs(source_dir: Path, lock_path: Path, platform_urls: dict[str, str]) -> None:
    _, expected = _load_lock(lock_path)
    platform = {name: item for name, item in expected.items() if item["_kind"] == "platform"}
    if set(platform_urls) != set(platform):
        missing = sorted(set(platform) - set(platform_urls))
        extra = sorted(set(platform_urls) - set(platform))
        raise ValueError(f"Platform URL set does not match lock; missing={missing} extra={extra}")
    for name, item in sorted(platform.items()):
        _fetch_exact(
            platform_urls[name],
            _target_path(source_dir, name, item),
            expected_size=int(item["size"]),
            expected_sha256=str(item["sha256"]),
        )


def prepare_transport(
    *,
    base_archive: Path,
    lock_path: Path,
    platform_urls: dict[str, str],
    output: Path,
) -> tuple[int, str]:
    builder = _load_script("clientflow_runtime_transport_builder", "build_clientflow_runtime_input_transport.py")
    materializer = _load_script("clientflow_runtime_transport_materializer", "materialize_clientflow_runtime_inputs.py")
    output = output.resolve()
    if output.exists():
        raise ValueError("Runtime-input transport output already exists")
    with tempfile.TemporaryDirectory(prefix="clientflow-runtime-input-prepare-") as tmp_name:
        tmp = Path(tmp_name)
        source = tmp / "source"
        seed_reusable_inputs(base_archive.resolve(), source, lock_path.resolve())
        fetch_platform_inputs(source, lock_path.resolve(), platform_urls)
        first = tmp / "first.tar"
        second = tmp / "second.tar"
        size_a, sha_a = builder.build_transport(source, first, lock_path)
        size_b, sha_b = builder.build_transport(source, second, lock_path)
        if size_a != size_b or sha_a != sha_b or first.read_bytes() != second.read_bytes():
            raise ValueError("Runtime-input transport reproducibility mismatch")
        materializer.materialize(first, tmp / "verified", lock_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        os.link(first, output, follow_symlinks=False)
        size, digest = _sha256_file(output)
        if size != size_a or digest != sha_a:
            output.unlink(missing_ok=True)
            raise ValueError("Published runtime-input transport changed after verification")
        return size, digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-archive", type=Path, required=True)
    parser.add_argument("--platform-url", action="append", default=[], metavar="FILE=HTTPS_URL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=ROOT / "client/release/runtime-platform-inputs.lock.json")
    args = parser.parse_args()
    size, digest = prepare_transport(
        base_archive=args.base_archive,
        lock_path=args.lock,
        platform_urls=_parse_platform_urls(args.platform_url),
        output=args.output,
    )
    print(f"runtime_inputs_transport_size={size}")
    print(f"runtime_inputs_transport_sha256={digest}")
    print("RESULT: RUNTIME INPUT TRANSPORT PREPARED REPRODUCIBLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
