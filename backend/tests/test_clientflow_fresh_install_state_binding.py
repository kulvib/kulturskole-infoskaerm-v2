from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import io
import json
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
            "--kiosk-user", "clientflow-kiosk",
        ]
    )
    assert args.fresh_install_authority_stdin is False
    assert not hasattr(args, "enrollment_code")
    assert not hasattr(args, "fresh_install_authorization")




def test_install_parser_rejects_secret_bearing_legacy_argv():
    with pytest.raises(SystemExit):
        installer_cli.build_parser().parse_args(
            [
                "install",
                "--bundle", "/tmp/bundle.tar",
                "--expected-bundle-sha256", "a" * 64,
                "--backend-url", "https://display.example.invalid",
                "--kiosk-user", "clientflow-kiosk",
                "--enrollment-code", "CF-SECRET",
            ]
        )


def test_new_install_authorities_are_read_from_bounded_stdin(monkeypatch):
    fake_stdin = io.TextIOWrapper(
        io.BytesIO(b"CF-TEST-TEST-TEST\nsigned-authorization\n"),
        encoding="utf-8",
    )
    monkeypatch.setattr(installer_cli.sys, "stdin", fake_stdin)
    args = SimpleNamespace(fresh_install_authority_stdin=True)
    assert installer_cli._fresh_install_authorities(args) == (
        "CF-TEST-TEST-TEST",
        "signed-authorization",
    )


def test_new_install_requires_code_and_authorization_before_clientflow_state_mutation():
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    start = source.index("def install_fresh(")
    end = source.index("def _common_transaction_parser", start)
    install = source[start:end]

    new_state = install.index("else:\n        # A brand-new consuming transaction")
    code_gate = install.index("Ny fresh install kræver en one-time enrollment code via stdin", new_state)
    auth_gate = install.index("Ny fresh install kræver fresh-install authorization via stdin", new_state)
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
        kiosk_user="clientflow-kiosk",
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


def _write_pending_install_state(tmp_path: Path) -> None:
    state_path = tmp_path / "var/lib/clientflow/release/install-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": installer_cli.INSTALL_STATE_SCHEMA,
                "fresh_install_binding": BINDING,
                "install_id": "pending-resume-install-id",
                "backend_url": "https://display.example.invalid",
                "kiosk_user": "clientflow-kiosk",
                "status": "pending_manual_activation",
            }
        ),
        encoding="utf-8",
    )
    state_path.chmod(0o600)


def _patch_existing_install_bundle(monkeypatch) -> None:
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


def test_pending_install_resume_rejects_active_release_before_updater_mutation(monkeypatch, tmp_path):
    _write_pending_install_state(tmp_path)
    _patch_existing_install_bundle(monkeypatch)
    monkeypatch.setattr(
        installer_cli,
        "status",
        lambda _layout: {
            "active_release_id": BINDING["release_id"],
            "active_symlink_release_id": BINDING["release_id"],
            "activation_intent": None,
        },
    )
    monkeypatch.setattr(
        installer_cli,
        "install_stable_updater_host",
        lambda *_args, **_kwargs: pytest.fail(
            "post-activation install resume must reject before updater mutation"
        ),
    )

    with pytest.raises(RuntimeError, match="allerede aktiveret eller igangværende activation"):
        installer_cli.install_fresh(_fresh_install_args(tmp_path))


def test_pending_install_resume_rejects_committed_activation_intent_before_updater_mutation(
    monkeypatch, tmp_path
):
    _write_pending_install_state(tmp_path)
    _patch_existing_install_bundle(monkeypatch)
    monkeypatch.setattr(
        installer_cli,
        "status",
        lambda _layout: {
            "active_release_id": None,
            "active_symlink_release_id": None,
            "activation_intent": {
                "release_id": BINDING["release_id"],
                "previous_release_id": None,
            },
        },
    )
    monkeypatch.setattr(
        installer_cli,
        "install_stable_updater_host",
        lambda *_args, **_kwargs: pytest.fail(
            "activation-intent recovery must reject before updater mutation"
        ),
    )

    with pytest.raises(RuntimeError, match="allerede aktiveret eller igangværende activation"):
        installer_cli.install_fresh(_fresh_install_args(tmp_path))


def test_pending_install_resume_still_repairs_updater_host_when_release_is_inactive(
    monkeypatch, tmp_path
):
    _write_pending_install_state(tmp_path)
    _patch_existing_install_bundle(monkeypatch)
    monkeypatch.setattr(
        installer_cli,
        "status",
        lambda _layout: {
            "active_release_id": None,
            "active_symlink_release_id": None,
            "activation_intent": None,
        },
    )
    calls: list[str] = []
    monkeypatch.setattr(
        installer_cli,
        "install_stable_updater_host",
        lambda *_args, **_kwargs: calls.append("updater-host"),
    )
    monkeypatch.setattr(
        installer_cli,
        "_validate_inactive_install",
        lambda *_args, **_kwargs: calls.append("validate-inactive"),
    )

    result = installer_cli.install_fresh(_fresh_install_args(tmp_path))

    assert result["status"] == "pending_manual_activation"
    assert calls == ["updater-host", "validate-inactive"]
