from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from service1 import display_control
from service1.client_presence import ClientPresence, DomainPresence


def test_display_projection_separates_process_running_from_browser_request(monkeypatch):
    desired = SimpleNamespace(kiosk_url="https://example.test/", revision=7)
    status = SimpleNamespace(
        status_payload={
            "runtime": {
                "state": "failed",
                "browser_pid": None,
                "browser_requested": True,
                "configuration_revision": 7,
                "error": "browser_exited",
                "updated_at": 1_780_000_000.0,
            }
        },
        reported_at=datetime(2026, 8, 25, 18, 0, 0),
        agent_version="1.3.10",
    )

    monkeypatch.setattr(display_control, "get_display_desired_configuration", lambda *_args, **_kwargs: desired)
    monkeypatch.setattr(display_control, "latest_display_status", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(display_control, "active_display_control_command", lambda *_args, **_kwargs: None)

    projection = display_control.display_read_projection(object(), 4242)

    assert projection["chrome_running"] is False
    assert projection["browser_requested"] is True
    assert projection["chrome_step"] == "chrome_failed"
    assert projection["pending_chrome_action"] == "none"


def test_chrome_status_route_surfaces_browser_request_state(monkeypatch):
    from service1.routers import clients

    class _Client:
        id = 4242
        chrome_status = None
        chrome_color = None
        chrome_step = None
        chrome_last_updated = None
        chrome_running = False
        pending_chrome_action = "none"
        pending_reboot = False
        pending_shutdown = False
        uptime = None

        def __getattr__(self, _name):
            return None

    client = _Client()

    class _Session:
        pass

    projection = {
        "kiosk_url": "https://example.test/",
        "chrome_status": "Browserfejl: browser_exited",
        "chrome_color": "red",
        "chrome_step": "chrome_failed",
        "chrome_running": False,
        "browser_requested": True,
        "chrome_last_updated": datetime(2026, 8, 25, 18, 0, 0),
        "pending_chrome_action": "none",
        "pending_chrome_action_source": None,
        "service_calendar_status": None,
    }
    monkeypatch.setattr(
        clients,
        "display_read_projections",
        lambda *_args, **_kwargs: {4242: projection},
    )
    monkeypatch.setattr(clients, "_require_client_read_access", lambda *_args, **_kwargs: None)
    presence = ClientPresence(
        status=DomainPresence(domain="status", is_online=True, reason="fresh_online_status"),
        display=DomainPresence(domain="display", is_online=True, reason="fresh_online_status"),
        system=DomainPresence(domain="system", is_online=True, reason="fresh_online_status"),
    )
    monkeypatch.setattr(
        clients,
        "load_client_with_presence_rows",
        lambda *_args, **_kwargs: (client, presence, {(4242, "display"): object()}),
    )
    monkeypatch.setattr(
        clients,
        "load_latest_system_projection_commands",
        lambda *_args, **_kwargs: {4242: {"power": None, "os_update": None, "local_management": None}},
    )
    monkeypatch.setattr(clients, "_apply_status_runtime_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clients, "_apply_system_projection_for_read", lambda *_args, **_kwargs: None)

    payload = clients.get_chrome_status(4242, session=_Session(), user=object())

    assert payload["presence"] == presence.public_dict()
    assert payload["chrome_running"] is False
    assert payload["browser_requested"] is True
    assert payload["chrome_step"] == "chrome_failed"


def test_display_projection_preserves_precise_runtime_browser_messages() -> None:
    desired = SimpleNamespace(kiosk_url="https://example.test/", revision=8, browser_refresh_interval_sec=900)
    status = SimpleNamespace(
        status_payload={
            "runtime": {
                "state": "countdown",
                "step": "countdown",
                "countdown_reason": "configuration_change",
                "countdown_remaining": 7,
                "browser_requested": True,
                "updated_at": 1_780_000_100.0,
            }
        },
        reported_at=datetime(2026, 8, 25, 18, 0, 0),
        agent_version="1.3.29",
    )

    projection = display_control._display_read_projection_from_rows(desired, status, None)

    assert projection["chrome_status"] == "Kiosk browser starter ved URL-skift om 7 sekunder…"
    assert projection["chrome_color"] == "orange"
    assert projection["chrome_step"] == "countdown"
    assert projection["chrome_running"] is False


def test_display_power_transition_overrides_stale_generic_browser_text() -> None:
    desired = SimpleNamespace(kiosk_url="https://example.test/", revision=9, browser_refresh_interval_sec=900)
    status = SimpleNamespace(
        status_payload={
            "runtime": {
                "state": "running",
                "browser_pid": 4242,
                "event_source": "system_start",
                "browser_requested": True,
                "updated_at": 1_780_000_100.0,
            },
            "display_power": {"state": "on", "updated_at": 1_780_000_105.0},
        },
        reported_at=datetime(2026, 8, 25, 18, 0, 0),
        agent_version="1.3.29",
    )

    projection = display_control._display_read_projection_from_rows(desired, status, None)

    assert projection["chrome_status"] == "Skærm vækket — klient online"
    assert projection["chrome_color"] == "green"
    assert projection["chrome_step"] == "display_wake_complete"
    assert projection["chrome_running"] is True
