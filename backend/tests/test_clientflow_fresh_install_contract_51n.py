from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_51n_fresh_path_is_separate_from_existing_update_mode():
    source = (ROOT / "backend/service1/clientflow_release_artifacts.py").read_text(encoding="utf-8")
    assert "INSTALL_MODE_UPDATE" in source
    assert "INSTALL_MODE_FRESH" in source
    assert "def open_published_release_artifact" in source
    assert "def open_published_fresh_install_artifact" in source
    assert "def open_artifact_matches_deployment" in source
    assert "def open_artifact_matches_fresh_install_authorization" in source


def test_51n_download_does_not_consume_but_claim_consumption_is_release_bound():
    source = (ROOT / "backend/service1/routers/enrollment.py").read_text(encoding="utf-8")
    download_start = source.index('def download_fresh_install_artifact(')
    list_start = source.index('@router.get("/admin/enrollment-tokens"', download_start)
    download = source[download_start:list_start]
    assert "token.used_at" not in download
    assert "token.used_by_client_id" not in download
    assert "open_artifact_matches_fresh_install_authorization" in download
    assert 'bucket="enrollment-fresh-install-artifact"' in download

    claim_start = source.index('def claim_enrollment_token(')
    complete_start = source.index('@router.post("/enrollment/complete")', claim_start)
    claim = source[claim_start:complete_start]
    assert "_verify_initial_fresh_install_authorization(" in claim
    assert "data.fresh_install_authorization" in claim
    assert "binding = _claim_fresh_install_binding(data.fresh_install_binding)" in claim
    assert "_bound_resume_proof_hash(data.resume_proof, binding)" in claim
    assert "token.used_at = now" in claim
    assert "token.used_by_client_id = client_id" in claim
    assert claim.index("_verify_initial_fresh_install_authorization(") < claim.index("client = Client(")
    assert claim.index("_verify_initial_fresh_install_authorization(") < claim.index("token.used_at = now")


def test_51n_receipt_hash_is_crash_resume_commitment_without_parallel_release_authority():
    router_source = (ROOT / "backend/service1/routers/enrollment.py").read_text(encoding="utf-8")
    models_source = (ROOT / "backend/service1/enrollment_models.py").read_text(encoding="utf-8")
    assert "clientflow-enrollment-resume-binding-v1" in router_source
    assert "_require_bound_resume_receipt" in router_source
    assert "legacy og mangler canonical fresh-install release-binding" in router_source
    assert "release_approval_reference" not in models_source
    assert "release_candidate_sha256" not in models_source
    assert "source_commit" not in models_source


def test_51n_has_no_new_database_or_parallel_fresh_install_release_authority():
    files = {str(path.relative_to(ROOT)) for path in ROOT.rglob("*") if path.is_file()}
    assert not any("fresh_install_binding" in path.lower() and "migrations/versions" in path for path in files)
    auth_source = (ROOT / "backend/service1/clientflow_fresh_install_auth.py").read_text(encoding="utf-8")
    releases_source = (ROOT / "backend/service1/clientflow_releases.py").read_text(encoding="utf-8")
    assert "CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64" in auth_source
    assert "SQLModel" not in auth_source
    assert "inspect_published_fresh_install_artifact" in releases_source
    assert "fresh_install_release_snapshot" in releases_source
