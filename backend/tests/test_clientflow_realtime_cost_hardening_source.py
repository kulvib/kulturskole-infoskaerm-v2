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
    reboot_pos = bootstrap.index('confirmed_reboot("kundeaktivering gennemført med kiosk lockdown"')
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
