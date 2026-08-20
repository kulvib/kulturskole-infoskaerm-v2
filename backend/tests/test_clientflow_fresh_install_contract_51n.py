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


def test_51n_enrollment_download_does_not_replace_claim_consumption_contract():
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
    assert "token.used_at = now" in claim
    assert "token.used_by_client_id = client_id" in claim


def test_51n_has_no_new_database_or_migration_authority():
    files = {str(path.relative_to(ROOT)) for path in ROOT.rglob("*") if path.is_file()}
    assert not any("51n" in path.lower() and "migrations/versions" in path for path in files)
    auth_source = (ROOT / "backend/service1/clientflow_fresh_install_auth.py").read_text(encoding="utf-8")
    assert "CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64" in auth_source
    assert "SQLModel" not in auth_source
