from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from clientflow_release_format.constants import (
    ARTIFACT_TYPE_RUNTIME_RELEASE,
    CHANNEL,
    DOMAIN_NAMES,
    INSTALL_MODE_FRESH,
    INSTALL_MODE_UPDATE,
    INTEGRITY_ALGORITHM,
    MANIFEST_SCHEMA,
    PRODUCT,
)
from service1.clientflow_releases import ClientFlowArtifactUnavailable, deployment_release_snapshot


def _published_bundle(root: Path, *, release_id: str = "clientflow-1.3.0-seq-1300") -> tuple[Path, dict]:
    version = "1.3.0"
    sequence = 1300
    payload_path = root / "payload.tar"
    with tarfile.open(payload_path, "w", format=tarfile.PAX_FORMAT) as archive:
        directory = tarfile.TarInfo(f"clientflow-{version}")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        directory.uid = directory.gid = 0
        archive.addfile(directory)
        raw = b"1.3.0\n"
        member = tarfile.TarInfo(f"clientflow-{version}/VERSION")
        member.size = len(raw)
        member.mode = 0o644
        member.uid = member.gid = 0
        archive.addfile(member, io.BytesIO(raw))
    payload = payload_path.read_bytes()
    manifest = {
        "manifest_schema": MANIFEST_SCHEMA,
        "product": PRODUCT,
        "channel": CHANNEL,
        "version": version,
        "release_id": release_id,
        "release_sequence": sequence,
        "source_date_epoch": 1_780_000_000,
        "artifact_type": ARTIFACT_TYPE_RUNTIME_RELEASE,
        "install_modes": [INSTALL_MODE_FRESH, INSTALL_MODE_UPDATE],
        "deployable": True,
        "integrity_algorithm": INTEGRITY_ALGORITHM,
        "release_approval": {"reference": "approval-1300", "candidate_sha256": "b" * 64},
        "source": {"commit": "c" * 40, "dirty": False},
        "payload": {
            "file": "clientflow-payload.tar",
            "format": "tar",
            "root": f"clientflow-{version}",
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
    bundle = root / f"{release_id}.tar"
    with tarfile.open(bundle, "w", format=tarfile.PAX_FORMAT) as archive:
        manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
        for name, raw in (("manifest.json", manifest_bytes), ("clientflow-payload.tar", payload)):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = 0o644
            member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(raw))
    return bundle, manifest


def test_deployment_release_snapshot_is_derived_from_published_approved_bytes(tmp_path, monkeypatch):
    bundle, _manifest = _published_bundle(tmp_path)
    monkeypatch.setenv("CLIENTFLOW_RELEASE_ARTIFACT_DIR", str(tmp_path))
    size = bundle.stat().st_size
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

    value = deployment_release_snapshot({
        "version": "1.3.0",
        "release_id": "clientflow-1.3.0-seq-1300",
        "release_sequence": 1300,
    })
    assert value == {
        "target_release_id": "clientflow-1.3.0-seq-1300",
        "bundle_sha256": digest,
        "bundle_size": size,
        "release_approval_reference": "approval-1300",
        "release_candidate_sha256": "b" * 64,
        "source_commit": "c" * 40,
    }


def test_deployment_release_snapshot_fails_closed_without_published_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_RELEASE_ARTIFACT_DIR", str(tmp_path))
    with pytest.raises(ClientFlowArtifactUnavailable, match="artifact mangler"):
        deployment_release_snapshot({
            "version": "1.2.0",
            "release_id": "clientflow-1.2.0-seq-1200",
            "release_sequence": 1200,
        })


def test_deployment_release_snapshot_rejects_catalog_artifact_identity_mismatch(tmp_path, monkeypatch):
    _published_bundle(tmp_path)
    monkeypatch.setenv("CLIENTFLOW_RELEASE_ARTIFACT_DIR", str(tmp_path))
    with pytest.raises(ClientFlowArtifactUnavailable, match="version matcher ikke"):
        deployment_release_snapshot({
            "version": "9.9.9",
            "release_id": "clientflow-1.3.0-seq-1300",
            "release_sequence": 1300,
        })
