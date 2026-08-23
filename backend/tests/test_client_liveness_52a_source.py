from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def read_backend(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_repo(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_status_domain_is_the_only_global_liveness_authority():
    presence = read_backend("service1/client_presence.py")
    assert 'PRESENCE_DOMAINS = ("status", "display", "system")' in presence
    assert 'return self.status.is_online' in presence
    assert 'status.domain' not in presence.split("def is_online", 1)[1].split("def public_dict", 1)[0]
    assert 'observed_state != ONLINE_OBSERVED_STATE' in presence
    assert 'credential.id != status.credential_id' in presence
    assert 'credential.revoked_at is not None' in presence
    assert 'current >= expires_at' in presence
    assert 'reported_at > current' in presence


def test_presence_lease_is_three_code_owned_canonical_shared_domain_periods():
    presence = read_backend("service1/client_presence.py")
    render = read_repo("render.yaml")
    status_agent = read_repo("client/runtime/clientflow_runtime/status_agent.py")
    runtime_constants = read_repo("client/runtime/clientflow_runtime/constants.py")
    command_agent = read_repo("client/runtime/clientflow_runtime/command_agent.py")
    assert 'SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 30' in presence
    assert 'SHARED_DOMAIN_MISSED_REPORT_LIMIT = 3' in presence
    assert 'SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS * SHARED_DOMAIN_MISSED_REPORT_LIMIT' in presence
    assert 'CLIENTFLOW_STATUS_LIVENESS_TIMEOUT_SECONDS' not in presence
    assert 'CLIENTFLOW_STATUS_LIVENESS_TIMEOUT_SECONDS' not in render
    assert 'CLIENTFLOW_ONLINE_TIMEOUT_SECONDS' not in render
    assert "SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 30" in runtime_constants
    assert "time.sleep(SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS)" in status_agent
    assert "now - self._last_status < SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS" in command_agent
    assert "CLIENTFLOW_STATUS_INTERVAL_SECONDS" not in status_agent


def test_client_model_and_routes_do_not_retain_legacy_liveness_authority():
    models = read_backend("service1/models.py")
    clients = read_backend("service1/routers/clients.py")
    enrollment = read_backend("service1/routers/enrollment.py")

    client_model = models.split("class Client(ClientBase, table=True):", 1)[1].split("class ClientDomainPresenceRead", 1)[0]
    client_read = models.split("class ClientRead(ClientBase):", 1)[1].split("class ClientCreate", 1)[0]
    assert "isOnline" not in client_model
    assert "\n    last_seen:" not in client_model
    assert "isOnline" not in client_read
    assert "\n    last_seen:" not in client_read
    assert '@router.post("/clients/{id}/heartbeat"' not in clients
    assert "client.last_seen" not in clients
    assert "client.isOnline" not in clients
    assert "last_seen=now" not in enrollment
    assert "isOnline=False" not in enrollment


def test_reads_use_batch_presence_and_dedicated_presence_endpoint():
    clients = read_backend("service1/routers/clients.py")
    presence = read_backend("service1/client_presence.py")
    assert "load_client_presences(session, clients)" in clients
    assert '@router.get("/clients/{id}/presence", response_model=ClientPresenceRead)' in clients
    assert "return load_client_presence(session, client).public_dict()" in clients
    presence_route = clients.split('@router.get("/clients/{id}/presence"', 1)[1].split('@router.get("/clients/{id}/chrome-status"', 1)[0]
    assert 'response.headers["Cache-Control"] = "no-store, max-age=0"' in presence_route
    assert "ClientDomainStatus.client_id.in_(client_ids)" in presence
    assert "ClientDomainCredential.id.in_(credential_ids)" in presence
    chrome_get = clients.split('@router.get("/clients/{id}/chrome-status")', 1)[1].split('@router.put("/clients/{id}/chrome-status")', 1)[0]
    assert '"last_seen"' not in chrome_get
    assert '"isOnline"' not in chrome_get
    assert '"is_online"' not in chrome_get


def test_network_diagnostics_are_not_a_command_authority():
    clients = read_backend("service1/routers/clients.py")
    derive = clients.split("def _derive_network_status", 1)[1].split("def _set_runtime_read_attr", 1)[0]
    assert "is_online(" not in derive
    assert "heartbeat" not in derive.lower()
    assert "_client_network_unavailable" not in clients


def test_live_only_legacy_action_guards_use_canonical_status_liveness_only():
    clients = read_backend("service1/routers/clients.py")
    assert "def _require_client_online(" in clients
    assert "evidence.is_online" in clients
    assert "_require_domain_ready" not in clients
    assert "_shared_domain_for_action" not in clients
    assert "_client_network_unavailable" not in clients
    assert "current legacy action endpoints are not producers for the shared ClientCommand" in clients
    update_guard = clients.split("def _validate_client_update_command_availability", 1)[1].split('@router.put("/clients/{id}/update"', 1)[0]
    assert "_require_client_online(session, client)" in update_guard
    assert "network_has_connection" not in update_guard


def test_os_update_staleness_uses_os_specific_timestamps_only():
    clients = read_backend("service1/routers/clients.py")
    stale = clients.split("def _os_update_is_stale", 1)[1].split("def _normalize_os_update_state_if_finished", 1)[0]
    assert 'ubuntu_update_updated_at' in stale
    assert 'ubuntu_update_started_at' in stale
    assert 'last_seen' not in stale
    assert 'chrome_last_updated' not in stale


def test_every_clientread_response_path_attaches_canonical_presence():
    clients = read_backend("service1/routers/clients.py")

    route_expectations = {
        'def get_clients_for_my_organization': '_prepare_clients_read(session, clients)',
        'def get_clients(': '_prepare_clients_read(session, clients)',
        'def get_deleted_clients(': '_prepare_clients_read(session, clients)',
        'def get_deleted_clients_slash': 'return get_deleted_clients(session=session, user=user)',
        'def get_client(': 'return _prepare_client_read(client, presence)',
        'async def create_client': 'return _prepare_client_read(client, load_client_presence(session, client))',
        'async def update_client': 'return _prepare_client_read(client, load_client_presence(session, client))',
        'async def update_kiosk_url': 'return _prepare_client_read(client, load_client_presence(session, client))',
        'async def approve_client': 'return _prepare_client_read(client, load_client_presence(session, client))',
        'async def restore_client': '_prepare_client_read(client, load_client_presence(session, client))',
    }
    for marker, expected in route_expectations.items():
        section = clients.split(marker, 1)[1]
        next_route = section.find("\n@router.")
        if next_route >= 0:
            section = section[:next_route]
        assert expected in section, marker


def test_step52a_drops_legacy_columns_and_is_the_reviewed_head():
    migration = read_backend("migrations/versions/20260822_52a_client_liveness_authority.py")
    contract = read_backend("scripts/display_schema_contract.py")
    runner = read_backend("scripts/run_migrations.py")
    assert 'revision = "20260822_52a_client_liveness"' in migration
    assert 'down_revision = "20260820_51b_update_auth"' in migration
    assert 'op.drop_column("client", "last_seen")' in migration
    assert 'op.drop_column("client", "isOnline")' in migration
    assert contract.rsplit('EXPECTED_HEAD_REVISION = ', 1)[1].splitlines()[0] == '"20260823_53a_display_authority"'
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260823_53a_display_authority"' in runner
    assert 'REVIEWED_LEGACY_RECONCILIATION_HEAD = "20260823_53a_display_authority"' in runner
    assert 'REVIEWED_CLIENT_LIVENESS_REVISION = "20260822_52a_client_liveness"' in runner
    assert "_without_client_liveness_schema" in runner
