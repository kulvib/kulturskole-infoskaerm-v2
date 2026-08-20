#!/usr/bin/env python3
"""Publish one already-approved ClientFlow bundle into an immutable backend artifact store."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "client" / "release" / "lib"))

from clientflow_release.bundle import verify_bundle  # noqa: E402
from clientflow_release.constants import INSTALL_MODE_UPDATE, MAX_BUNDLE_BYTES  # noqa: E402
from clientflow_release.crypto import sha256_file  # noqa: E402
from service1.clientflow_releases import resolve_release  # noqa: E402


def _secure_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise RuntimeError("Artifact-kataloget skal være en absolut sti")
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("Artifact-kataloget findes ikke") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o022:
        raise RuntimeError("Artifact-kataloget er ikke et sikkert immutable publication target")
    if metadata.st_uid not in {0, os.geteuid()}:
        raise RuntimeError("Artifact-kataloget har uventet ejer")
    return path


def publish(
    bundle: Path,
    artifact_dir: Path,
    *,
    expected_bundle_sha256: str,
    expected_approval_reference: str,
    expected_source_commit: str,
) -> tuple[Path, int, str]:
    expected_bundle_sha256 = str(expected_bundle_sha256 or "").strip().lower()
    expected_approval_reference = str(expected_approval_reference or "").strip()
    expected_source_commit = str(expected_source_commit or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_bundle_sha256):
        raise RuntimeError("expected_bundle_sha256 skal være præcis SHA-256")
    if not expected_approval_reference:
        raise RuntimeError("expected_approval_reference er påkrævet")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source_commit):
        raise RuntimeError("expected_source_commit skal være et fuldt Git commit-SHA")
    manifest, _payload = verify_bundle(
        bundle,
        require_deployable=True,
        required_install_mode=INSTALL_MODE_UPDATE,
    )
    release = resolve_release(str(manifest["version"]))
    expected_release_id = str(release.get("release_id") or release.get("revision") or "")
    if manifest["release_id"] != expected_release_id:
        raise RuntimeError("Approved bundle matcher ikke backendens releasekatalog")
    if int(manifest["release_sequence"]) != int(release["release_sequence"]):
        raise RuntimeError("Approved bundle release_sequence matcher ikke backendens releasekatalog")

    size, digest = sha256_file(bundle, max_bytes=MAX_BUNDLE_BYTES)
    if digest != expected_bundle_sha256:
        raise RuntimeError("Approved bundle matcher ikke den forventede bundle-SHA-256")
    approval = manifest.get("release_approval") or {}
    source = manifest.get("source") or {}
    if str(approval.get("reference") or "") != expected_approval_reference:
        raise RuntimeError("Approved bundle matcher ikke den forventede approval-reference")
    if str(source.get("commit") or "").lower() != expected_source_commit:
        raise RuntimeError("Approved bundle matcher ikke det forventede source commit")
    root = _secure_directory(artifact_dir)
    destination = root / f"{manifest['release_id']}.tar"
    if destination.exists() or destination.is_symlink():
        try:
            existing_size, existing_digest = sha256_file(destination, max_bytes=MAX_BUNDLE_BYTES)
        except (OSError, ValueError) as exc:
            raise RuntimeError("Eksisterende publiceret artifact er ugyldigt") from exc
        if (existing_size, existing_digest) != (size, digest):
            raise RuntimeError("Artifact-ID er allerede publiceret med andre bytes")
        return destination, size, digest

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{manifest['release_id']}.", suffix=".publish", dir=root)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with bundle.open("rb") as source, os.fdopen(descriptor, "wb", closefd=True) as target:
            descriptor = -1
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        staged_size, staged_digest = sha256_file(temporary, max_bytes=MAX_BUNDLE_BYTES)
        if (staged_size, staged_digest) != (size, digest):
            raise RuntimeError("Staged artifact matcher ikke den verificerede approved bundle")
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            existing_size, existing_digest = sha256_file(destination, max_bytes=MAX_BUNDLE_BYTES)
            if (existing_size, existing_digest) != (size, digest):
                raise RuntimeError("Concurrent publication brugte samme release-ID med andre bytes")
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination, size, digest
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish one approved ClientFlow runtime-release artifact")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--expected-approval-reference", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--publish-release", action="store_true")
    args = parser.parse_args(argv)
    if not args.publish_release:
        raise SystemExit("Artifact-publicering kræver --publish-release")
    path, size, digest = publish(
        args.bundle.resolve(),
        args.artifact_dir.resolve(),
        expected_bundle_sha256=args.expected_bundle_sha256,
        expected_approval_reference=args.expected_approval_reference,
        expected_source_commit=args.expected_source_commit,
    )
    print(path)
    print(f"BUNDLE_SIZE={size}")
    print(f"BUNDLE_SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
