from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_b1_legacy_clientflow_update_authority_is_not_routable() -> None:
    clients = read("backend/service1/routers/clients.py")
    system_agent = read("client/runtime/clientflow_runtime/system_agent.py")
    system_broker = read("client/runtime/clientflow_runtime/system_broker.py")

    assert '@router.post("/clients/{id}/clientflow-update")' not in clients
    assert '@router.post("/clients/{id}/clientflow-update/reset")' not in clients
    assert "ClientFlowUpdateRequest" not in clients
    assert "ChromeAction.CLIENTFLOW_UPDATE" not in clients
    assert 'action == "clientflow_update"' in clients
    assert "Legacy clientflow_update er fjernet" in clients
    assert "LEGACY_CLIENTFLOW_UPDATE_FIELDS" in clients
    assert "Legacy ClientFlow update-felter er fjernet fra runtime-kontrakten" in clients
    assert "Legacy ClientFlow update-state må ikke oprettes" in clients

    # Canonical ClientFlow update authority is the isolated update identity +
    # stable updater/controller. The retained System domain must not contain a
    # second executable release download/stage/activate/rollback path.
    assert "release_download" not in system_agent
    for legacy_action in ("update_clientflow", "activate_release", "rollback_release"):
        assert legacy_action not in system_agent
        assert legacy_action not in system_broker


def test_b1_stale_legacy_command_is_neutralized_and_canonical_deployment_locks_commands() -> None:
    clients = read("backend/service1/routers/clients.py")

    chrome_command_start = clients.index('def get_chrome_command(')
    chrome_command_end = clients.index('async def trigger_os_update(', chrome_command_start)
    chrome_command = clients[chrome_command_start:chrome_command_end]
    assert 'if action == "clientflow_update":' in chrome_command
    assert "client.pending_chrome_action = ChromeAction.NONE" in chrome_command
    assert "client.pending_chrome_action_source = None" in chrome_command
    assert 'client.state = "normal"' in chrome_command
    assert "session.commit()" in chrome_command

    assert "from ..clientflow_deployments import active_deployment" in clients
    assert "def _require_no_active_clientflow_deployment" in clients
    assert "_require_no_active_clientflow_deployment(session, id)" in clients
    assert "_require_no_active_clientflow_deployment(session, client.id)" in clients


def test_b1_clientflow_and_ubuntu_updates_are_mutually_exclusive() -> None:
    clients = read("backend/service1/routers/clients.py")
    deployments = read("backend/service1/routers/clientflow_deployments.py")

    os_update_start = clients.index('async def trigger_os_update(')
    os_update_reset = clients.index('async def reset_os_update(', os_update_start)
    os_update = clients[os_update_start:os_update_reset]
    assert "_require_no_active_clientflow_deployment(session, id)" in os_update

    assert 'active = active_system_command(session, int(client.id))' in deployments
    assert "ClientFlow deployment kan ikke startes under aktiv System-handling" in deployments
    assert 'lock_system_client(session, int(client.id))' in deployments
    assert '_require_deployable_client(session, client)' in deployments
    assert 'getattr(client, "pending_os_update", False)' not in deployments


def test_b1_frontend_uses_only_first_class_clientflow_deployments() -> None:
    api = read("frontend/src/api/api.js")
    info = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")
    actions = read("frontend/src/pages/clientdetailspage/ClientDetailsActionsSection.jsx")
    page = read("frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx")

    assert "requestClientflowDeployment" in api
    assert "getClientflowDeployments" in api
    assert "getActiveClientflowDeployment" in api
    assert "cancelClientflowDeployment" in api
    assert "/clientflow-deployments" in api
    assert "/clientflow-update" not in api
    assert "requestClientflowUpdate" not in api
    assert "getClientflowUpdateStatus" not in api
    assert "resetClientflowUpdate" not in api

    for source in (info, actions, page):
        assert "client_update_" not in source
        assert "clientflow_self_update" not in source
        assert "service_selfupdate_status" not in source

    assert "CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES" in info
    assert "CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES" in actions


def test_b1_audit_ui_names_canonical_deployment_events_only() -> None:
    audit = read("frontend/src/pages/adminpages/AuditLog.jsx")
    user_admin = read("frontend/src/pages/adminpages/UserAdministration.jsx")

    assert "clientflow_deployment_authorized" in audit
    assert "clientflow_deployment_cancelled" in audit
    assert "ClientFlow-version bestilt (historisk)" in audit
    assert "ClientFlow-nedgradering bestilt (historisk)" in audit
    assert "clientflow_deployment_authorized" in user_admin
    assert "clientflow_deployment_cancelled" in user_admin
