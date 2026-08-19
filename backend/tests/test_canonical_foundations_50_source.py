from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_step50_revision_fits_alembic_version_and_follows_step49():
    migration = read("migrations/versions/20260819_50a_canonical_foundations.py")
    assert 'revision = "20260819_50a_canonical"' in migration
    assert len("20260819_50a_canonical") <= 32
    assert 'down_revision = "20260819_49a_db_contract"' in migration


def test_step50_adopts_physically_observed_enrollment_tables_exactly():
    migration = read("migrations/versions/20260819_50a_canonical_foundations.py")
    models = read("service1/enrollment_models.py")
    for table in ("client_enrollment_receipt", "client_system_encryption_key"):
        assert table in migration
        assert table in models
    for field in ("install_id", "resume_proof_hash", "completed_at"):
        assert field in migration
    for field in ("RSA-OAEP-SHA256", "public_key_pem", "revoked_at"):
        assert field in migration


def test_step50_retires_shared_livestream_only_after_isolated_credential_check():
    migration = read("migrations/versions/20260819_50a_canonical_foundations.py")
    assert "NOT EXISTS" in migration
    assert "livestream_v2_credential" in migration
    assert "DELETE FROM client_domain_status WHERE domain = 'livestream'" in migration
    assert "DELETE FROM client_command WHERE domain = 'livestream'" in migration
    assert "DELETE FROM client_domain_credential WHERE domain = 'livestream'" in migration
    assert "domain IN ('status','display','system')" in migration
    assert "domain IN ('display','system')" in migration


def test_models_exclude_retired_shared_livestream_domains():
    models = read("service1/client_domain_models.py")
    assert "domain IN ('status','display','system')" in models
    assert "domain IN ('display','system')" in models
    assert "domain IN ('display','livestream','system')" not in models


def test_enrollment_matches_installer_seed_and_six_domain_contract():
    router = read("service1/routers/enrollment.py")
    installer = read("../client/release/lib/clientflow_release/enrollment.py")
    for context in (
        "clientflow-enrollment-resume-v1",
        "clientflow-domain-secret-v1",
    ):
        assert context in router
        assert context in installer
    for domain in ("status", "display", "livestream", "remote_desktop", "terminal", "system"):
        assert f'"{domain}"' in router
    assert "LivestreamV2Credential" in router
    assert "TerminalCredential" in router
    assert "RemoteDesktopCredential" in router
    assert "ClientDomainCredential" in router
    assert '@router.post("/enrollment/complete")' in router


def test_release_source_is_self_contained_and_runtime_is_buildable():
    for path in (
        "../client/release/lib/clientflow_release/builder.py",
        "../client/release/lib/clientflow_release/transaction.py",
        "../client/sysusers.d/clientflow.conf",
        "../client/tmpfiles.d/clientflow.conf",
        "../client/runtime/pyproject.toml",
        "../scripts/build_clientflow_release.py",
        "../scripts/approve_clientflow_release.py",
    ):
        assert (ROOT / path).resolve().is_file(), path
    builder = read("../client/release/lib/clientflow_release/builder.py")
    assert 'Path("client/systemd")' in builder
    assert 'repo / "client/VERSION"' in builder
    assert 'repo / "client" / "runtime"' in read("../scripts/build_clientflow_release.py")


def test_rd_capture_user_is_rendered_from_kiosk_user_not_frozen_hostname():
    unit = read("../client/systemd/clientflow-remote-desktop-capture.service")
    transaction = read("../client/release/lib/clientflow_release/transaction.py")
    cli = read("../client/release/lib/clientflow_release/cli.py")
    assert "User=@CLIENTFLOW_KIOSK_USER@" in unit
    assert "Group=@CLIENTFLOW_KIOSK_USER@" in unit
    assert "viborg2" not in unit
    assert "@CLIENTFLOW_KIOSK_USER@" in transaction
    assert "kiosk_user=kiosk_user" in cli


def test_final_schema_contract_head_is_step50():
    contract = read("scripts/display_schema_contract.py")
    runner = read("scripts/run_migrations.py")
    assert 'EXPECTED_HEAD_REVISION = "20260819_50a_canonical"' in contract
    assert 'REVIEWED_CANONICAL_FOUNDATIONS_REVISION = "20260819_50a_canonical"' in runner

def test_permanent_delete_cleans_canonical_enrollment_fk_state():
    source = read("service1/lifecycle.py")
    assert "delete(ClientEnrollmentReceipt)" in source
    assert "delete(ClientSystemEncryptionKey)" in source
    assert source.index("delete(ClientEnrollmentReceipt)") < source.index("delete(CalendarMarking)")

