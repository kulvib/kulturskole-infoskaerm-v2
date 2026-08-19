from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import zipfile

from .constants import CHANNEL, DOMAIN_NAMES, INTEGRITY_ALGORITHM, MANIFEST_SCHEMA, PRODUCT
from .crypto import sha256_file
from .manifest import validate_manifest

EXCLUDED_NAMES = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "dist", "build"}
REQUIRED_WHEELS = (
    "clientflow_runtime-{version}-",
    "PyJWT-2.13.0-",
    "websockets-12.0-",
    "evdev-1.9.3-",
    "pip-26.1.2-",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _source_mode(path: Path) -> int:
    mode = path.stat().st_mode
    return 0o755 if mode & stat.S_IXUSR else 0o644


def _iter_files(root: Path):
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if any(part in EXCLUDED_NAMES for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Symlinks må ikke indgå i releasepayload: {path}")
        if path.is_file():
            yield path


def _tar_add_bytes(archive: tarfile.TarFile, name: str, data: bytes, *, mode: int, epoch: int) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = epoch
    archive.addfile(info, io.BytesIO(data))


def _create_payload(repo: Path, output: Path, *, version: str, epoch: int, runtime_inputs: Path | None) -> tuple[bool, list[dict]]:
    root = f"clientflow-{version}"
    sources: list[tuple[Path, PurePosixPath]] = []
    # The installed release contains only runtime definitions/helpers/configuration and
    # operational release documentation. Source trees, tests and repository history
    # stay in the source artifact, not on the client.
    source_mappings = (
        (Path("client/config-examples"), PurePosixPath(root) / "client-runtime/config-examples"),
        (Path("client/libexec"), PurePosixPath(root) / "client-runtime/libexec"),
        (Path("client/systemd"), PurePosixPath(root) / "client-runtime/systemd"),
        (Path("client/sysusers.d"), PurePosixPath(root) / "client-runtime/sysusers.d"),
        (Path("client/tmpfiles.d"), PurePosixPath(root) / "client-runtime/tmpfiles.d"),
        (Path("client/release/docs"), PurePosixPath(root) / "release/docs"),
    )
    for relative_root, target_root in source_mappings:
        source_root = repo / relative_root
        if not source_root.exists():
            raise ValueError(f"Canonical release-source mangler: {relative_root}")
        for path in _iter_files(source_root):
            sources.append((path, target_root / path.relative_to(source_root).as_posix()))
    package_root = repo / "client/release/lib/clientflow_release"
    for path in _iter_files(package_root):
        sources.append((path, PurePosixPath(root) / "release/lib/clientflow_release" / path.relative_to(package_root).as_posix()))
    wrapper = repo / "client/release/bin/clientflow-release-transaction"
    sources.append((wrapper, PurePosixPath(root) / "release/bin/clientflow-release-transaction"))
    sources.append((repo / "client/VERSION", PurePosixPath(root) / "VERSION"))
    sources.append((repo / "client/release/release-input.json", PurePosixPath(root) / "release/release-input.json"))

    runtime_files: list[dict] = []
    complete = False
    if runtime_inputs and runtime_inputs.is_dir():
        python_tar = runtime_inputs / "python-runtime-amd64.tar"
        wheelhouse = runtime_inputs / "wheelhouse"
        wheel_names = [item.name for item in wheelhouse.glob("*.whl")] if wheelhouse.is_dir() else []
        required = [prefix.format(version=version).replace("-", "_").lower() for prefix in REQUIRED_WHEELS]
        normalized = [name.replace("-", "_").lower() for name in wheel_names]
        wheels_complete = all(any(name.startswith(prefix) for name in normalized) for prefix in required)
        complete = python_tar.is_file() and wheels_complete
        if python_tar.is_file():
            sources.append((python_tar, PurePosixPath(root) / "runtime-inputs/python-runtime-amd64.tar"))
            size, digest = sha256_file(python_tar)
            runtime_files.append({"file": "python-runtime-amd64.tar", "size": size, "sha256": digest})
        if wheelhouse.is_dir():
            for path in _iter_files(wheelhouse):
                sources.append((path, PurePosixPath(root) / "runtime-inputs/wheelhouse" / path.name))
                size, digest = sha256_file(path)
                runtime_files.append({"file": path.name, "size": size, "sha256": digest})

    targets = [target.as_posix() for _, target in sources]
    if len(targets) != len(set(targets)):
        raise ValueError("Releasepayloaden indeholder dublerede målfilnavne")

    with output.open("wb") as raw:
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
            directories: set[str] = {root}
            for _, target in sources:
                current = target.parent
                while str(current) not in {".", ""}:
                    directories.add(current.as_posix())
                    current = current.parent
            for directory in sorted(directories):
                info = tarfile.TarInfo(directory)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = epoch
                archive.addfile(info)
            for source, target in sorted(sources, key=lambda item: item[1].as_posix()):
                _tar_add_bytes(archive, target.as_posix(), source.read_bytes(), mode=_source_mode(source), epoch=epoch)
    return complete, sorted(runtime_files, key=lambda item: item["file"])


def _create_bundle(output: Path, manifest: dict, payload: Path, *, epoch: int) -> None:
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    payload_bytes = payload.read_bytes()
    with output.open("wb") as raw:
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
            _tar_add_bytes(archive, "manifest.json", manifest_bytes, mode=0o644, epoch=epoch)
            _tar_add_bytes(archive, "clientflow-payload.tar", payload_bytes, mode=0o644, epoch=epoch)


def _create_installer_pyz(repo: Path, output: Path, *, epoch: int) -> None:
    package_root = repo / "client/release/lib/clientflow_release"
    entries: list[tuple[str, bytes, int]] = []
    for path in _iter_files(package_root):
        entries.append((f"clientflow_release/{path.relative_to(package_root).as_posix()}", path.read_bytes(), _source_mode(path)))
    entries.append(("__main__.py", b"from clientflow_release.cli import main\nraise SystemExit(main())\n", 0o644))
    timestamp = __import__("datetime").datetime.fromtimestamp(max(epoch, 315532800), tz=__import__("datetime").timezone.utc)
    date_time = (timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second)
    with output.open("wb") as raw:
        raw.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data, mode in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=date_time)
                info.create_system = 3
                info.external_attr = (mode & 0xFFFF) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        raw.flush()
        os.fsync(raw.fileno())
    output.chmod(0o755)


def build(repo: Path, output_dir: Path, *, runtime_inputs: Path | None, allow_dirty: bool) -> dict:
    version = (repo / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads((repo / "client/release/release-input.json").read_text(encoding="utf-8"))
    sequence = int(release_input["release_sequence"])
    release_id = f"clientflow-{version}-seq-{sequence}"
    commit = _git(repo, "rev-parse", "HEAD")
    dirty = bool(_git(repo, "status", "--porcelain"))
    if dirty and not allow_dirty:
        raise ValueError("Reproducerbart releasebuild kræver et rent Git-worktree")
    epoch = int(os.getenv("SOURCE_DATE_EPOCH") or _git(repo, "show", "-s", "--format=%ct", "HEAD"))
    if not 1 <= epoch <= 4_354_819_199:
        raise ValueError("SOURCE_DATE_EPOCH er uden for det understøttede interval")
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = output_dir / "clientflow-payload.tar"
    complete, runtime_files = _create_payload(repo, payload, version=version, epoch=epoch, runtime_inputs=runtime_inputs)
    payload_size, payload_sha = sha256_file(payload)
    manifest = {
        "manifest_schema": MANIFEST_SCHEMA,
        "product": PRODUCT,
        "channel": CHANNEL,
        "version": version,
        "release_id": release_id,
        "release_sequence": sequence,
        "source_date_epoch": epoch,
        "fresh_only": True,
        "deployable": False,
        "integrity_algorithm": INTEGRITY_ALGORITHM,
        "release_approval": {"reference": None, "candidate_sha256": None},
        "source": {"commit": commit, "dirty": dirty},
        "payload": {
            "file": "clientflow-payload.tar",
            "format": "tar",
            "root": f"clientflow-{version}",
            "size": payload_size,
            "sha256": payload_sha,
        },
        "runtime": {
            "python": str(release_input["runtime_python"]),
            "architecture": str(release_input["architecture"]),
            "offline_wheelhouse_complete": complete,
            "artifacts": runtime_files,
        },
        "platform": {
            "os": "ubuntu-desktop-lts",
            "minimum_lts": str(release_input["minimum_ubuntu_lts"]),
            "architecture": str(release_input["architecture"]),
            "requires_preflight": True,
        },
        "credential_domains": list(DOMAIN_NAMES),
        "activation": {
            "automatic": False,
            "requires_manual_approval": True,
            "automatic_reboot": False,
            "health_timeout_seconds": 120,
        },
    }
    validate_manifest(manifest, require_deployable=False)
    bundle = output_dir / f"{release_id}-candidate.tar"
    _create_bundle(bundle, manifest, payload, epoch=epoch)
    installer = output_dir / f"clientflow-installer-{version}.pyz"
    _create_installer_pyz(repo, installer, epoch=epoch)
    manifest_path = output_dir / "manifest.candidate.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksums = []
    for path in (bundle, installer, manifest_path, payload):
        size, digest = sha256_file(path)
        checksums.append(f"{digest}  {path.name}\n")
    (output_dir / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    return {"manifest": manifest, "bundle": bundle, "installer": installer}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic unapproved ClientFlow 1.2.0 release candidate")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-inputs", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    result = build(args.repo.resolve(), args.output_dir.resolve(), runtime_inputs=args.runtime_inputs, allow_dirty=args.allow_dirty)
    print(result["bundle"])
    print(result["installer"])
    return 0
