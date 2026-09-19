from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _function_block(source: str, name: str, next_name: str | None = None) -> str:
    start = source.index(f"def {name}(")
    if next_name is None:
        return source[start:]
    end = source.index(f"\ndef {next_name}(", start)
    return source[start:end]


def test_shared_agent_auth_is_one_joined_database_read_per_validation():
    source = _read("backend/service1/shared_domain.py")
    authenticate = _function_block(source, "authenticate_shared_credential", "create_shared_domain_token")
    require_token = _function_block(source, "require_shared_agent_token", "upsert_shared_status")

    for block in (authenticate, require_token):
        assert ".join(Client, Client.id == ClientDomainCredential.client_id)" in block
        assert "session.get(ClientDomainCredential" not in block
        assert "session.get(Client," not in block

    assert "ClientDomainCredential.revoked_at.is_(None)" in require_token
    assert 'func.lower(Client.status) == "approved"' in require_token
    assert "Client.deleted_at.is_(None)" in require_token
    assert 'ClientDomainCredential.token_version == int(claims["token_version"])' in require_token


def test_empty_shared_command_claim_reads_active_queue_once_and_skips_display_status():
    source = _read("backend/service1/shared_domain.py")
    loader = _function_block(source, "_load_active_command_rows", "_reconcile_command_state")
    claim = _function_block(source, "claim_shared_command", "_require_claimed_command")

    assert "select(ClientCommand)" in loader
    assert '.with_for_update()' in loader
    assert "active_rows = _load_active_command_rows(" in claim
    assert 'if not active_rows:' in claim
    assert 'return {"claimed": None}' in claim
    # The Display capability lookup must happen only after the empty-queue return.
    assert claim.index("if not active_rows:") < claim.index('if domain == "display":')
    # Candidate selection reuses the locked rows rather than issuing a second queue SELECT.
    assert "row = next(" in claim
    assert claim.count("select(ClientCommand)") == 0


def test_shared_command_poll_matches_legacy_five_second_backend_cadence_without_changing_presence():
    constants = _read("client/runtime/clientflow_runtime/constants.py")
    agent = _read("client/runtime/clientflow_runtime/command_agent.py")

    assert "SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 15" in constants
    assert "SHARED_DOMAIN_COMMAND_POLL_SECONDS = 5.0" in constants
    assert "poll_seconds: float = SHARED_DOMAIN_COMMAND_POLL_SECONDS" in agent
    assert "time.sleep(self.poll_seconds)" in agent


def test_frontend_always_on_database_polls_are_visibility_aware():
    list_page = _read("frontend/src/pages/ClientInfoPage.jsx")
    details_page = _read("frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx")
    actions = _read("frontend/src/pages/clientdetailspage/ClientDetailsActionsSection.jsx")
    info = _read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")

    assert "if (isPageVisible()) fetchClients(false, false);" in list_page
    assert "if (!isPageVisible()) {" in details_page
    assert "getActiveClientflowDeployment" not in actions
    assert "refreshDeployment" not in actions
    assert "if (isPageVisible()) refreshClientflowDeployment();" in details_page
    assert "!clientflowDeploymentActive" in details_page
    assert "configRefreshInFlightRef.current || !isPageVisible()" in info
    assert "diagnosticsRefreshInFlightRef.current || !isPageVisible()" in info
