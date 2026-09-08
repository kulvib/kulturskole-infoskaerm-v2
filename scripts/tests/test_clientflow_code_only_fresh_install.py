from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "client/bootstrap/clientflow-fresh-install"
ENROLLMENT = ROOT / "backend/service1/routers/enrollment.py"
MODELS = ROOT / "backend/service1/models.py"
MIGRATION = ROOT / "backend/migrations/versions/20260908_55a_enroll_binding.py"
FRONTEND = ROOT / "frontend/src/pages/adminpages/EnrollmentTokensPage.jsx"


def _load_helper():
    loader = importlib.machinery.SourceFileLoader("clientflow_fresh_install_bootstrap", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_enrollment_persists_creation_time_release_binding_and_bootstrap_uses_token_binding():
    source = ENROLLMENT.read_text(encoding="utf-8")
    model = MODELS.read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8")

    for field in (
        "fresh_install_release_id", "fresh_install_version", "fresh_install_release_sequence",
        "fresh_install_bundle_sha256", "fresh_install_bundle_size", "fresh_install_approval_reference",
        "fresh_install_candidate_sha256", "fresh_install_source_commit",
    ):
        assert field in model
        assert field in migration
        assert f"{field}=" in source

    bootstrap = source[source.index('def fresh_install_bootstrap('):source.index('@router.post("/enrollment/fresh-install-artifact")')]
    assert "_active_token_for_code" in bootstrap
    assert "_token_fresh_install_binding(token)" in bootstrap
    assert "issue_fresh_install_authorization" in bootstrap
    assert "fresh_install_release_snapshot" not in bootstrap
    assert "resolve_fresh_install_release" not in bootstrap


def test_historical_unbound_codes_fail_closed_instead_of_rebinding():
    source = ENROLLMENT.read_text(encoding="utf-8")
    helper = source[source.index("def _token_fresh_install_binding"):source.index('@router.post("/admin/enrollment-tokens"')]
    assert "mangler en durable exact-release binding" in helper
    assert "tilbagekaldes og oprettes igen" in helper
    assert "fresh_install_release_snapshot" not in helper


def test_admin_response_no_longer_exposes_signed_authorization():
    source = ENROLLMENT.read_text(encoding="utf-8")
    schema = source[source.index("class EnrollmentTokenCreated"):source.index("class FreshInstallBootstrapRequest")]
    assert "fresh_install_authorization" not in schema
    page = FRONTEND.read_text(encoding="utf-8")
    assert "Kopiér authorization" not in page
    assert "Kopiér non-secret handoff" not in page
    assert "kun bruge den korte CF-kode" in page


def test_preclaim_helper_has_no_release_selector_or_parallel_download_authority():
    source = HELPER.read_text(encoding="utf-8")
    assert "fresh-install-bootstrap" in source
    assert "fresh-install-artifact" in source
    assert "resolve_release" not in source
    assert "requested_version" not in source
    assert "Release version:" not in source
    assert "latest" not in source.lower()
    assert "github.com" not in source.lower()
    assert "onrender.com" not in source.lower()
    assert 'BACKEND_URL = "https://api.display.planiq.dk"' in source
    assert "--fresh-install-authority-stdin" in source


def test_preclaim_helper_validates_binding_and_embedded_installer_from_exact_bundle(tmp_path: Path):
    module = _load_helper()
    installer = b"#!/usr/bin/python3\nprint('installer')\n"
    installer_sha = hashlib.sha256(installer).hexdigest()
    release_id = "clientflow-1.3.18-seq-1219"
    manifest = {
        "release_id": release_id,
        "fresh_installer": {
            "file": "clientflow-installer-1.3.18.pyz",
            "size": len(installer),
            "sha256": installer_sha,
        },
    }
    bundle = tmp_path / "bundle.tar"
    with tarfile.open(bundle, "w") as archive:
        manifest_bytes = json.dumps(manifest).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        archive.addfile(info, io.BytesIO(manifest_bytes))
        info = tarfile.TarInfo("clientflow-installer-1.3.18.pyz")
        info.size = len(installer)
        archive.addfile(info, io.BytesIO(installer))
    binding = {
        "release_id": release_id,
        "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "bundle_size": bundle.stat().st_size,
        "authorization": "cf-fresh-v1.payload.signature",
        "artifact_url": "/api/enrollment/fresh-install-artifact",
        "release_approval_reference": "approval/test",
    }
    # materializer requires its destination to exist, matching the real private /run directory.
    dest = tmp_path / "materialized"
    dest.mkdir()
    out = module._materialize_installer(bundle, binding, dest)
    assert out.read_bytes() == installer
    assert oct(out.stat().st_mode & 0o777) == "0o500"


def test_same_helper_activates_pending_install_without_reusing_consumed_code(monkeypatch, tmp_path: Path):
    module = _load_helper()
    updater = tmp_path / "clientflow-updater.pyz"
    updater.write_bytes(b"updater")
    module.STABLE_UPDATER = updater
    captured = {}

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        captured["command"] = command
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    state = {
        "status": "pending_manual_activation",
        "fresh_install_binding": {
            "release_id": "clientflow-1.3.18-seq-1219",
            "release_approval_reference": "clientflow-1.3.18-seq-1219/operator-approval",
        },
    }
    assert module._activate_pending(state) == 0
    command = captured["command"]
    assert "activate" in command
    assert "clientflow-1.3.18-seq-1219" in command
    assert "CF-" not in " ".join(command)
    assert "authorization" not in " ".join(command).lower()


def test_55a_is_wired_into_canonical_database_contract_and_migration_runner():
    contract = (ROOT / "backend/scripts/display_schema_contract.py").read_text(encoding="utf-8")
    delta = (ROOT / "backend/scripts/enrollment_binding_schema_contract.py").read_text(encoding="utf-8")
    runner = (ROOT / "backend/scripts/run_migrations.py").read_text(encoding="utf-8")

    assert 'EXPECTED_HEAD_REVISION = "20260908_55a_enroll_binding"' in contract
    assert 'from enrollment_binding_schema_contract import ENROLLMENT_BINDING_COLUMNS' in contract
    assert 'EXPECTED_COLUMNS["enrollmenttoken"] = _enrollment_columns' in contract
    for field in (
        "fresh_install_release_id", "fresh_install_version", "fresh_install_release_sequence",
        "fresh_install_bundle_sha256", "fresh_install_bundle_size", "fresh_install_approval_reference",
        "fresh_install_candidate_sha256", "fresh_install_source_commit",
    ):
        assert f'"{field}"' in delta
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260908_55a_enroll_binding"' in runner
    assert 'REVIEWED_LEGACY_RECONCILIATION_HEAD = "20260908_55a_enroll_binding"' in runner
    assert 'REVIEWED_ENROLLMENT_BINDING_REVISION = "20260908_55a_enroll_binding"' in runner
    assert 'enrollment_binding_revision.down_revision != REVIEWED_DISPLAY_OPERATIONAL_PARITY_REVISION' in runner
    assert 'head != REVIEWED_ENROLLMENT_BINDING_REVISION' in runner
