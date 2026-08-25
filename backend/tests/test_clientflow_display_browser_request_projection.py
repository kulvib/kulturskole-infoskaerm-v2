from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from service1 import display_control


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
        def get(self, _model, _id):
            return client

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
    monkeypatch.setattr(clients, "display_read_projection", lambda *_args, **_kwargs: projection)
    monkeypatch.setattr(clients, "_require_client_read_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clients, "load_client_presence", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(clients, "_apply_status_runtime_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clients, "_apply_system_projection_for_read", lambda *_args, **_kwargs: None)

    payload = clients.get_chrome_status(4242, session=_Session(), user=object())

    assert payload["chrome_running"] is False
    assert payload["browser_requested"] is True
    assert payload["chrome_step"] == "chrome_failed"
