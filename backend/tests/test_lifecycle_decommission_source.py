from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_client_purge_uses_shared_lifecycle_service():
    router = read("service1/routers/clients.py")
    lifecycle = read("service1/lifecycle.py")
    assert "prepare_client_for_permanent_delete" in router
    assert 'terminal_client.status = "disabled"' in lifecycle
    assert 'rd_client.status = "disabled"' in lifecycle
    assert "credential.token_version" in lifecycle
    assert "LivestreamV2Credential" in lifecycle
    assert "ClientDomainCredential" in lifecycle
    assert "ClientActivityLease" in lifecycle


def test_organization_delete_deactivates_users_and_reuses_client_decommission():
    router = read("service1/routers/organizations.py")
    assert "prepare_client_for_permanent_delete" in router
    assert "user.is_active = False" in router
    assert "user.token_version" in router
    assert "_revoke_all_user_refresh_tokens" in router
    assert "user.organization_id = None" in router


def test_platform_owned_domain_tokens_revalidate_parent_client():
    livestream = read("service1/livestream_v2.py")
    shared = read("service1/shared_domain.py")
    assert "client = session.get(Client, client_id)" in livestream
    assert 'lower() != "approved"' in livestream
    assert "client = session.get(Client, client_id)" in shared
    assert 'lower() != "approved"' in shared


def test_privileged_websockets_revalidate_login_and_domain_authority():
    auth = read("service1/auth.py")
    remote_ticket = read("service1/routers/websocket_tickets.py")
    terminal_ticket = read("service1/routers/terminal.py")
    shared_ws = read("service1/websocket_auth.py")
    terminal_ws = read("service1/terminal_websocket_auth.py")
    terminal = read("service1/routers/terminal.py")
    remote = read("service1/routers/remote_desktop_v2.py")
    assert "def validate_browser_auth_session_binding" in auth
    assert "def require_active_browser_auth_session_binding" in auth
    assert "RefreshToken.revoked_at.is_(None)" in auth
    assert "require_active_browser_auth_session_binding(" in remote_ticket
    assert "require_active_browser_auth_session_binding(" in terminal_ticket
    assert "validate_browser_auth_session_binding(" in shared_ws
    assert "validate_browser_auth_session_binding(" in terminal_ws
    assert "validate_browser_auth_session_binding" in terminal
    assert "_terminal_agent_connection_valid" in terminal
    assert "authenticate_browser_websocket_with_context" in remote
    assert "_remote_desktop_browser_auth_state" in remote
    assert 'rd_client.status != "approved"' in remote
    assert "_remote_desktop_agent_channel_valid" in remote
    assert "REMOTE_DESKTOP_BROWSER_AUTH_RECHECK_SECONDS" in remote


def test_lifecycle_retention_migration_is_additive_and_set_null():
    migration = read("migrations/versions/20260818_48a_lifecycle_retention.py")
    contract = read("scripts/display_schema_contract.py")
    runner = read("scripts/run_migrations.py")
    assert 'revision = "20260818_48a_lifecycle"' in migration
    assert 'down_revision = "20260818_47a_client_activity"' in migration
    assert 'ondelete="SET NULL"' in migration
    assert 'EXPECTED_HEAD_REVISION = "20260820_51b_update_auth"' in contract
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260820_51b_update_auth"' in runner
    assert 'REVIEWED_LIFECYCLE_REVISION = "20260818_48a_lifecycle"' in runner


def test_user_owned_history_models_are_nullable_with_set_null():
    terminal = read("service1/terminal_v2_models.py")
    remote = read("service1/remote_desktop_session_models.py")
    shared = read("service1/client_domain_models.py")
    assert 'ForeignKey("user.id", ondelete="SET NULL")' in terminal
    assert 'ForeignKey("user.id", ondelete="SET NULL")' in remote
    assert 'ForeignKey("user.id", ondelete="SET NULL")' in shared


def test_livestream_browser_hold_requires_active_platform_client():
    router = read("service1/routers/livestream_v2.py")
    assert "from ..models import Client" in router
    assert "def _require_active_platform_client" in router
    assert router.count("_require_active_platform_client(int(client_id))") >= 3


def test_remote_desktop_cleanup_preserves_actual_close_reason():
    router = read("service1/routers/remote_desktop_v2.py")
    assert "reason=close_reason" in router
    assert "end_activity_lease(" in router
