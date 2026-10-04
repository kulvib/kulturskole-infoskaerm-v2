from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_command_wakeup_is_commit_coupled_and_payload_free():
    wake = read("backend/service1/realtime_wakeup.py")
    db = read("backend/service1/db.py")
    shared = read("backend/service1/routers/shared_domain.py")
    command_agent = read("client/runtime/clientflow_runtime/command_agent.py")
    assert "queue_wakeup_after_commit" in wake
    assert "after_commit" in db
    assert "command_available" in shared
    assert "/commands/wait" in shared
    assert "/commands/wake/ws" in shared
    assert "WSS wake channel with HTTPS long-poll fallback" in command_agent
    assert "max(60.0, self.poll_seconds)" in command_agent
    assert "claimed" not in wake


def test_livestream_media_hot_path_has_db_free_capability():
    capability = read("backend/service1/livestream_media_capability.py")
    main = read("backend/service1/main.py")
    router = read("backend/service1/routers/livestream_v2.py")
    media = read("backend/service1/routers/livestream_media.py")
    assert "livestream_media_read" in capability
    assert "TTL_SECONDS" in capability
    assert "verify_livestream_media_capability(token, client_id=client_id)" in main
    assert '"media_capability": media_capability' in router
    assert '"/hls-cap/{client_id}/health"' in media


def test_browser_presence_is_ephemeral_not_15_second_db_heartbeat():
    activity = read("backend/service1/client_activity.py")
    assert "_ACTIVE_PRESENCE" in activity
    maintain = activity[activity.index("async def maintain_activity_lease") :]
    assert "await asyncio.Event().wait()" in maintain
    assert "await asyncio.sleep(ACTIVITY_RENEW_SECONDS)" not in maintain


def test_remote_desktop_idle_transport_is_adaptive_and_deduplicated():
    agent = read("client/runtime/clientflow_runtime/remote_desktop_agent.py")
    browser = read("frontend/src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx")
    assert "hashlib.sha256" in agent
    assert "unchanged" in agent
    assert "stream_mode_updated" in agent
    assert "RD_ACTIVE_FPS = 6" in browser
    assert "RD_IDLE_FPS = 1" in browser
    assert "RD_DEEP_IDLE_FPS = 0.2" in browser
    assert "visibilitychange" in browser
    assert 'startStream("deep_idle")' in browser
    assert "stopStream();" in browser


def test_fresh_install_requires_lockdown_before_final_reboot():
    enrollment = read("backend/service1/routers/enrollment.py")
    bootstrap = read("client/bootstrap/clientflow-fresh-install")
    assert "desktop_lockdown_enabled=True" in enrollment
    apply_pos = bootstrap.index("_apply_customer_kiosk_lockdown()", bootstrap.index("def _customer_install"))
    reboot_pos = bootstrap.index('confirmed_reboot("kundeaktivering afventer post-final-reboot acceptance"')
    assert apply_pos < reboot_pos
    assert 'payload.get("status") != "applied"' in bootstrap


def test_control_room_realtime_wait_is_capability_scoped_and_db_free():
    realtime = read("backend/service1/ui_realtime.py")
    clients = read("backend/service1/routers/clients.py")
    details = read("frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx")
    listing = read("frontend/src/pages/ClientInfoPage.jsx")
    assert "ui_realtime_wait" in realtime
    assert "wait_for_ui_change" in realtime
    assert '"/clients/control-room-realtime/capability"' in clients
    assert '"/clients/control-room-realtime/wait"' in clients
    wait_block = clients[clients.index("def wait_control_room_realtime"):clients.index('@router.get("/clients/deleted"')]
    assert "Depends(get_session)" not in wait_block
    assert "waitForControlRoomRealtime(capability, generation, 25)" in details
    assert "CHROME_STATUS_IDLE_POLL_MS = 60000" in details
    assert "waitForControlRoomRealtime(capability, generation, 25)" in listing
    assert "CLIENT_LIST_IDLE_POLL_MS = 60_000" in listing


def test_calendar_uses_push_assisted_invalidation_with_conditional_reconciliation():
    agent = read("client/runtime/clientflow_runtime/calendar_agent.py")
    calendar = read("backend/service1/routers/calendar.py")
    organizations = read("backend/service1/routers/organizations.py")
    assert 'CLIENTFLOW_CALENDAR_POLL_SECONDS", "300"' in agent
    assert "_wait_for_calendar_wake" in agent
    assert "If-None-Match" in agent
    assert 'domain="display"' in calendar
    assert '"push_assisted_conditional_fetch"' in calendar
    assert 'domain="display"' in organizations


def test_municipal_firewall_fallback_covers_terminal_and_remote_desktop():
    relay = read("backend/service1/http_ws_relay.py")
    terminal = read("backend/service1/routers/terminal.py")
    remote = read("backend/service1/routers/remote_desktop_v2.py")
    terminal_agent = read("client/runtime/clientflow_runtime/terminal_agent.py")
    remote_agent = read("client/runtime/clientflow_runtime/remote_desktop_agent.py")
    terminal_ui = read("frontend/src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx")
    remote_ui = read("frontend/src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx")
    frontend_relay = read("frontend/src/api/httpRelaySocket.js")

    assert "QUEUE_DEPTH = 64" in relay
    assert "MAX_QUEUE_BYTES = 48 * 1024 * 1024" in relay
    assert "RELAY_TTL_SECONDS = 15 * 60" in relay
    assert "MAX_TOTAL_QUEUE_BYTES = 128 * 1024 * 1024" in relay
    assert "MAX_RELAYS_PER_OWNER = 8" in relay
    assert "RELAY_CLOSE_GRACE_SECONDS = 30" in relay
    assert "_reserve_global_bytes" in relay
    assert "_relay_owner_key" in relay
    assert "process-local" in relay
    for source in (terminal, remote):
        assert "/http/open" in source
        assert "/http/{relay_id}/send" in source
        assert "/http/{relay_id}/poll" in source
    assert "terminal_websocket_unavailable_using_https_fallback" in terminal_agent
    assert "remote_desktop_websocket_unavailable_using_https_fallback" in remote_agent
    assert "createWebSocketWithHttpsFallback" in frontend_relay
    assert "createWebSocketWithHttpsFallback" in terminal_ui
    assert "createWebSocketWithHttpsFallback" in remote_ui
    assert "https_long_poll" in frontend_relay


def test_livestream_durable_queue_is_push_assisted_with_https_fallback():
    wake = read("backend/service1/realtime_wakeup.py")
    service = read("backend/service1/livestream_v2.py")
    router = read("backend/service1/routers/livestream_v2.py")
    agent = read("client/runtime/clientflow_runtime/command_agent.py")
    assert '"livestream"' in wake
    assert 'queue_wakeup_after_commit(session, domain="livestream", client_id=client_id)' in service
    assert '"/livestream-agent/clients/{client_id}/commands/wait"' in router
    assert '"/livestream-agent/clients/{client_id}/commands/wake/ws"' in router
    assert '{"display", "system", "livestream"}' in agent
    assert "max(60.0, self.poll_seconds)" in agent


def test_shared_liveness_keeps_15_second_freshness_without_15_second_db_writes():
    ephemeral = read("backend/service1/ephemeral_presence.py")
    shared = read("backend/service1/routers/shared_domain.py")
    presence = read("backend/service1/client_presence.py")
    status_agent = read("client/runtime/clientflow_runtime/status_agent.py")
    command_agent = read("client/runtime/clientflow_runtime/command_agent.py")
    assert "touch_presence" in ephemeral
    for domain in ("status", "display", "system"):
        assert f'/{domain}-agent/clients/{{client_id}}/presence' in shared
    assert "ephemeral_last_seen" in presence
    assert "DURABLE_STATUS_CHECKPOINT_SECONDS = 60.0" in status_agent
    assert "CLIENTFLOW_STATUS_DURABLE_CHECKPOINT_SECONDS" not in status_agent
    assert "_STATUS_FINGERPRINT_VOLATILE_FIELDS" in status_agent
    for volatile in ("uptime_seconds", "client_time_utc", "diagnostics_updated_at", "load_average"):
        assert f'"{volatile}"' in status_agent
    assert "_durable_status_checkpoint_seconds = 60.0" in command_agent
    assert "_send_presence_if_due" in command_agent


def test_livestream_viewer_steady_presence_does_not_rewrite_last_seen():
    presence = read("backend/service1/livestream_presence.py")
    service = read("backend/service1/livestream_v2.py")
    assert "ephemeral_viewer_touch" in service
    assert "ephemeral_viewer_leave" in service
    assert "active_keys" in presence
    heartbeat = service[service.index("def viewer_heartbeat("):service.index("def viewer_leave(")]
    # Existing active viewer rows are not rewritten merely to renew last_seen;
    # the timestamp is only persisted when an ended viewer is re-opened.
    steady = heartbeat[heartbeat.index("if row.ended_at is not None:"):]
    assert steady.count("row.last_seen_at = now") == 1
    assert "Steady heartbeats are ephemeral" in heartbeat
    assert "ephemeral_viewer_touch(" in heartbeat


def test_remote_desktop_media_has_transport_boundary_and_local_measurement():
    agent = read("client/runtime/clientflow_runtime/remote_desktop_agent.py")
    browser = read("frontend/src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx")
    assert "class RemoteDesktopMediaTransport(Protocol)" in agent
    assert "class JpegRpcMediaTransport" in agent
    assert "media-telemetry.json" in agent
    for field in (
        "captured_frames", "relayed_frames", "unchanged_frames", "relayed_bytes",
        "capture_ms_avg", "input_to_frame_ms_last", "input_to_frame_ms_avg",
    ):
        assert field in agent
    assert 'msg.type === "file_activity"' in browser
    assert "markRemoteActivity();" in browser


def test_reconnect_backoff_has_bounded_jitter():
    for path in (
        "client/runtime/clientflow_runtime/net.py",
        "client/runtime/clientflow_runtime/terminal_net.py",
        "client/runtime/clientflow_runtime/remote_desktop_net.py",
    ):
        source = read(path)
        assert "random.uniform(0.8, 1.2)" in source
        assert "min(60.0" in source


def test_current_hls_paths_prefer_short_lived_capability_without_url_secret():
    main = read("backend/service1/main.py")
    router = read("backend/service1/routers/livestream_v2.py")
    browser = read("frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx")
    assert 'clientflow_hls_media_capability' in main
    assert 'response.set_cookie(' in router
    assert 'key="clientflow_hls_media_capability"' in router
    assert 'httponly=True' in router
    assert 'secure=True' in router
    assert 'samesite="strict"' in router
    assert 'xhr.setRequestHeader("Authorization", `Bearer ${token}`)' in browser
    assert "media_capability=" not in browser


def test_https_relay_browser_access_is_bound_to_login_session_context():
    terminal = read("backend/service1/routers/terminal.py")
    remote = read("backend/service1/routers/remote_desktop_v2.py")
    for source in (terminal, remote):
        assert '"auth_session_binding"' in source
        assert '"user_token_version"' in source
    assert "require_active_browser_auth_session_binding" in terminal
    assert "_http_browser_session_binding" in remote


def test_livestream_media_capability_is_parent_session_bounded():
    capability = read("backend/service1/livestream_media_capability.py")
    router = read("backend/service1/routers/livestream_v2.py")
    auth = read("backend/service1/auth.py")
    assert "get_access_token_session_context" in auth
    assert '"auth_session_binding"' in capability
    assert '"parent_session_exp"' in capability
    assert "min(ttl_expiry, parent_expiry)" in capability
    assert "get_access_token_session_context(token, user)" in router


def test_customer_handoff_is_accepted_only_after_final_reboot_runtime_gate():
    bootstrap = read("client/bootstrap/clientflow-fresh-install")
    gate = read("client/runtime/clientflow_runtime/post_final_reboot_acceptance.py")
    session_policy = read("client/runtime/clientflow_runtime/kiosk_session_policy.py")
    unit = read("client/systemd/clientflow-post-final-reboot-acceptance.service")
    target = read("client/systemd/clientflow.target")
    pyproject = read("client/runtime/pyproject.toml")
    hardening = read("CLIENTFLOW_1.3.30_1231_REALTIME_COST_HARDENING.md")
    assert '"status": "awaiting_post_final_reboot_acceptance"' in bootstrap
    assert "_stage_post_final_reboot_acceptance()" in bootstrap
    assert 'phase("9/9 · Final reboot og post-boot acceptance")' in bootstrap
    assert '"status": "accepted"' in gate
    assert "current_boot == previous_boot" in gate
    assert "_active_local_kiosk_session()" in gate
    assert '"--property=Type"' in session_policy
    assert 'properties.get("Type", "").lower() == "wayland"' in session_policy
    assert 'lockdown.get("status") != "applied"' in gate
    assert "_verify_nautilus_ding_session()" in gate
    assert "kiosk_url = _verify_display_runtime(current_boot)" in gate
    assert "EXPECTED_BOOT_COUNTDOWN_SECONDS = 10" in gate
    assert "_verify_critical_services()" in gate
    assert "_verify_browser_guard(kiosk_url)" in gate
    assert "_verify_backend_approved()" in gate
    assert "DomainCredential.load(Domain.STATUS)" in gate
    assert "DomainTransport(credential).access_token(force_refresh=True)" in gate
    assert "org.freedesktop.DBus.StartServiceByName" in gate
    assert "visibleConsent" in gate
    assert "clientflow-post-final-reboot-acceptance" in pyproject
    assert "clientflow-post-final-reboot-acceptance.service" in target
    assert "After=network-online.target" in unit
    assert "CLIENTFLOW_CREDENTIAL_FILE=/etc/clientflow/credentials/status.json" in unit
    assert "Restart=on-failure" in unit
    for documented_proof in (
        "exact 10-second startup contract",
        "configured kiosk URL",
        "Browser Guard/cookie/consent behavior",
        "healthy critical ClientFlow services",
        "client is `Approved`",
        "keeps the handoff fail-closed",
    ):
        assert documented_proof in hardening
