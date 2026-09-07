from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from clientflow_release_format.archive import ArchiveError, FileRegion

ROOT = Path(__file__).resolve().parents[2]


class _ZeroReader(io.RawIOBase):
    def __init__(self, size: int):
        self.remaining = size

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        if size < 0 or size > self.remaining:
            size = self.remaining
        size = min(size, 1024 * 1024)
        self.remaining -= size
        return b"\0" * size


def _stream_sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _large_structural_bundle(tmp_path: Path, *, filler_bytes: int = 80 * 1024 * 1024) -> Path:
    version = "9.9.9"
    sequence = 9999
    release_id = f"clientflow-{version}-seq-{sequence}"
    payload = tmp_path / "payload.tar"
    with tarfile.open(payload, "w", format=tarfile.PAX_FORMAT) as archive:
        root = tarfile.TarInfo(f"clientflow-{version}")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        root.uid = root.gid = 0
        archive.addfile(root)
        filler = tarfile.TarInfo(f"clientflow-{version}/large.bin")
        filler.size = filler_bytes
        filler.mode = 0o644
        filler.uid = filler.gid = 0
        archive.addfile(filler, _ZeroReader(filler_bytes))
    payload_size, payload_sha = _stream_sha256(payload)

    installer = b"bounded-installer"
    manifest = {
        "manifest_schema": 8,
        "product": "ClientFlow",
        "channel": "clientflow-runtime-release",
        "version": version,
        "release_id": release_id,
        "release_sequence": sequence,
        "source_date_epoch": 1_787_000_000,
        "artifact_type": "runtime_release",
        "install_modes": ["fresh_install", "in_place_update"],
        "deployable": False,
        "integrity_algorithm": "sha256",
        "release_approval": {"reference": None, "candidate_sha256": None},
        "source": {"commit": "a" * 40, "dirty": False},
        "payload": {
            "file": "clientflow-payload.tar",
            "format": "tar",
            "root": f"clientflow-{version}",
            "size": payload_size,
            "sha256": payload_sha,
        },
        "fresh_installer": {
            "file": f"clientflow-installer-{version}.pyz",
            "format": "python-zipapp",
            "size": len(installer),
            "sha256": hashlib.sha256(installer).hexdigest(),
        },
        "runtime": {
            "python": "3.13.14",
            "architecture": "amd64",
            "offline_wheelhouse_complete": False,
            "artifacts": [],
        },
        "platform": {
            "os": "ubuntu-desktop-lts",
            "minimum_lts": "26.04",
            "architecture": "amd64",
            "requires_preflight": True,
        },
        "credential_domains": ["status", "display", "livestream", "remote_desktop", "terminal", "system"],
        "activation": {
            "automatic": False,
            "requires_manual_approval": True,
            "automatic_reboot": False,
            "health_timeout_seconds": 120,
        },
    }
    bundle = tmp_path / "large-candidate.tar"
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
    with tarfile.open(bundle, "w", format=tarfile.PAX_FORMAT) as archive:
        for name, raw, mode in (
            ("manifest.json", manifest_bytes, 0o644),
            (manifest["fresh_installer"]["file"], installer, 0o555),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = mode
            member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(raw))
        payload_member = tarfile.TarInfo("clientflow-payload.tar")
        payload_member.size = payload_size
        payload_member.mode = 0o644
        payload_member.uid = payload_member.gid = 0
        with payload.open("rb") as source:
            archive.addfile(payload_member, source)
    return bundle


@pytest.mark.skipif(sys.platform != "linux", reason="RSS regression is Linux-specific")
def test_54a_structure_verifier_stays_bounded_below_payload_size(tmp_path: Path) -> None:
    bundle = _large_structural_bundle(tmp_path)
    code = r'''
import resource
import sys
from pathlib import Path
from clientflow_release_format.bundle import verify_bundle_structure
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
manifest, size, digest = verify_bundle_structure(Path(sys.argv[1]), require_deployable=False)
assert manifest["release_id"] == "clientflow-9.9.9-seq-9999"
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(before, after)
'''
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
    result = subprocess.run(
        [sys.executable, "-c", code, str(bundle)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    before_kib, after_kib = (int(value) for value in result.stdout.split())
    # The payload itself is ~80 MiB. Canonical verification must add only a
    # small bounded working set, independent of payload size.
    assert after_kib - before_kib < 16 * 1024, result.stderr


def test_54a_canonical_paths_use_regions_not_payload_sized_bytes() -> None:
    archive = (ROOT / "backend/clientflow_release_format/archive.py").read_text(encoding="utf-8")
    structure = (ROOT / "backend/clientflow_release_format/bundle.py").read_text(encoding="utf-8")
    deep = (ROOT / "client/release/lib/clientflow_release/runtime_artifacts.py").read_text(encoding="utf-8")
    client_bundle = (ROOT / "client/release/lib/clientflow_release/bundle.py").read_text(encoding="utf-8")
    builder = (ROOT / "client/release/lib/clientflow_release/builder.py").read_text(encoding="utf-8")
    publication = (ROOT / "scripts/publish_clientflow_release.py").read_text(encoding="utf-8")
    serving = (ROOT / "backend/service1/clientflow_release_artifacts.py").read_text(encoding="utf-8")

    assert "class FileRegion" in archive
    assert "os.pread" in archive
    assert "read_bundle_artifact_regions_fd" in archive
    assert "payload_bytes" not in archive
    assert "inspect_payload_region" in structure
    assert "FileRegion" in deep
    assert "io.BytesIO(payload)" not in deep
    assert "dict[str, bytes]" not in deep
    assert "payload.subregion" in deep
    assert "tempfile.NamedTemporaryFile" not in client_bundle
    assert "payload.read_bytes()" not in builder
    assert "installer.read_bytes()" not in builder
    assert "open_verified_bundle(" in publication
    assert "open_verified_bundle_structure" in serving


def test_54a_region_keeps_original_inode_across_path_replacement_and_rejects_in_place_write(tmp_path: Path) -> None:
    path = tmp_path / "artifact.tar"
    original = b"original-pinned-bytes"
    path.write_bytes(original)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        region = FileRegion(descriptor, 0, len(original))
        replacement = tmp_path / "replacement.tar"
        replacement.write_bytes(b"replacement-path-bytes")
        replacement.replace(path)
        assert region.read_small(max_bytes=1024) == original

        writable = os.open(f"/proc/self/fd/{descriptor}", os.O_WRONLY)
        try:
            os.pwrite(writable, b"X", 0)
        finally:
            os.close(writable)
        with pytest.raises(ArchiveError, match="ændrede sig"):
            region.assert_unchanged()
    finally:
        os.close(descriptor)
