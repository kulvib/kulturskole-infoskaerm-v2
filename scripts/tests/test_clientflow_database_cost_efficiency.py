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


def test_shared_agent_auth_is_one_joined_database_read_and_reuses_authorized_client():
    source = _read("backend/service1/shared_domain.py")
    authenticate = _function_block(source, "authenticate_shared_credential", "create_shared_domain_token")
    context = _function_block(source, "require_shared_agent_context", "require_shared_agent_token")
    wrapper = _function_block(source, "require_shared_agent_token", "upsert_shared_status")

    assert ".join(Client, Client.id == ClientDomainCredential.client_id)" in authenticate
    assert "session.get(ClientDomainCredential" not in authenticate
    assert "session.get(Client," not in authenticate

    assert "select(ClientDomainCredential, Client)" in context
    assert ".join(Client, Client.id == ClientDomainCredential.client_id)" in context
    assert "ClientDomainCredential.revoked_at.is_(None)" in context
    assert 'func.lower(Client.status) == "approved"' in context
    assert "Client.deleted_at.is_(None)" in context
    assert 'ClientDomainCredential.token_version == int(claims["token_version"])' in context
    assert "return SharedAgentAuthorization(credential=credential, client=client)" in context
    assert "return require_shared_agent_context(" in wrapper
    assert ").credential" in wrapper


def test_shared_status_uses_atomic_upsert_instead_of_read_before_write():
    source = _read("backend/service1/shared_domain.py")
    block = _function_block(source, "upsert_shared_status", "_claim_digest")

    assert 'dialect_name in {"postgresql", "sqlite"}' in block
    assert "on_conflict_do_update(" in block
    assert 'index_elements=["client_id", "domain"]' in block
    # Production PostgreSQL and executable SQLite tests must not SELECT the status
    # row before every heartbeat. The ORM SELECT exists only in the explicit
    # unsupported-dialect fallback branch.
    assert block.index('if dialect_name in {"postgresql", "sqlite"}:') < block.index("row = session.exec(")


def test_status_router_reuses_authorized_client_for_identity_and_power_observation():
    source = _read("backend/service1/routers/shared_domain.py")
    block = _function_block(source, "_status", "_claim")

    assert "authorization_context = require_shared_agent_context(" in block
    assert "client = authorization_context.client" in block
    assert "client=client," in block
    assert "_client_identity_payload(client)" in block
    assert "session.get(Client," not in block


def test_display_heartbeat_shares_lazy_active_command_read_between_reconcilers():
    router = _read("backend/service1/routers/shared_domain.py")
    display = _read("backend/service1/display_control.py")
    block = _function_block(router, "_status", "_claim")

    assert "active_command_cache: dict[str, Any] = {}" in block
    assert block.count("active_command_cache=active_command_cache") == 2
    assert "def _cached_active_display_commands(" in display
    assert 'cache.get("active")' in display
    assert 'cache["active"] = rows' in display


def test_calendar_hot_path_reuses_authorized_client_and_batches_two_seasons():
    router = _read("backend/service1/routers/shared_domain.py")
    calendar = _read("backend/service1/calendar_control.py")
    start = router.index("def display_calendar(")
    end = router.index('@router.put("/status-agent', start)
    endpoint = router[start:end]
    delivery = _function_block(calendar, "build_display_calendar_delivery")

    assert "authorization_context = require_shared_agent_context(" in endpoint
    assert "authorized_client=authorization_context.client" in endpoint
    assert "requested_seasons = tuple(current_and_next_seasons())" in delivery
    assert "CalendarMarking.season.in_(requested_seasons)" in delivery
    assert "select(CalendarMarking.season, CalendarMarking.markings)" in delivery
    assert delivery.count("select(CalendarMarking") == 1
    assert "if client is None:" in delivery  # safe standalone lifecycle fallback


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

    assert "if (!cancelled && isPageVisible()) {" in list_page
    assert "await fetchClients(false, false);" in list_page
    assert "CLIENT_LIST_ACTIVE_POLL_MS = 2_000" in list_page
    assert "CLIENT_LIST_IDLE_POLL_MS = 5_000" in list_page
    assert "if (!isPageVisible()) {" in details_page
    assert "await waitForNextPoll(CHROME_STATUS_HIDDEN_CHECK_MS);" in details_page
    assert "CHROME_STATUS_ACTIVE_POLL_MS = 1000" in details_page
    assert "CHROME_STATUS_IDLE_POLL_MS = 5000" in details_page
    assert "getActiveClientflowDeployment" not in actions
    assert "refreshDeployment" not in actions
    assert "if (isPageVisible()) refreshClientflowDeployment();" in details_page
    assert "!clientflowDeploymentActive" in details_page
    # Configuration/Diagnostics must not add their own full-client intervals.
    # Their state rides on the already visibility-aware /chrome-status poll.
    assert "const DETAIL_HOT_FIELDS = [" in details_page
    assert "setLiveDetailHotFields" in details_page
    assert "setInterval(refreshConfig" not in info
    assert "setInterval(refreshDiagnostics" not in info
