from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release_format.constants import (  # noqa: E402
    ARTIFACT_TYPE_RUNTIME_RELEASE,
    CHANNEL,
    DOMAIN_NAMES,
    INSTALL_MODE_FRESH,
    INSTALL_MODE_UPDATE,
    INTEGRITY_ALGORITHM,
    MANIFEST_SCHEMA,
    PRODUCT,
)
from clientflow_release import approval as approval_module  # noqa: E402
from clientflow_release import bundle as release_bundle  # noqa: E402
from clientflow_release.archive import read_bundle  # noqa: E402
from scripts import publish_clientflow_release as publication  # noqa: E402


RELEASE_ID = "clientflow-1.3.2-seq-1203"
VERSION = "1.3.2"
SEQUENCE = 1203


def _approved_bundle(
    directory: Path,
    *,
    approval_reference: str,
    source_commit: str,
    marker: bytes,
    deployable: bool = True,
    installer_bytes: bytes | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload_path = directory / "payload.tar"
    with tarfile.open(payload_path, "w", format=tarfile.PAX_FORMAT) as archive:
        root = tarfile.TarInfo(f"clientflow-{VERSION}")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        root.uid = root.gid = 0
        root.mtime = 1_787_000_000
        archive.addfile(root)

        member = tarfile.TarInfo(f"clientflow-{VERSION}/marker")
        member.size = len(marker)
        member.mode = 0o644
        member.uid = member.gid = 0
        member.mtime = 1_787_000_000
        archive.addfile(member, io.BytesIO(marker))

    payload = payload_path.read_bytes()
    installer_bytes = installer_bytes if installer_bytes is not None else b"embedded-installer-51h"
    manifest = {
        "manifest_schema": MANIFEST_SCHEMA,
        "product": PRODUCT,
        "channel": CHANNEL,
        "version": VERSION,
        "release_id": RELEASE_ID,
        "release_sequence": SEQUENCE,
        "source_date_epoch": 1_787_000_000,
        "artifact_type": ARTIFACT_TYPE_RUNTIME_RELEASE,
        "install_modes": [INSTALL_MODE_FRESH, INSTALL_MODE_UPDATE],
        "deployable": deployable,
        "integrity_algorithm": INTEGRITY_ALGORITHM,
        "release_approval": (
            {"reference": approval_reference, "candidate_sha256": "a" * 64}
            if deployable
            else {"reference": None, "candidate_sha256": None}
        ),
        "source": {"commit": source_commit, "dirty": False},
        "fresh_installer": {
            "file": f"clientflow-installer-{VERSION}.pyz",
            "format": "python-zipapp",
            "size": len(installer_bytes),
            "sha256": hashlib.sha256(installer_bytes).hexdigest(),
        },
        "payload": {
            "file": "clientflow-payload.tar",
            "format": "tar",
            "root": f"clientflow-{VERSION}",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "runtime": {
            "python": "3.13.14",
            "architecture": "amd64",
            "offline_wheelhouse_complete": True,
            "artifacts": [],
        },
        "platform": {
            "os": "ubuntu-desktop-lts",
            "minimum_lts": "26.04",
            "architecture": "amd64",
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

    bundle = directory / f"{RELEASE_ID}.tar"
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with tarfile.open(bundle, "w", format=tarfile.PAX_FORMAT) as archive:
        for name, raw in (
            ("manifest.json", manifest_bytes),
            ("clientflow-payload.tar", payload),
            (manifest["fresh_installer"]["file"], installer_bytes),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = 0o644
            member.uid = member.gid = 0
            member.mtime = 1_787_000_000
            archive.addfile(member, io.BytesIO(raw))
    return bundle


def _source_identity() -> tuple[str, int, str]:
    return VERSION, SEQUENCE, RELEASE_ID


def test_51h_publication_streams_from_the_same_open_file_identity_that_was_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = _approved_bundle(
        tmp_path / "source",
        approval_reference="approval-first",
        source_commit="c" * 40,
        marker=b"first-approved-bytes",
    )
    replacement = _approved_bundle(
        tmp_path / "replacement",
        approval_reference="approval-second",
        source_commit="d" * 40,
        marker=b"replacement-bytes",
    )
    expected_bytes = source.read_bytes()
    expected_sha = hashlib.sha256(expected_bytes).hexdigest()

    real_open = publication.open_verified_bundle
    swapped = False

    def open_then_replace_path(bundle, **kwargs):
        nonlocal swapped
        result = real_open(bundle, **kwargs)
        if not swapped:
            swapped = True
            replacement.replace(source)
        return result

    monkeypatch.setattr(release_bundle, "validate_runtime_artifacts", lambda _payload, _manifest: None)
    monkeypatch.setattr(publication, "open_verified_bundle", open_then_replace_path)
    monkeypatch.setattr(publication, "_source_release_identity", _source_identity)

    artifact_dir = tmp_path / "artifact-store"
    artifact_dir.mkdir(mode=0o700)
    destination, size, digest = publication.publish(
        source,
        artifact_dir,
        expected_bundle_sha256=expected_sha,
        expected_approval_reference="approval-first",
        expected_source_commit="c" * 40,
    )

    assert swapped is True
    assert (size, digest) == (len(expected_bytes), expected_sha)
    assert destination.read_bytes() == expected_bytes
    assert destination.read_bytes() != source.read_bytes()


def test_51h_idempotent_publication_rejects_insecure_existing_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = _approved_bundle(
        tmp_path / "source",
        approval_reference="approval-first",
        source_commit="c" * 40,
        marker=b"approved-bytes",
    )
    expected_bytes = source.read_bytes()
    expected_sha = hashlib.sha256(expected_bytes).hexdigest()
    monkeypatch.setattr(release_bundle, "validate_runtime_artifacts", lambda _payload, _manifest: None)
    monkeypatch.setattr(publication, "_source_release_identity", _source_identity)

    artifact_dir = tmp_path / "artifact-store"
    artifact_dir.mkdir(mode=0o700)
    destination = artifact_dir / f"{RELEASE_ID}.tar"
    destination.write_bytes(expected_bytes)
    destination.chmod(0o666)

    with pytest.raises(RuntimeError, match="gruppe-/verdensskrivbart"):
        publication.publish(
            source,
            artifact_dir,
            expected_bundle_sha256=expected_sha,
            expected_approval_reference="approval-first",
            expected_source_commit="c" * 40,
        )

    assert stat.S_IMODE(destination.stat().st_mode) == 0o666


def test_51h_approval_promotes_payload_from_same_open_candidate_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    installer_bytes = b"verified-installer"
    installer = tmp_path / f"clientflow-installer-{VERSION}.pyz"
    installer.write_bytes(installer_bytes)

    candidate = _approved_bundle(
        tmp_path / "candidate",
        approval_reference="unused",
        source_commit="c" * 40,
        marker=b"first-candidate-payload",
        deployable=False,
        installer_bytes=installer_bytes,
    )
    replacement = _approved_bundle(
        tmp_path / "replacement-candidate",
        approval_reference="unused",
        source_commit="c" * 40,
        marker=b"replacement-payload",
        deployable=False,
        installer_bytes=installer_bytes,
    )
    expected_candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()

    real_open = approval_module.open_verified_bundle
    swapped = False

    def open_then_replace_candidate(bundle, **kwargs):
        nonlocal swapped
        result = real_open(bundle, **kwargs)
        if not swapped:
            swapped = True
            replacement.replace(candidate)
        return result

    monkeypatch.setattr(approval_module, "open_verified_bundle", open_then_replace_candidate)
    monkeypatch.setattr(approval_module, "validate_runtime_artifacts", lambda _payload, _manifest: None)
    monkeypatch.setattr(release_bundle, "validate_runtime_artifacts", lambda _payload, _manifest: None)
    monkeypatch.setattr(approval_module, "prepare_runtime", lambda _root, _manifest: None)

    approved = tmp_path / "approved.tar"
    result = approval_module.approve_bundle(
        candidate,
        approved,
        approval_reference="approval-51h",
        expected_candidate_sha256=expected_candidate_sha,
        expected_installer_sha256=hashlib.sha256(installer_bytes).hexdigest(),
        expected_source_commit="c" * 40,
    )

    assert swapped is True
    assert result["release_approval"]["candidate_sha256"] == expected_candidate_sha

    approved_manifest, approved_payload = read_bundle(approved)
    assert approved_manifest["release_approval"]["candidate_sha256"] == expected_candidate_sha

    with tarfile.open(fileobj=io.BytesIO(approved_payload), mode="r:") as archive:
        marker = archive.extractfile(f"clientflow-{VERSION}/marker").read()
    assert marker == b"first-candidate-payload"


def test_51h_publication_uses_source_build_identity_not_runtime_selection_catalog() -> None:
    assert publication._source_release_identity() == (VERSION, SEQUENCE, RELEASE_ID)
    source = (ROOT / "scripts/publish_clientflow_release.py").read_text(encoding="utf-8")
    assert "_source_release_identity" in source
    assert "resolve_release" not in source
    assert "clientflow_release_catalog" not in source


def test_51h_publication_rejects_bundle_from_other_source_release_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = _approved_bundle(
        tmp_path / "source",
        approval_reference="approval-first",
        source_commit="c" * 40,
        marker=b"approved-bytes",
    )
    expected_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(release_bundle, "validate_runtime_artifacts", lambda _payload, _manifest: None)
    monkeypatch.setattr(
        publication,
        "_source_release_identity",
        lambda: ("1.3.3", 1204, "clientflow-1.3.3-seq-1204"),
    )

    artifact_dir = tmp_path / "artifact-store"
    artifact_dir.mkdir(mode=0o700)
    with pytest.raises(RuntimeError, match="canonical source VERSION"):
        publication.publish(
            source,
            artifact_dir,
            expected_bundle_sha256=expected_sha,
            expected_approval_reference="approval-first",
            expected_source_commit="c" * 40,
        )


def test_51h_publication_source_uses_pinned_bundle_and_directory_descriptors():
    source = (ROOT / "scripts/publish_clientflow_release.py").read_text(encoding="utf-8")
    assert "open_verified_bundle" in source
    assert "source_handle.fileno()" in source
    assert "src_dir_fd=directory_fd" in source
    assert "dst_dir_fd=directory_fd" in source
    assert "sha256_file(bundle" not in source
    assert 'bundle.open("rb")' not in source

    approval_source = (ROOT / "client/release/lib/clientflow_release/approval.py").read_text(encoding="utf-8")
    assert "open_verified_bundle(" in approval_source
    assert "read_bundle(candidate_bundle)" not in approval_source
    assert "sha256_file(candidate_bundle" not in approval_source
