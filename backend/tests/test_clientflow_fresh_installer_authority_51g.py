from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import approval as approval_module  # noqa: E402
from clientflow_release import builder as builder_module  # noqa: E402
from clientflow_release.archive import read_bundle  # noqa: E402
from clientflow_release.approval import ApprovalError  # noqa: E402
from clientflow_release.crypto import sha256_file  # noqa: E402
from clientflow_release_format.constants import MANIFEST_SCHEMA  # noqa: E402
from clientflow_release_format.manifest import ManifestError, validate_manifest  # noqa: E402


CURRENT_VERSION = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
CURRENT_SEQUENCE = int(json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))["release_sequence"])
CURRENT_RELEASE_ID = f"clientflow-{CURRENT_VERSION}-seq-{CURRENT_SEQUENCE}"


def _candidate_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(
        builder_module,
        "_git",
        lambda _repo, *args: (
            "a" * 40 if args == ("rev-parse", "HEAD") else "" if args == ("status", "--porcelain") else "1787200000"
        ),
    )

    def fake_payload(_repo, output, *, version, epoch, runtime_inputs, updater_pyz):
        del _repo, runtime_inputs, updater_pyz
        with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as archive:
            root = tarfile.TarInfo(f"clientflow-{version}")
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            root.uid = root.gid = 0
            root.mtime = epoch
            archive.addfile(root)
        return True, []

    monkeypatch.setattr(builder_module, "_create_payload", fake_payload)
    monkeypatch.setattr(builder_module, "_create_updater_pyz", lambda _repo, output, *, epoch: output.write_bytes(b"updater"))
    return builder_module.build(ROOT, tmp_path, runtime_inputs=None, allow_dirty=False)


def test_51g_manifest_schema_requires_exact_fresh_installer_descriptor(tmp_path, monkeypatch):
    result = _candidate_build(tmp_path, monkeypatch)
    manifest = result["manifest"]
    installer = result["installer"]
    size, digest = sha256_file(installer)

    assert MANIFEST_SCHEMA == 8
    assert manifest["fresh_installer"] == {
        "file": f"clientflow-installer-{CURRENT_VERSION}.pyz",
        "format": "python-zipapp",
        "size": size,
        "sha256": digest,
    }
    validate_manifest(manifest, require_deployable=False)

    missing = dict(manifest)
    missing.pop("fresh_installer")
    with pytest.raises(ManifestError, match="fresh_installer"):
        validate_manifest(missing, require_deployable=False)

    wrong = dict(manifest)
    wrong["fresh_installer"] = {**manifest["fresh_installer"], "sha256": "0" * 64}
    validate_manifest(wrong, require_deployable=False)


def test_51g_approval_rejects_installer_hash_not_bound_by_candidate(tmp_path, monkeypatch):
    result = _candidate_build(tmp_path, monkeypatch)
    candidate = result["bundle"]
    installer = result["installer"]
    _, candidate_sha = sha256_file(candidate)
    _, installer_sha = sha256_file(installer)

    with pytest.raises(ApprovalError, match="eksplicit godkendte hash"):
        approval_module.approve_bundle(
            candidate,
            tmp_path / "approved.tar",
            approval_reference="step-51g-test",
            expected_candidate_sha256=candidate_sha,
            expected_installer_sha256="0" * 64,
            expected_source_commit="a" * 40,
        )

    assert installer_sha == result["manifest"]["fresh_installer"]["sha256"]


def test_51g_approved_bundle_preserves_installer_authority(tmp_path, monkeypatch):
    result = _candidate_build(tmp_path, monkeypatch)
    candidate = result["bundle"]
    installer = result["installer"]
    _, candidate_sha = sha256_file(candidate)
    _, installer_sha = sha256_file(installer)

    monkeypatch.setattr(approval_module, "validate_runtime_artifacts", lambda payload, manifest: None)
    monkeypatch.setattr(approval_module, "extract_verified_payload", lambda payload, target, *, expected_root: target)
    monkeypatch.setattr(approval_module, "prepare_runtime", lambda release_root, manifest: None)
    monkeypatch.setattr(approval_module, "verify_bundle", lambda bundle, require_deployable=True: read_bundle(bundle))

    approved = tmp_path / f"{CURRENT_RELEASE_ID}-approved.tar"
    approval_module.approve_bundle(
        candidate,
        approved,
        approval_reference="step-51g-test",
        expected_candidate_sha256=candidate_sha,
        expected_installer_sha256=installer_sha,
        expected_source_commit="a" * 40,
    )
    approved_manifest, _payload = read_bundle(approved)
    assert approved_manifest["deployable"] is True
    assert approved_manifest["release_approval"]["candidate_sha256"] == candidate_sha
    assert approved_manifest["fresh_installer"] == result["manifest"]["fresh_installer"]
    assert approved_manifest["fresh_installer"]["sha256"] == installer_sha


def test_51g_candidate_and_fresh_installer_are_byte_reproducible(tmp_path, monkeypatch):
    first = _candidate_build(tmp_path / "first", monkeypatch)
    first_bundle = first["bundle"].read_bytes()
    first_installer = first["installer"].read_bytes()

    second = _candidate_build(tmp_path / "second", monkeypatch)
    assert second["bundle"].read_bytes() == first_bundle
    assert second["installer"].read_bytes() == first_installer
    assert second["manifest"]["fresh_installer"] == first["manifest"]["fresh_installer"]


def test_51g_release_procedure_requires_explicit_installer_hash_approval():
    approval_source = (ROOT / "client/release/lib/clientflow_release/approval.py").read_text(encoding="utf-8")
    assert "--expected-installer-sha256" in approval_source
    assert "read_bundle_artifacts_fd" in approval_source
    assert 'manifest.get("fresh_installer")' in approval_source

