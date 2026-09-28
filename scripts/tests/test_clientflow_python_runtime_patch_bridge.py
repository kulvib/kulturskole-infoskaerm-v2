from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import runtime_artifacts, transaction  # noqa: E402
from clientflow_release_format.archive import FileRegion  # noqa: E402
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
from clientflow_release_format.manifest import ManifestError, validate_manifest  # noqa: E402


def _manifest(runtime_python: str) -> dict:
    version = "1.3.27"
    release_sequence = 1228
    installer = b"installer"
    payload = b"payload"
    return {
        "manifest_schema": MANIFEST_SCHEMA,
        "product": PRODUCT,
        "channel": CHANNEL,
        "version": version,
        "release_id": f"clientflow-{version}-seq-{release_sequence}",
        "release_sequence": release_sequence,
        "source_date_epoch": 1_797_000_000,
        "artifact_type": ARTIFACT_TYPE_RUNTIME_RELEASE,
        "install_modes": [INSTALL_MODE_FRESH, INSTALL_MODE_UPDATE],
        "deployable": False,
        "integrity_algorithm": INTEGRITY_ALGORITHM,
        "release_approval": {"reference": None, "candidate_sha256": None},
        "source": {"commit": "a" * 40, "dirty": False},
        "fresh_installer": {
            "file": f"clientflow-installer-{version}.pyz",
            "format": "python-zipapp",
            "size": len(installer),
            "sha256": hashlib.sha256(installer).hexdigest(),
        },
        "payload": {
            "file": "clientflow-payload.tar",
            "format": "tar",
            "root": f"clientflow-{version}",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "runtime": {
            "python": runtime_python,
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


def _python_runtime_tar(path: Path, version: str) -> None:
    root = f"python-{version}"
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
        for directory in (root, f"{root}/bin"):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = info.gid = 0
            archive.addfile(info)
        body = b"#!/bin/sh\n"
        info = tarfile.TarInfo(f"{root}/bin/python3")
        info.size = len(body)
        info.mode = 0o755
        info.uid = info.gid = 0
        archive.addfile(info, io.BytesIO(body))


def _prepared_release_tree(root: Path, *, manifest: dict, ready_python: str) -> None:
    required = (
        "VERSION",
        "client-runtime/systemd/clientflow.target",
        "client-runtime/sysusers.d/clientflow.conf",
        "client-runtime/tmpfiles.d/clientflow.conf",
        "release/updater/clientflow-updater.pyz",
        "release/lib/clientflow_release/transaction.py",
        "release/lib/clientflow_release_format/manifest.py",
    )
    for relative in required:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest["version"] if relative == "VERSION" else "x", encoding="utf-8")

    helper = root / "release/bin/clientflow-release-transaction"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("#!/opt/clientflow/active/runtime/bin/python\n", encoding="utf-8")

    runtime_python = root / "runtime/bin/python"
    runtime_python.parent.mkdir(parents=True, exist_ok=True)
    runtime_python.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_python.chmod(0o755)

    ready = {
        "schema_version": 1,
        "version": manifest["version"],
        "release_id": manifest["release_id"],
        "release_sequence": manifest["release_sequence"],
        "python": ready_python,
    }
    ready_path = root / "release-ready.json"
    ready_path.write_text(json.dumps(ready), encoding="utf-8")
    ready_path.chmod(0o444)


def test_bridge_manifest_keeps_31314_and_accepts_later_313_patch_only() -> None:
    validate_manifest(_manifest("3.13.14"), require_deployable=False)
    validate_manifest(_manifest("3.13.15"), require_deployable=False)
    validate_manifest(_manifest("3.13.99"), require_deployable=False)

    for incompatible in ("3.13.13", "3.14.0", "3.12.99", "3.13", "3.13.015", "3.13.15rc1"):
        with pytest.raises(ManifestError, match="Python 3.13 patch"):
            validate_manifest(_manifest(incompatible), require_deployable=False)


def test_bridge_runtime_archive_root_is_bound_to_manifest_declared_patch(tmp_path: Path) -> None:
    runtime_tar = tmp_path / "python-runtime-amd64.tar"
    _python_runtime_tar(runtime_tar, "3.13.15")
    descriptor = os.open(runtime_tar, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        region = FileRegion(descriptor, 0, runtime_tar.stat().st_size)
        runtime_artifacts._validate_python_runtime(region, version="3.13.15")
        with pytest.raises(runtime_artifacts.RuntimeArtifactError, match="ugyldig sti"):
            runtime_artifacts._validate_python_runtime(region, version="3.13.14")
    finally:
        os.close(descriptor)


def test_bridge_release_ready_python_is_bound_to_manifest_runtime(tmp_path: Path) -> None:
    manifest = _manifest("3.13.15")
    good = tmp_path / "good"
    _prepared_release_tree(good, manifest=manifest, ready_python="3.13.15")
    transaction._validate_prepared_release_tree(good, manifest)

    bad = tmp_path / "bad"
    _prepared_release_tree(bad, manifest=manifest, ready_python="3.13.14")
    with pytest.raises(transaction.TransactionError, match="release-ready.json matcher ikke manifestet: python"):
        transaction._validate_prepared_release_tree(bad, manifest)


def test_bridge_does_not_change_current_runtime_pin_before_bridge_release() -> None:
    release_input = json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))
    runtime_lock = json.loads((ROOT / "client/release/runtime-platform-inputs.lock.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "client/runtime/pyproject.toml").read_text(encoding="utf-8")

    assert release_input["runtime_python"] == "3.13.14"
    assert runtime_lock["runtime_python"] == "3.13.14"
    assert 'requires-python = "==3.13.14"' in pyproject

    for relative in (
        "backend/clientflow_release_format/manifest.py",
        "client/release/lib/clientflow_release/runtime_artifacts.py",
        "client/release/lib/clientflow_release/runtime_prepare.py",
        "client/release/lib/clientflow_release/transaction.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert '"3.13.14"' not in source
        assert "python-3.13.14" not in source
