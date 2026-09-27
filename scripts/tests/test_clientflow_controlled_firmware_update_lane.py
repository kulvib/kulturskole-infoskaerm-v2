from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_firmware_awareness_is_system_domain_read_only_telemetry() -> None:
    agent = read("client/runtime/clientflow_runtime/system_agent.py")
    clients = read("backend/service1/routers/clients.py")
    models = read("backend/service1/models.py")
    assert 'FWUPDMGR = Path("/usr/bin/fwupdmgr")' in agent
    assert 'FIRMWARE_STATUS_TTL_SECONDS' in agent
    assert '"firmware": firmware_cache.snapshot()' in agent
    assert 'system_payload.get("firmware")' in clients
    assert 'firmware: Optional[Dict[str, Any]] = None' in models


def test_firmware_execution_is_superadmin_only_and_uses_canonical_system_queue() -> None:
    clients = read("backend/service1/routers/clients.py")
    control = read("backend/service1/system_control.py")
    api = read("frontend/src/api/api.js")
    section = read("frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx")
    assert '@router.post("/clients/{id}/firmware-update")' in clients
    route = clients.split('@router.post("/clients/{id}/firmware-update")', 1)[1].split('@router.post("/clients/{id}/os-update/reset")', 1)[0]
    assert 'user=Depends(get_current_superadmin_user)' in route
    assert 'command_type="update_firmware"' in route
    assert 'action="firmware_update_approved"' in route
    assert 'severity="critical"' in route
    assert 'requires_shutdown' in route
    assert 'SYSTEM_COMMAND_TYPES = frozenset({"reboot", "shutdown", "update_os", "update_firmware"' in control
    assert '/firmware-update`' in api
    assert 'const isSuperadmin = user?.role === "superadmin";' in section
    assert 'Kun superadministrator kan godkende firmwareopdateringer.' in section


def test_firmware_helper_keeps_fwupd_safety_checks_and_clientflow_owns_reboot() -> None:
    helper = read("client/libexec/update-firmware")
    broker = read("client/runtime/clientflow_runtime/system_broker.py")
    builder = read("client/release/lib/clientflow_release/builder.py")
    assert '"$FWUPDMGR" update --assume-yes --no-reboot-check --json' in helper
    assert '--no-safety-check' not in helper
    assert '/tmp/clientflow-fwupd' not in helper
    assert 'WORKDIR=/run/clientflow-firmware-update' in helper
    assert '--force' not in helper.split('"$FWUPDMGR" update', 1)[1]
    assert 'CLIENTFLOW_REBOOT_REQUIRED=' in helper
    assert 'CLIENTFLOW_SHUTDOWN_REQUIRED=' in helper
    assert 'planlagt lokal vedligeholdelse kræves' in helper
    assert 'UPDATE_ACTIONS = frozenset({"update_os", "update_firmware"})' in broker
    assert 'source=action' in broker
    assert '"client-runtime/libexec/update-firmware"' in builder


def test_firmware_status_is_bounded_and_does_not_refresh_lvfs_on_every_heartbeat() -> None:
    agent = read("client/runtime/clientflow_runtime/system_agent.py")
    assert 'for raw in candidates[:32]:' in agent
    assert '_run_fwupd_json("get-updates", timeout=20)' in agent
    assert '_run_fwupd_json("refresh"' not in agent


def test_shutdown_required_firmware_is_fail_closed_for_headless_kiosk() -> None:
    helper = read("client/libexec/update-firmware")
    clients = read("backend/service1/routers/clients.py")
    assert 'if [[ "$NEEDS_SHUTDOWN" == "1" ]]' in helper
    assert 'exit 78' in helper
    assert 'if firmware.get("requires_shutdown") is True:' in clients
