from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from service1 import livestream_v2
from service1.routers import clients


def test_status_snapshot_projects_canonical_version_network_and_real_unit_health():
    client = SimpleNamespace()
    presence = SimpleNamespace(
        status=SimpleNamespace(
            agent_version="1.3.12",
            reported_at=datetime(2026, 8, 28, 12, 0, 0),
            status_payload={
                "uptime_seconds": 123.9,
                "ubuntu_version": "Ubuntu 26.04 LTS",
                "diagnostics_updated_at": "2026-08-28T12:00:00Z",
                "client_time_utc": "2026-08-28T12:00:00Z",
                "system_timezone": "Europe/Copenhagen",
                "ntp_enabled": True,
                "ntp_synchronized": True,
                "active_network_type": "lan",
                "active_network_interface": "enp1s0",
                "active_network_ip": "192.0.2.10",
                "active_network_mac": "02:00:00:00:00:10",
                "lan_ip_address": "192.0.2.10",
                "lan_mac_address": "02:00:00:00:00:10",
                "services": {
                    "clientflow.target": "active",
                    "clientflow-display-runtime.service": "active",
                    "clientflow-root-terminal-broker.socket": "active",
                    "clientflow-updater.timer": "active",
                },
            },
        )
    )

    clients._apply_status_runtime_snapshot(client, presence)

    assert client.client_version == "1.3.12"
    assert client.client_version_updated_at == presence.status.reported_at
    assert client.uptime == "123"
    assert client.ubuntu_version == "Ubuntu 26.04 LTS"
    assert client.active_network_interface == "enp1s0"
    assert client.service_clientflow_status == "active"
    assert client.service_browser_guard_status == "active"
    assert client.service_admin_terminal_status == "active"
    assert client.service_selfupdate_status == "active"


def test_lockdown_desired_mutation_fails_closed_until_canonical_consumer_exists():
    with pytest.raises(HTTPException) as exc:
        clients._validate_client_update_privileges(
            SimpleNamespace(is_superadmin=True, role="superadmin"),
            SimpleNamespace(),
            {"desktop_lockdown_enabled"},
        )
    assert exc.value.status_code == 409
    assert "ikke en understøttet canonical" in str(exc.value.detail)


@pytest.mark.parametrize("state", ["shutdown", "rebooting", "updating"])
def test_livestream_generation_creation_is_blocked_during_system_lifecycle(state):
    client = SimpleNamespace(state=state, pending_shutdown=False, pending_reboot=False)
    with pytest.raises(HTTPException) as exc:
        livestream_v2._require_livestream_start_allowed(client)
    assert exc.value.status_code == 409


def test_livestream_generation_creation_is_blocked_by_pending_power_action():
    for pending_shutdown, pending_reboot in ((True, False), (False, True)):
        client = SimpleNamespace(
            state="normal",
            pending_shutdown=pending_shutdown,
            pending_reboot=pending_reboot,
        )
        with pytest.raises(HTTPException):
            livestream_v2._require_livestream_start_allowed(client)


def test_livestream_generation_creation_is_allowed_in_normal_runtime():
    livestream_v2._require_livestream_start_allowed(
        SimpleNamespace(state="normal", pending_shutdown=False, pending_reboot=False)
    )
