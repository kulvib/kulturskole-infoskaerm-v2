from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_step51b_migration_and_current_head_chain_are_explicit():
    migration = (ROOT / "backend/migrations/versions/20260820_51b_clientflow_update_auth.py").read_text()
    runner = (ROOT / "backend/scripts/run_migrations.py").read_text()
    display = (ROOT / "backend/scripts/display_schema_contract.py").read_text()
    contract = (ROOT / "backend/scripts/clientflow_update_auth_schema_contract.py").read_text()

    assert 'revision = "20260820_51b_update_auth"' in migration
    assert 'down_revision = "20260819_51a_update_control"' in migration
    assert 'REVIEWED_CLIENTFLOW_UPDATE_AUTH_REVISION = "20260820_51b_update_auth"' in runner
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260822_52a_client_liveness"' in runner
    assert display.rsplit("EXPECTED_HEAD_REVISION = ", 1)[1].splitlines()[0] == '"20260822_52a_client_liveness"'
    assert "clientflow_update_replay" in contract
    assert "clientflow_update_provisioning_token" in contract


def test_update_auth_isolated_from_domain_credentials_and_system_encryption_key():
    source = (ROOT / "backend/service1/clientflow_update_auth.py").read_text()
    models = (ROOT / "backend/service1/clientflow_update_models.py").read_text()
    enrollment = (ROOT / "backend/service1/routers/enrollment.py").read_text()

    assert 'UPDATE_CREDENTIAL_ALGORITHM = "Ed25519"' in source
    assert 'UPDATE_ACCESS_TOKEN_TYP = "clientflow-update-access+jwt"' in source
    assert 'UPDATE_DPOP_TYP = "dpop+jwt"' in source
    assert 'UPDATE_TOKEN_AUDIENCE = "urn:planiq:clientflow-update:token"' in source
    assert "ClientDomainCredential" not in source
    assert "TerminalCredential" not in source
    assert "RemoteDesktopCredential" not in source
    assert "ClientSystemEncryptionKey" not in source
    assert 'tablename__ = "clientflow_update_credential"' in models
    assert "update_auth_public_key_pem" in enrollment


def test_update_router_uses_identity_derived_client_and_scoped_dpop_auth():
    source = (ROOT / "backend/service1/routers/clientflow_update.py").read_text()

    assert '@router.post("/clientflow-update/token"' in source
    assert '@router.post("/clientflow-update/provision"' in source
    assert '@router.post("/clientflow-update/credential/rotate"' in source
    assert 'clientflow-update-credential/revoke' in source
    assert '@router.get("/clientflow-update/deployments/active"' in source
    assert 'scope="deployment:read"' in source
    assert 'scope="deployment:report"' in source
    assert 'scope="credential:rotate"' in source
    assert "principal.client.id" in source
    assert "DPoP proof mangler" in source


def test_fresh_installer_generates_separate_local_update_private_key():
    cli = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text()
    enrollment = (ROOT / "client/release/lib/clientflow_release/enrollment.py").read_text()
    update_auth = (ROOT / "client/release/lib/clientflow_release/update_auth.py").read_text()

    assert 'update/private-key.pem' in cli
    assert "generate_update_key" in cli
    assert "update_auth_public_key_pem" in enrollment
    assert "update_private_key" in enrollment
    assert '"algorithm": "Ed25519"' in enrollment
    assert "openssl" in update_auth
    assert "private_key" in update_auth
    filesystem = (ROOT / "client/release/lib/clientflow_release/filesystem.py").read_text()
    assert '"credentials", "release", "update"' in filesystem
