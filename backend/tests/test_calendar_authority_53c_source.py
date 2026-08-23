from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_53c_release_identity_advances_without_catalog_promotion() -> None:
    assert read("client/VERSION").strip() == "1.3.7"
    release_input = json.loads(read("client/release/release-input.json"))
    assert release_input["release_sequence"] == 1208
    catalog = json.loads(read("backend/service1/clientflow_release_catalog.json"))
    assert catalog["latest_stable"] == "1.3.4"
    assert catalog["default_install_version"] == "1.3.4"
    assert catalog["releases"][0]["revision"] == "clientflow-1.3.4-seq-1205"


def test_53c_calendar_delivery_is_display_domain_self_only_and_complete() -> None:
    shared = read("backend/service1/routers/shared_domain.py")
    control = read("backend/service1/calendar_control.py")
    calendar = read("backend/service1/routers/calendar.py")

    assert '@router.get("/display-agent/clients/{client_id}/calendar")' in shared
    endpoint = shared[shared.index('def display_calendar('):shared.index('@router.put("/status-agent', shared.index('def display_calendar('))]
    assert 'domain="display"' in endpoint
    assert "build_display_calendar_delivery" in endpoint
    assert "require_shared_agent_token" in endpoint

    assert "current_and_next_seasons()" in control
    assert "validate_and_normalize_markings" in control
    assert "require_complete=True" in control
    assert 'status_code=409' in control
    assert '"revision": _revision_for(seasons)' in control
    assert 'return {"ok": True, "delivery": "client_poll"}' in calendar


def test_53c_calendar_agent_uses_display_credential_local_wall_clock_and_cache() -> None:
    agent = read("client/runtime/clientflow_runtime/calendar_agent.py")

    assert "DomainCredential.load(Domain.DISPLAY)" in agent
    assert "/api/display-agent/clients/{client_id}/calendar" in agent
    assert "CACHE_PATH" in agent and "atomic_write_json(CACHE_PATH" in agent
    assert "datetime.now().astimezone()" in agent
    assert "Europe/Copenhagen" not in agent
    assert "Domain.SYSTEM" not in agent
    assert "reboot" not in agent.lower()
    assert "shutdown" not in agent.lower()


def test_53c_calendar_transitions_preserve_historical_display_semantics_without_system_reboot() -> None:
    agent = read("client/runtime/clientflow_runtime/calendar_agent.py")
    transition = agent[agent.index("def _apply_transition("):agent.index("def _timezone_label", agent.index("def _apply_transition("))]

    on_block = transition[transition.index('if state == "on"'):transition.index('if state == "off"')]
    assert on_block.index('set_display_power("on")') < on_block.index('runtime_action("start_browser")')
    off_block = transition[transition.index('if state == "off"'):]
    assert off_block.index('runtime_action("stop_browser")') < off_block.index('set_display_power("off")')
    assert "display_control_lock()" in transition


def test_53c_calendar_and_manual_display_commands_share_one_local_control_lock() -> None:
    helper = read("client/runtime/clientflow_runtime/display_local_control.py")
    display_agent = read("client/runtime/clientflow_runtime/display_agent.py")
    calendar_agent = read("client/runtime/clientflow_runtime/calendar_agent.py")

    assert "fcntl.flock" in helper
    assert "CONTROL_LOCK_PATH" in helper
    assert "with display_control_lock():" in display_agent
    assert "with display_control_lock():" in calendar_agent


def test_53c_calendar_status_is_canonical_display_projection_not_legacy_client_write() -> None:
    display_agent = read("client/runtime/clientflow_runtime/display_agent.py")
    display_control = read("backend/service1/display_control.py")
    clients = read("backend/service1/routers/clients.py")

    assert '"calendar": _read_object(CALENDAR_STATUS_PATH)' in display_agent
    assert 'calendar_raw = status_payload.get("calendar")' in display_control
    assert '"service_calendar_status": calendar_service_status' in display_control
    assert '_set_runtime_read_attr(client, "service_calendar_status", projection["service_calendar_status"])' in clients
    assert '"service_calendar_status"' in clients[clients.index("LEGACY_DISPLAY_STATUS_WRITE_FIELDS"):clients.index("def _reject_legacy_display_write_fields")]


def test_53c_calendar_service_is_display_subcomponent_and_target_managed() -> None:
    service = read("client/systemd/clientflow-calendar.service")
    target = read("client/systemd/clientflow.target")
    pyproject = read("client/runtime/pyproject.toml")
    frontend = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")

    assert "User=clientflow-display-agent" in service
    assert "Group=clientflow-display-agent" in service
    assert "SupplementaryGroups=clientflow-display-control" in service
    assert "LoadCredential=display.json:/etc/clientflow/credentials/display.json" in service
    assert "WantedBy=clientflow.target" in service
    assert "ReadWritePaths=/var/lib/clientflow/display-agent" in service
    assert "clientflow-calendar.service" in target
    assert 'clientflow-calendar = "clientflow_runtime.calendar_agent:main"' in pyproject
    assert 'unit: "clientflow-calendar.service"' in frontend
    assert "clientflow_calendar.service" not in frontend


def test_53c_does_not_modify_frozen_domain_runtime_contracts() -> None:
    calendar = read("client/runtime/clientflow_runtime/calendar_agent.py")
    helper = read("client/runtime/clientflow_runtime/display_local_control.py")
    combined = calendar + helper
    for forbidden in (
        "livestream",
        "remote_desktop",
        "terminal",
        "clientflow-terminal",
        "clientflow-livestream",
        "clientflow-remote-desktop",
    ):
        assert forbidden not in combined.lower()



def test_53c_manual_display_override_is_boot_bound_and_apply_configuration_is_not_manual() -> None:
    helper = read("client/runtime/clientflow_runtime/display_local_control.py")
    display_agent = read("client/runtime/clientflow_runtime/display_agent.py")
    calendar_agent = read("client/runtime/clientflow_runtime/calendar_agent.py")

    assert "calendar-override.json" in helper
    assert 'BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")' in helper
    assert "calendar_manual_override_created_at" in helper
    assert "record_calendar_manual_override(context.command_type)" in display_agent
    apply_block = display_agent[
        display_agent.index('if context.command_type in {"apply_configuration"'):
        display_agent.index('except RpcError', display_agent.index('if context.command_type in {"apply_configuration"'))
    ]
    assert 'context.command_type != "apply_configuration"' in apply_block
    assert "_calendar_boundary_since" in calendar_agent
    assert "clear_calendar_manual_override()" in calendar_agent
    assert "RECONCILE_SECONDS" in calendar_agent
