from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import builder as builder_module  # noqa: E402
from clientflow_release_format.bundle import BundleFormatError, verify_bundle_structure  # noqa: E402
from clientflow_release_format.constants import MANIFEST_SCHEMA  # noqa: E402


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


def test_51i_schema8_bundle_physically_contains_exact_fresh_installer(tmp_path, monkeypatch):
    result = _candidate_build(tmp_path, monkeypatch)
    bundle = result["bundle"]
    installer = result["installer"].read_bytes()
    manifest = result["manifest"]

    assert MANIFEST_SCHEMA == 8
    with tarfile.open(bundle, "r:", format=tarfile.PAX_FORMAT) as archive:
        names = [member.name for member in archive.getmembers()]
        assert names == [
            "manifest.json",
            "clientflow-payload.tar",
            manifest["fresh_installer"]["file"],
        ]
        embedded = archive.extractfile(manifest["fresh_installer"]["file"]).read()

    assert embedded == installer
    assert len(embedded) == manifest["fresh_installer"]["size"]
    assert hashlib.sha256(embedded).hexdigest() == manifest["fresh_installer"]["sha256"]


def test_51i_bundle_verification_rejects_missing_embedded_installer(tmp_path, monkeypatch):
    result = _candidate_build(tmp_path, monkeypatch)
    source = result["bundle"]
    broken = tmp_path / "missing-installer.tar"

    with tarfile.open(source, "r:") as archive, tarfile.open(broken, "w", format=tarfile.PAX_FORMAT) as out:
        for member in archive.getmembers():
            if member.name == result["manifest"]["fresh_installer"]["file"]:
                continue
            data = archive.extractfile(member).read()
            clone = tarfile.TarInfo(member.name)
            clone.size = len(data)
            clone.mode = member.mode
            clone.uid = member.uid
            clone.gid = member.gid
            clone.mtime = member.mtime
            out.addfile(clone, io.BytesIO(data))

    with pytest.raises(BundleFormatError, match="fresh installer"):
        verify_bundle_structure(broken, require_deployable=False)


def test_51i_bundle_verification_rejects_tampered_embedded_installer(tmp_path, monkeypatch):
    result = _candidate_build(tmp_path, monkeypatch)
    source = result["bundle"]
    broken = tmp_path / "tampered-installer.tar"

    with tarfile.open(source, "r:") as archive, tarfile.open(broken, "w", format=tarfile.PAX_FORMAT) as out:
        for member in archive.getmembers():
            data = archive.extractfile(member).read()
            if member.name == result["manifest"]["fresh_installer"]["file"]:
                data += b"tampered"
            clone = tarfile.TarInfo(member.name)
            clone.size = len(data)
            clone.mode = member.mode
            clone.uid = member.uid
            clone.gid = member.gid
            clone.mtime = member.mtime
            out.addfile(clone, io.BytesIO(data))

    with pytest.raises(BundleFormatError, match="Fresh installerens størrelse eller SHA-256"):
        verify_bundle_structure(broken, require_deployable=False)


def test_51i_canonical_handoff_uses_pinned_bundle_and_private_root_bootstrap():
    procedure = (ROOT / "CLIENTFLOW_RELEASE_PROCEDURE.md").read_text(encoding="utf-8")
    approval = (ROOT / "client/release/lib/clientflow_release/approval.py").read_text(encoding="utf-8")

    assert 'exec {BUNDLE_FD}<"$BUNDLE_PATH"' in procedure
    assert 'BUNDLE_FD_PATH="/proc/$$/fd/$BUNDLE_FD"' in procedure
    assert '/usr/bin/tar -xOf "$BUNDLE_FD_PATH" "$INSTALLER_FILE"' in procedure
    assert 'BOOTSTRAP_DIR/clientflow-approved.tar' in procedure
    assert 'sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" verify' in procedure
    assert 'INSTALL_ARGS=(' in procedure
    assert 'install\n  --bundle "$BOOTSTRAP_BUNDLE"' in procedure
    assert '--name "$CLIENTFLOW_CLIENT_NAME"' in procedure
    assert 'sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" "${INSTALL_ARGS[@]}"' in procedure

    first_hash = procedure.index('"$BUNDLE_FD_PATH" |')
    extraction = procedure.index('/usr/bin/tar -xOf "$BUNDLE_FD_PATH" "$INSTALLER_FILE"')
    execution = procedure.index('sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" verify')
    assert first_hash < extraction < execution

    assert 'parser.add_argument("--installer"' not in approval
    assert "read_bundle_artifact_regions_fd" in approval


def _section5_bootstrap_block(procedure: str) -> str:
    section = procedure.split("## 5. Materialize a pinned fresh-install bootstrap before executing installer code", 1)[1]
    section = section.split("## 6. Fresh installation", 1)[0]
    match = re.search(r"```bash\n(.*?)\n```", section, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_51i_bootstrap_reuses_handoff_trust_values_and_preserves_interactive_shell():
    procedure = (ROOT / "CLIENTFLOW_RELEASE_PROCEDURE.md").read_text(encoding="utf-8")
    block = _section5_bootstrap_block(procedure)

    assert 'BUNDLE="/path/to/downloaded-approved-bundle.tar"' not in block
    assert "APPROVED_BUNDLE_SHA256='<APPROVED_BUNDLE_SHA256>'" not in block
    assert 'test -n "${BUNDLE:-}"' in block
    assert 'test -n "${APPROVED_BUNDLE_SHA256:-}"' in block
    assert "clientflow_materialize_fresh_bootstrap() {" in block
    assert '*) echo "Ugyldig materialiseret installersti" >&2; return 1 ;;' in block

    # exit(1) is valid only inside the deliberately isolated root child shell.
    outer = block.split("<<'CLIENTFLOW_BOOTSTRAP'", 1)[0] + block.split("CLIENTFLOW_BOOTSTRAP", 2)[-1]
    assert "exit 1" not in outer

    result = subprocess.run(
        ["/usr/bin/bash", "-n"],
        input=block,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
