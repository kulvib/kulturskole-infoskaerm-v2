#!/usr/bin/env python3
"""Publish one already-approved ClientFlow bundle into an immutable backend artifact store."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "client" / "release" / "lib"))

from clientflow_release.bundle import open_verified_bundle  # noqa: E402
from clientflow_release.constants import INSTALL_MODE_UPDATE, MAX_BUNDLE_BYTES  # noqa: E402
from clientflow_release.crypto import sha256_fd  # noqa: E402


def _source_release_identity(repo: Path = REPO) -> tuple[str, int, str]:
    """Return the exact build identity declared by this source checkout.

    Publication deliberately does not consult the runtime selection catalog.
    A new approved bundle must be materialized before the catalog is promoted,
    otherwise fresh-install/update selection can point at bytes that do not yet
    exist in the immutable artifact store.
    """
    try:
        version = (repo / "client/VERSION").read_text(encoding="utf-8").strip()
        release_input = json.loads((repo / "client/release/release-input.json").read_text(encoding="utf-8"))
        sequence = int(release_input["release_sequence"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("Canonical source release identity kunne ikke læses") from exc

    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Canonical source VERSION er ugyldig")
    if sequence <= 0:
        raise RuntimeError("Canonical source release_sequence er ugyldig")
    return version, sequence, f"clientflow-{version}-seq-{sequence}"


def _open_secure_directory(path: Path) -> int:
    if not path.is_absolute():
        raise RuntimeError("Artifact-kataloget skal være en absolut sti")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise RuntimeError("Artifact-kataloget findes ikke") from exc
    except OSError as exc:
        raise RuntimeError("Artifact-kataloget kunne ikke åbnes sikkert") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o022:
            raise RuntimeError("Artifact-kataloget er ikke et sikkert immutable publication target")
        if metadata.st_uid not in {0, os.geteuid()}:
            raise RuntimeError("Artifact-kataloget har uventet ejer")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_published_file(directory_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise RuntimeError("Eksisterende publiceret artifact kunne ikke åbnes sikkert") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("Eksisterende publiceret artifact er ikke en almindelig fil")
        if metadata.st_mode & 0o022:
            raise RuntimeError("Eksisterende publiceret artifact må ikke være gruppe-/verdensskrivbart")
        if metadata.st_uid not in {0, os.geteuid()}:
            raise RuntimeError("Eksisterende publiceret artifact har uventet ejer")
        if not 1 <= metadata.st_size <= MAX_BUNDLE_BYTES:
            raise RuntimeError("Eksisterende publiceret artifact har ugyldig størrelse")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _existing_artifact_identity(directory_fd: int, name: str) -> tuple[int, str]:
    descriptor = _open_published_file(directory_fd, name)
    try:
        return sha256_fd(descriptor, max_bytes=MAX_BUNDLE_BYTES)
    except (OSError, ValueError) as exc:
        raise RuntimeError("Eksisterende publiceret artifact er ugyldigt") from exc
    finally:
        os.close(descriptor)


def _create_temporary_artifact(directory_fd: int, release_id: str) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    for _attempt in range(32):
        name = f".{release_id}.{secrets.token_hex(8)}.publish"
        try:
            descriptor = os.open(name, flags, 0o644, dir_fd=directory_fd)
            return descriptor, name
        except FileExistsError:
            continue
    raise RuntimeError("Kunne ikke oprette unik publication-tempfil")


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

    manifest, _payload, size, digest, source_handle = open_verified_bundle(
        bundle,
        require_deployable=True,
        required_install_mode=INSTALL_MODE_UPDATE,
    )
    try:
        if digest != expected_bundle_sha256:
            raise RuntimeError("Approved bundle matcher ikke den forventede bundle-SHA-256")

        source_version, source_sequence, source_release_id = _source_release_identity()
        if str(manifest["version"]) != source_version:
            raise RuntimeError("Approved bundle matcher ikke canonical source VERSION")
        if str(manifest["release_id"]) != source_release_id:
            raise RuntimeError("Approved bundle matcher ikke canonical source release-ID")
        if int(manifest["release_sequence"]) != source_sequence:
            raise RuntimeError("Approved bundle matcher ikke canonical source release_sequence")

        approval = manifest.get("release_approval") or {}
        source = manifest.get("source") or {}
        if str(approval.get("reference") or "") != expected_approval_reference:
            raise RuntimeError("Approved bundle matcher ikke den forventede approval-reference")
        if str(source.get("commit") or "").lower() != expected_source_commit:
            raise RuntimeError("Approved bundle matcher ikke det forventede source commit")

        directory_fd = _open_secure_directory(artifact_dir)
        try:
            destination_name = f"{manifest['release_id']}.tar"
            try:
                existing_size, existing_digest = _existing_artifact_identity(directory_fd, destination_name)
            except FileNotFoundError:
                pass
            else:
                if (existing_size, existing_digest) != (size, digest):
                    raise RuntimeError("Artifact-ID er allerede publiceret med andre bytes")
                return artifact_dir / destination_name, size, digest

            temporary_fd, temporary_name = _create_temporary_artifact(directory_fd, str(manifest["release_id"]))
            try:
                os.lseek(source_handle.fileno(), 0, os.SEEK_SET)
                with os.fdopen(temporary_fd, "wb", closefd=True) as target:
                    temporary_fd = -1
                    shutil.copyfileobj(source_handle, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())

                # Re-hash the same source inode after copying. Together with the
                # staged hash below, this proves that publication used exactly
                # the bytes that were structurally verified above.
                source_size, source_digest = sha256_fd(
                    source_handle.fileno(),
                    max_bytes=MAX_BUNDLE_BYTES,
                )
                if (source_size, source_digest) != (size, digest):
                    raise RuntimeError("Approved bundle ændrede sig under publication")

                staged_fd = _open_published_file(directory_fd, temporary_name)
                try:
                    staged_size, staged_digest = sha256_fd(staged_fd, max_bytes=MAX_BUNDLE_BYTES)
                finally:
                    os.close(staged_fd)
                if (staged_size, staged_digest) != (size, digest):
                    raise RuntimeError("Staged artifact matcher ikke de verificerede approved bundle-bytes")

                try:
                    os.link(
                        temporary_name,
                        destination_name,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    existing_size, existing_digest = _existing_artifact_identity(directory_fd, destination_name)
                    if (existing_size, existing_digest) != (size, digest):
                        raise RuntimeError("Concurrent publication brugte samme release-ID med andre bytes")

                os.fsync(directory_fd)
                return artifact_dir / destination_name, size, digest
            finally:
                if temporary_fd >= 0:
                    os.close(temporary_fd)
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory_fd)
    finally:
        source_handle.close()


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
