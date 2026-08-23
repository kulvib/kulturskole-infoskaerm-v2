from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import cli as installer_cli  # noqa: E402
from clientflow_release.enrollment import EnrollmentError, EnrollmentHTTPError, validate_fresh_install_binding  # noqa: E402


BINDING = {
    "release_id": "clientflow-1.3.3-seq-1204",
    "version": "1.3.3",
    "release_sequence": 1204,
    "bundle_sha256": "a" * 64,
    "bundle_size": 80123456,
    "release_approval_reference": "clientflow-1.3.3-seq-1204/test-approval",
    "release_candidate_sha256": "b" * 64,
    "source_commit": "c" * 40,
}


def test_installer_state_schema_persists_complete_non_secret_release_binding():
    assert installer_cli.INSTALL_STATE_SCHEMA == 2
    manifest = {
        "release_id": BINDING["release_id"],
        "version": BINDING["version"],
        "release_sequence": BINDING["release_sequence"],
        "release_approval": {
            "reference": BINDING["release_approval_reference"],
            "candidate_sha256": BINDING["release_candidate_sha256"],
        },
        "source": {"commit": BINDING["source_commit"], "dirty": False},
    }
    actual = installer_cli._fresh_install_binding(
        manifest,
        bundle_size=BINDING["bundle_size"],
        bundle_sha256=BINDING["bundle_sha256"],
    )
    assert actual == BINDING


def test_release_binding_validator_rejects_incomplete_or_incoherent_identity():
    incomplete = dict(BINDING)
    incomplete.pop("source_commit")
    with pytest.raises(EnrollmentError, match="forkert schema"):
        validate_fresh_install_binding(incomplete)

    incoherent = dict(BINDING)
    incoherent["release_sequence"] = 1205
    with pytest.raises(EnrollmentError, match="matcher ikke"):
        validate_fresh_install_binding(incoherent)


def test_install_parser_allows_receipt_resume_without_one_time_authorities():
    args = installer_cli.build_parser().parse_args(
        [
            "install",
            "--bundle", "/tmp/bundle.tar",
            "--expected-bundle-sha256", "a" * 64,
            "--backend-url", "https://display.example.invalid",
            "--kiosk-user", "kiosk",
        ]
    )
    assert args.enrollment_code is None
    assert args.fresh_install_authorization is None


def test_new_install_requires_code_and_authorization_before_clientflow_state_mutation():
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    start = source.index("def install_fresh(")
    end = source.index("def _common_transaction_parser", start)
    install = source[start:end]

    new_state = install.index("else:\n        # A brand-new consuming transaction")
    code_gate = install.index("Ny fresh install kræver en one-time enrollment code", new_state)
    auth_gate = install.index("Ny fresh install kræver fresh-install authorization", new_state)
    state_root = install.index("ensure_real_directory(layout.state_root", new_state)
    assert new_state < code_gate < auth_gate < state_root


def test_install_state_never_persists_one_time_code_or_authorization():
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    start = source.index('install_state = {')
    end = source.index('atomic_write_json(state_path, install_state', start)
    initialized_state = source[start:end]
    assert '"fresh_install_binding": binding' in initialized_state
    assert '"enrollment_code"' not in initialized_state
    assert '"fresh_install_authorization"' not in initialized_state


def test_installer_carries_same_binding_into_claim_and_complete_resume_transactions():
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    assert "fresh_install_binding=binding" in source
    claim_index = source.index("response = claim(")
    complete_index = source.index("complete(\n", claim_index)
    assert source.index("fresh_install_binding=binding", claim_index) < complete_index
    assert "fresh_install_binding=binding" in source[complete_index:complete_index + 360]


def _fresh_install_args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        root=str(tmp_path),
        kiosk_user="kiosk",
        backend_url="https://display.example.invalid",
        bundle=tmp_path / "approved.tar",
        expected_bundle_sha256=BINDING["bundle_sha256"],
        enrollment_code="CF-TEST-TEST-TEST",
        fresh_install_authorization="signed-authorization",
        name=None,
        locality=None,
        ca_file=None,
    )


def _patch_new_install_primitives(monkeypatch, *, claim_error: Exception):
    manifest = {
        "release_id": BINDING["release_id"],
        "version": BINDING["version"],
        "release_sequence": BINDING["release_sequence"],
        "release_approval": {
            "reference": BINDING["release_approval_reference"],
            "candidate_sha256": BINDING["release_candidate_sha256"],
        },
        "source": {"commit": BINDING["source_commit"], "dirty": False},
    }
    monkeypatch.setattr(
        installer_cli,
        "_verify_expected_bundle_identity",
        lambda *_args, **_kwargs: (BINDING["bundle_size"], BINDING["bundle_sha256"]),
    )
    monkeypatch.setattr(
        installer_cli,
        "verify_bundle",
        lambda *_args, **_kwargs: (manifest, BINDING["bundle_size"], BINDING["bundle_sha256"]),
    )

    def fake_system_key(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("system-private", encoding="ascii")
        path.chmod(0o600)
        return "system-public", "system-key"

    def fake_update_key(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("update-private", encoding="ascii")
        path.chmod(0o600)
        return "update-public", "update-key", {}, "thumbprint"

    monkeypatch.setattr(installer_cli, "generate_system_key", fake_system_key)
    monkeypatch.setattr(installer_cli, "generate_update_key", fake_update_key)
    monkeypatch.setattr(installer_cli, "claim", lambda **_kwargs: (_ for _ in ()).throw(claim_error))


def test_first_claim_definite_rejection_restores_clean_client_state(monkeypatch, tmp_path):
    _patch_new_install_primitives(
        monkeypatch,
        claim_error=EnrollmentHTTPError(409, "Fresh-install release-binding matcher ikke authorization"),
    )
    staged = []
    monkeypatch.setattr(installer_cli, "stage_bundle", lambda *_args, **_kwargs: staged.append("stage"))
    monkeypatch.setattr(
        installer_cli, "install_staged_definitions", lambda *_args, **_kwargs: staged.append("definitions")
    )

    with pytest.raises(EnrollmentHTTPError) as exc:
        installer_cli.install_fresh(_fresh_install_args(tmp_path))

    assert exc.value.status_code == 409
    assert staged == []
    assert not (tmp_path / "etc/clientflow").exists()
    assert not (tmp_path / "var/lib/clientflow").exists()
    assert not (tmp_path / "opt/clientflow").exists()


def test_first_claim_ambiguous_server_failure_keeps_only_resume_material(monkeypatch, tmp_path):
    _patch_new_install_primitives(
        monkeypatch,
        claim_error=EnrollmentHTTPError(503, "ambiguous backend failure"),
    )
    staged = []
    monkeypatch.setattr(installer_cli, "stage_bundle", lambda *_args, **_kwargs: staged.append("stage"))
    monkeypatch.setattr(
        installer_cli, "install_staged_definitions", lambda *_args, **_kwargs: staged.append("definitions")
    )

    with pytest.raises(EnrollmentHTTPError) as exc:
        installer_cli.install_fresh(_fresh_install_args(tmp_path))

    assert exc.value.status_code == 503
    assert staged == []
    assert (tmp_path / "var/lib/clientflow/release/install-state.json").is_file()
    assert (tmp_path / "etc/clientflow/system-private-key.pem").is_file()
    assert (tmp_path / "etc/clientflow/update/private-key.pem").is_file()
    assert not (tmp_path / "opt/clientflow").exists()


def test_first_claim_precedes_release_staging_and_managed_definitions():
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    start = source.index("def install_fresh(")
    end = source.index("def _common_transaction_parser", start)
    install = source[start:end]
    claim_index = install.index("response = claim(")
    assert claim_index < install.index("stage_bundle(", claim_index)
    assert claim_index < install.index("install_staged_definitions(", claim_index)
    assert "except EnrollmentHTTPError as exc:" in install
    assert "_cleanup_new_install_preclaim_state(layout, install_id=install_id)" in install
