from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_deployment_polling_has_one_common_parent_owner_and_bounded_history():
    page = read("frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx")
    actions = read("frontend/src/pages/clientdetailspage/ClientDetailsActionsSection.jsx")
    info = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")
    api = read("frontend/src/api/api.js")
    router = read("backend/service1/routers/clientflow_deployments.py")

    assert "getClientflowDeployments(client.id, { limit: 1 })" in page
    assert "deploymentRefreshInFlightRef" in page
    assert "clientflowDeploymentActive" in page
    assert "getActiveClientflowDeployment" not in actions
    assert "refreshDeployment" not in actions
    assert "getClientflowDeployments" not in info
    assert "deployment={clientflowDeployment}" in info
    assert "limit = null" in api
    assert "limit: int | None = Query(default=None, ge=1, le=100)" in router
    assert "statement = statement.limit(limit)" in router

def test_ubuntu_and_local_management_use_existing_hot_read_instead_of_extra_db_pollers():
    page = read("frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx")
    info = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")
    clients = read("backend/service1/routers/clients.py")

    assert "pollUbuntuUpdate" not in info
    assert "UBUNTU_POLL_MS" not in info
    assert "pollLocalManagement" not in info
    assert '"local_management_status"' in page
    assert '"local_management_finished_at"' in page
    assert '"local_management_status": getattr(client, "local_management_status", None)' in clients
    assert '"local_management_error": getattr(client, "local_management_error", None)' in clients
