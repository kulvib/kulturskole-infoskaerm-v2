from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_53b_migration_extends_53a_and_retires_plaintext_secret() -> None:
    migration = read("backend/migrations/versions/20260823_53b_system_authority.py")
    contract = read("backend/scripts/display_schema_contract.py")
    runner = read("backend/scripts/run_migrations.py")
    model = read("backend/service1/models.py")

    assert 'revision = "20260823_53b_system_authority"' in migration
    assert 'down_revision = "20260823_53a_display_authority"' in migration
    assert 'op.drop_column("client", "local_management_secret")' in migration
    assert "pending_reboot = false" in migration
    assert "pending_shutdown = false" in migration
    assert "pending_os_update = false" in migration
    assert 'EXPECTED_HEAD_REVISION = "20260823_53b_system_authority"' in contract
    assert 'REVIEWED_SYSTEM_AUTHORITY_REVISION = "20260823_53b_system_authority"' in runner
    assert "system_authority_revision.down_revision != REVIEWED_DISPLAY_AUTHORITY_REVISION" in runner
    assert "local_management_secret:" not in model


def test_53b_system_commands_use_shared_system_queue_only() -> None:
    control = read("backend/service1/system_control.py")
    clients = read("backend/service1/routers/clients.py")
    agent = read("client/runtime/clientflow_runtime/system_agent.py")
    broker = read("client/runtime/clientflow_runtime/system_broker.py")

    assert 'SYSTEM_DOMAIN = "system"' in control
    assert 'domain=SYSTEM_DOMAIN' in control
    for command in ("reboot", "shutdown", "update_os", "change_hostname", "change_password"):
        assert f'"{command}"' in control
        assert f'"{command}"' in broker
    assert "Domain.SYSTEM" in agent
    assert "SYSTEM_SOCKET" in agent
    assert 'call(' in agent

    assert '@router.post("/clients/{id}/system-command")' in clients
    assert 'command_type="update_os"' in clients
    assert 'command_type="change_hostname"' in clients
    assert 'command_type="change_password"' in clients
    assert "queue_system_command(" in clients

    forbidden_assignments = re.findall(
        r"client\.(pending_reboot|pending_shutdown|pending_os_update|ubuntu_update_[A-Za-z0-9_]+|local_management_[A-Za-z0-9_]+)\s*=",
        clients,
    )
    assert forbidden_assignments == []


def test_53b_password_is_command_bound_rsa_oaep_before_persistence() -> None:
    control = read("backend/service1/system_control.py")
    clients = read("backend/service1/routers/clients.py")
    broker = read("client/runtime/clientflow_runtime/system_broker.py")

    assert '"algorithm": "RSA-OAEP-SHA256"' in control
    assert '"client_id": int(client_id)' in control
    assert '"command_id": command_id' in control
    assert '"target_user": target_user' in control
    assert '"new_password": new_password' in control
    assert "public_key.encrypt(" in control
    assert "padding.OAEP(" in control
    assert "hashes.SHA256()" in control
    assert "payload_encryption_key_id=key_id" in clients
    assert "local_management_secret" not in control
    assert "local_management_secret" not in clients

    assert 'decrypted.get("target_user") != target_user' in broker
    assert 'int(decrypted.get("client_id", 0)) != client_id' in broker
    assert 'str(decrypted.get("command_id") or "") != command_id' in broker


def test_53b_legacy_system_write_paths_fail_closed() -> None:
    clients = read("backend/service1/routers/clients.py")

    assert 'LEGACY_SYSTEM_COMMAND_FIELDS' in clients
    assert 'SYSTEM_OWNED_STATES = {"rebooting", "shutdown", "updating"}' in clients
    assert 'Legacy System command/status-felter er read-only kompatibilitetsprojektion.' in clients
    assert 'Legacy System state-write er fjernet; canonical System command/status er authority.' in clients
    assert 'Legacy power lifecycle writes er fjernet; canonical System command + Status observation er authority.' in clients
    assert 'Legacy browser/System-status-write er fjernet.' in clients
    assert 'Legacy local-management status er fjernet; canonical System-command completion er authority.' in clients
    assert 'Legacy OS-update reset er fjernet; canonical System-command status kan ikke nulstilles kunstigt.' in clients


def test_53b_completion_and_power_observation_are_not_browser_authority() -> None:
    clients = read("backend/service1/routers/clients.py")
    shared = read("backend/service1/routers/shared_domain.py")
    control = read("backend/service1/system_control.py")

    assert "apply_system_command_completion" in shared
    assert 'if domain == "system":' in shared
    assert 'row.command_type != "change_hostname"' in control
    assert 'client.name = client_name' in control
    assert 'current_boot_id=presence.status.boot_id' in clients
    assert 'status_online=presence.status.is_online' in clients
    assert 'if action in {"reboot", "shutdown"} and not presence.status.boot_id:' in clients
    assert 'observed_new_boot' in control
    assert 'observed_offline = status == "succeeded" and not status_online' in control
    assert 'observed_boot_after_shutdown = bool(' in control
    assert 'shutdown_complete = observed_offline or observed_boot_after_shutdown' in control
    assert 'result["last_power_event"] = "shutdown_completed"' in control
    assert 'result["last_power_event"] = "boot_after_shutdown"' in control

    projection = clients[clients.index("def _apply_system_projection_for_read"):clients.index("def _prepare_clients_read")]
    assert '"chrome_step"' not in projection
    display_projection = clients[clients.index("def _apply_display_projection_for_read"):clients.index("def _apply_system_projection_for_read")]
    assert '_set_runtime_read_attr(client, "chrome_step", projection["chrome_step"])' in display_projection


def test_53b_serializes_system_commands_against_clientflow_deployments() -> None:
    clients = read("backend/service1/routers/clients.py")
    deployments = read("backend/service1/routers/clientflow_deployments.py")

    assert "lock_system_client(session, id)" in clients
    assert "lock_system_client(session, int(client.id))" in deployments
    assert "_require_deployable_client(session, client)" in deployments
    assert "active_system_command(session, int(client.id))" in deployments


def test_53b_frontend_uses_system_endpoints_and_system_projection_fields() -> None:
    api = read("frontend/src/api/api.js")
    page = read("frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx")
    actions = read("frontend/src/pages/clientdetailspage/ClientDetailsActionsSection.jsx")

    assert '`${apiUrl}/api/clients/${id}/system-command`' in api
    assert 'JSON.stringify({ action: systemAction, source })' in api
    assert "export async function resetOsUpdate" not in api
    assert "/os-update/reset" not in api
    assert 'data?.pending_shutdown === true' in page
    assert 'data?.pending_reboot === true' in page
    assert 'response-only projections, never pending_chrome_action' in page
    assert 'normalizedPendingAction === "os_update"' not in actions
    assert "SYSTEM_PENDING_ACTIONS" not in actions
    assert "serviceLooksBusy" not in actions
    info = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")
    ubuntu_step = info[info.index("function getUbuntuStep"):info.index("function getUbuntuStepPhase")]
    ubuntu_message = info[info.index("function getUbuntuHumanMessage"):info.index("function getUbuntuSearchText")]
    ubuntu_search = info[info.index("function getUbuntuSearchText"):info.index("function normalizeUbuntuPhase")]
    assert "chrome_step" not in ubuntu_step
    assert "chrome_status" not in ubuntu_message
    assert "chrome_step" not in ubuntu_search
    assert "chrome_status" not in ubuntu_search
    assert "serviceLooksReady" not in info



def test_53b_os_update_reports_reboot_requirement_without_auto_reboot_or_fake_progress() -> None:
    helper = read("client/libexec/update-os")
    control = read("backend/service1/system_control.py")

    assert 'CLIENTFLOW_REBOOT_REQUIRED=1' in helper
    assert 'CLIENTFLOW_REBOOT_REQUIRED=0' in helper
    assert '/var/run/reboot-required' in helper
    assert 'systemctl' not in helper
    assert '"claimed": ("installing", "os_update_installing", "Ubuntu-opdatering kører", None)' in control
    assert 'if "CLIENTFLOW_REBOOT_REQUIRED=1" in output:' in control
    assert '"ubuntu_update_reboot_required": reboot_required' in control

def test_53b_source_139_keeps_system_catalog_on_canonical_138_runtime() -> None:
    version = read("client/VERSION").strip()
    release_input = json.loads(read("client/release/release-input.json"))
    catalog = json.loads(read("backend/service1/clientflow_release_catalog.json"))

    assert version == "1.3.9"
    assert release_input["release_sequence"] == 1210
    assert catalog["catalog_sequence"] == 1209
    assert catalog["latest_stable"] == "1.3.8"
    assert catalog["default_install_version"] == "1.3.8"
    assert catalog["releases"][0]["release_id"] == "clientflow-1.3.8-seq-1209"
