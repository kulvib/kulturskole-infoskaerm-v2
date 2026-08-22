from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_step51_follows_canonical_foundations_and_remains_in_reviewed_head_chain():
    migration = read("migrations/versions/20260819_51a_clientflow_update_control.py")
    contract = read("scripts/display_schema_contract.py")
    runner = read("scripts/run_migrations.py")
    assert 'revision = "20260819_51a_update_control"' in migration
    assert 'down_revision = "20260819_50a_canonical"' in migration
    assert contract.rsplit("EXPECTED_HEAD_REVISION = ", 1)[1].splitlines()[0] == '"20260822_52a_client_liveness"'
    assert 'REVIEWED_CLIENTFLOW_DEPLOYMENT_REVISION = "20260819_51a_update_control"' in runner
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260822_52a_client_liveness"' in runner


def test_step51_has_separate_update_identity_and_first_class_deployment_tables():
    migration = read("migrations/versions/20260819_51a_clientflow_update_control.py")
    models = read("service1/clientflow_update_models.py")
    for table in (
        "clientflow_update_credential",
        "clientflow_deployment",
        "clientflow_deployment_event",
    ):
        assert table in migration
        assert table in models
    assert "client_domain_credential" not in models
    assert "Ed25519" in models
    assert "public_key_pem" in models


def test_step51_enforces_one_active_credential_and_deployment_per_client_in_database():
    migration = read("migrations/versions/20260819_51a_clientflow_update_control.py")
    assert '"uq_clientflow_update_credential_active_client"' in migration
    assert 'postgresql_where=sa.text("revoked_at IS NULL")' in migration
    assert '"uq_clientflow_deployment_active_client"' in migration
    assert 'postgresql_where=sa.text("completed_at IS NULL")' in migration
    assert "ck_clientflow_deployment_completion" in migration


def test_deployment_authority_snapshots_artifact_identity_not_admin_payload():
    router = read("service1/routers/clientflow_deployments.py")
    releases = read("service1/clientflow_releases.py")
    assert "deployment_release_snapshot(release)" in router
    assert "bundle_sha256" not in router.split("class ClientFlowDeploymentCreate", 1)[1].split("class ClientFlowDeploymentCancel", 1)[0]
    for field in ("bundle_sha256", "bundle_size", "release_approval_reference"):
        assert field in releases
    assert "ClientFlowArtifactUnavailable" in releases


def test_activation_gate_is_atomic_and_cancellation_stops_at_staged():
    service = read("service1/clientflow_deployments.py")
    models = read("service1/clientflow_update_models.py")
    assert '.with_for_update()' in service
    assert 'deployment.state != "staged"' in service
    assert 'deployment.state = "activating"' in service
    for state in ("authorized", "downloading", "verified", "staged"):
        assert f'"{state}"' in models
    assert '"activating"' not in models.split("CLIENTFLOW_DEPLOYMENT_CANCELLABLE_STATES", 1)[1].split("}", 1)[0]


def test_permanent_purge_refuses_active_deployment_and_cleans_terminal_history_only():
    lifecycle = read("service1/lifecycle.py")
    clients = read("service1/routers/clients.py")
    assert "ClientPurgeBlocked" in lifecycle
    assert "ClientFlowDeployment.completed_at.is_(None)" in lifecycle
    assert "delete(ClientFlowDeploymentEvent)" in lifecycle
    assert "delete(ClientFlowDeployment)" in lifecycle
    assert "delete(ClientFlowUpdateCredential)" in lifecycle
    assert "except ClientPurgeBlocked as exc:" in clients
    assert "status_code=409" in clients


def test_legacy_client_update_fields_are_not_new_deployment_authority():
    models = read("service1/clientflow_update_models.py")
    clients = read("service1/routers/clients.py")
    self_fields = clients.split("CLIENT_SELF_UPDATE_FIELDS = {", 1)[1].split("}", 1)[0]
    assert "client_update_deployment_sequence" not in models
    assert "client_update_applied_deployment_sequence" not in models
    assert "target_release_sequence" in models
    assert "requested_by_user_id" in models
    assert '"client_update_target_version"' not in self_fields
    assert '"client_update_deployment_sequence"' not in self_fields


def test_step51_postgresql_ddl_contains_partial_unique_authority_indexes():
    import importlib.util
    import io

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = ROOT / "migrations/versions/20260819_51a_clientflow_update_control.py"
    spec = importlib.util.spec_from_file_location("step51_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    module.op = Operations(context)
    module.upgrade()
    ddl = output.getvalue()
    assert "CREATE UNIQUE INDEX uq_clientflow_deployment_active_client" in ddl
    assert "WHERE completed_at IS NULL" in ddl
    assert "CREATE UNIQUE INDEX uq_clientflow_update_credential_active_client" in ddl
    assert "WHERE revoked_at IS NULL" in ddl
    assert "clientflow_deployment_event" in ddl
    assert "ON DELETE CASCADE" in ddl
