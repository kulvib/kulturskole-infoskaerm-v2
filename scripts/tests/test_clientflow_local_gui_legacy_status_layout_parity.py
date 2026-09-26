from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_display_runtime_preserves_canonical_browser_event_source() -> None:
    source = _source("client/runtime/clientflow_runtime/display_runtime.py")

    for token in (
        'self._status("starting", step="starting_chrome", event_source=source)',
        'self._status("running", step="start_chrome", event_source=source)',
        'self._status("stopping", step="terminate_chrome", event_source=source)',
        'self._status("stopped", step="chrome_closed_programmatically", event_source=source)',
        'self.stop_browser(preserve_request=True, source="url_change")',
        'self.start_browser(source="url_change")',
        'self.stop_browser(preserve_request=True, source="reset_browser")',
        'self.start_browser(source="reset_browser")',
    ):
        assert token in source

    assert 'return self.stop_browser(source=source)' in source
    assert 'source=str(payload.get("source") or "") or None' in source


def test_local_gui_uses_legacy_equivalent_sourceful_messages() -> None:
    source = _source("client/libexec/local-gui")

    for message in (
        "Starter kiosk browser fra backend…",
        "Starter kiosk browser fra GUI…",
        "Starter kiosk browser fra kalender…",
        "Starter kiosk browser ved systemstart…",
        "Kiosk browser startet fra backend",
        "Kiosk browser startet fra GUI på klient",
        "Kiosk browser startet fra kalender",
        "Kiosk browser startet ved systemstart",
        "Kiosk browser startet ved URL-skift",
        "Kiosk browser lukket fra backend",
        "Kiosk browser lukket fra GUI på klient",
        "Kiosk browser lukket fra kalender",
        "Kiosk browser lukket ved URL-skift",
        "Kiosk browser lukket — klient genstarter",
        "Kiosk browser lukket — klient lukker ned",
        "Kiosk browser nulstilles — lukker browser…",
        "Klient genstarter…",
        "Klient lukker ned…",
        "Skærm slukket — klienten er stadig online",
    ):
        assert message in source

    assert 'source = str(runtime.get("event_source") or "runtime")' in source


def test_local_gui_button_lock_covers_busy_and_power_transitions() -> None:
    source = _source("client/libexec/local-gui")

    assert 'busy = state in {"countdown", "resetting", "waiting_session", "starting", "stopping"}' in source
    assert 'system_locked = str(runtime.get("step") or "").lower()' in source
    for step in ("shutdown_chrome", "system_rebooting", "system_shutting_down"):
        assert f'"{step}"' in source
    assert "not system_locked" in source
    assert 'if action in {"start_browser", "stop_browser"}:' in source
    assert 'payload["payload"] = {"source": "gui"}' in source


def test_local_gui_typography_uses_legacy_point_units_not_css_pixels() -> None:
    source = _source("client/libexec/local-gui")

    assert "font-family: Arial, sans-serif;" in source
    assert "font-size: {normal}pt;" in source
    assert "font-size: {heading}pt;" in source
    assert "font-size: {big}pt;" in source
    assert "font-size: {normal}px;" not in source
    assert "font-size: {heading}px;" not in source
    assert "font-size: {big}px;" not in source
    assert '"Skift til administrator"' not in source


def test_system_broker_preserves_reboot_shutdown_source_without_broadening_authority() -> None:
    source = _source("client/runtime/clientflow_runtime/system_broker.py")

    assert 'transition_source = "pending_reboot" if action == "reboot" else "pending_shutdown"' in source
    assert '"action": "stop_browser"' in source
    assert '"action": "record_system_transition"' in source
