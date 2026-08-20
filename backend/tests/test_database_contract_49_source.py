from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")



def test_frozen_display_baseline_does_not_autoincrement_organizationlogo_fk_primary_key():
    migration = read("migrations/versions/20260712_30d_display_base_frozen_display_baseline.py")
    assert "sa.Column('organization_id', sa.Integer(), autoincrement=False, nullable=False)" in migration
    assert "organizationlogo_organization_id_seq" not in migration

def test_step49_is_additive_head_after_lifecycle_and_creates_missing_command_queue():
    migration = read("migrations/versions/20260819_49a_database_contract.py")
    assert 'revision = "20260819_49a_db_contract"' in migration
    assert 'down_revision = "20260818_48a_lifecycle"' in migration
    assert 'if not _has_table("client_command"):' in migration
    assert '_create_client_command()' in migration
    assert 'sa.Column("command_type", sa.String(100), nullable=False)' in migration
    assert 'sa.Column("payload_encryption_key_id", sa.String(120), nullable=True)' in migration
    assert 'sa.Column("idempotency_key", sa.String(200), nullable=False)' in migration
    assert 'sa.Column("claim_token_hash", sa.String(64), nullable=True)' in migration
    assert 'sa.Column("error_code", sa.String(100), nullable=True)' in migration
    assert 'ondelete="SET NULL"' in migration


def test_step49_normalises_only_the_reviewed_fresh_rd_delta_and_fails_closed():
    migration = read("migrations/versions/20260819_49a_database_contract.py")
    assert 'source_ip_length == 255' in migration
    assert 'char_length(source_ip) > 64' in migration
    assert 'type_=sa.String(64)' in migration
    assert 'source_ip_length != 64' in migration
    assert 'ix_remote_desktop_session_expiry' in migration
    assert 'ix_remote_desktop_session_requested_by_user_id' in migration
    assert 'kan ikke downgrades sikkert' in migration


def test_adopted_runtime_contract_contains_only_physically_reviewed_active_tables():
    contract = read("scripts/adopted_runtime_schema_contract.py")
    for table in (
        "client_domain_credential",
        "client_domain_status",
        "client_command",
        "remote_desktop_session",
        "remote_desktop_session_event",
    ):
        assert f'"{table}"' in contract
    for opaque in (
        "browser_websocket_ticket",
        "client_enrollment_receipt",
        "client_system_encryption_key",
        "livestream_generation",
    ):
        assert f'"{opaque}"' not in contract


def test_models_match_reviewed_production_lengths_and_rd_indexes():
    shared = read("service1/client_domain_models.py")
    rd = read("service1/remote_desktop_session_models.py")
    for snippet in (
        "command_type: str = Field(max_length=100)",
        "payload_encryption_key_id: Optional[str] = Field(default=None, max_length=120)",
        "idempotency_key: str = Field(max_length=200)",
        "claim_token_hash: Optional[str] = Field(default=None, max_length=64)",
        "error_code: Optional[str] = Field(default=None, max_length=100)",
    ):
        assert snippet in shared
    assert "source_ip: Optional[str] = Field(default=None, max_length=64)" in rd
    assert 'Index("ix_remote_desktop_session_expiry", "status", "expires_at")' in rd
    assert 'Index("ix_remote_desktop_session_requested_by_user_id", "requested_by_user_id")' in rd


def test_head_contract_promotes_adopted_runtime_tables_out_of_opaque_preservation():
    display = read("scripts/display_schema_contract.py")
    runner = read("scripts/run_migrations.py")
    assert 'EXPECTED_HEAD_REVISION = "20260820_51b_update_auth"' in display
    assert "EXPECTED_TABLES |= ADOPTED_RUNTIME_TABLES" in display
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260820_51b_update_auth"' in runner
    assert 'REVIEWED_DATABASE_CONTRACT_REVISION = "20260819_49a_db_contract"' in runner
    assert "- ADOPTED_RUNTIME_TABLES" in runner
    assert "- CANONICAL_FOUNDATION_TABLES" in runner
    assert "_without_adopted_runtime_schema" in runner



def test_catalog_contract_uses_postgresql_canonical_array_check_rendering():
    sources = "\n".join(
        read(path)
        for path in (
            "scripts/display_schema_contract.py",
            "scripts/client_activity_schema_contract.py",
            "scripts/remote_desktop_v2_schema_contract.py",
            "scripts/terminal_v2_schema_contract.py",
            "scripts/adopted_runtime_schema_contract.py",
        )
    )

    for snippet in (
        "'superadmin'::character varying::text",
        "'terminal'::character varying::text",
        "'approved'::character varying::text",
        "'standard'::character varying::text",
        "'requested'::character varying::text",
        "'queued'::character varying::text",
        "'cancelled'::character varying::text",
    ):
        assert snippet in sources

    for constraint in (
        "users_role_check",
        "ck_client_activity_lease_domain",
        "ck_remote_desktop_client_status",
        "ck_remote_desktop_session_status",
        "ck_terminal_client_status",
        "ck_terminal_session_privilege",
        "ck_terminal_session_status",
        "ck_client_command_status",
    ):
        assert constraint in sources
