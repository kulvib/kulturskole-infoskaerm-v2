"""System command agent. It can call only the fixed-function local system broker."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from .command_agent import CommandContext, CommandRejected, QueueAgent
from .config import DomainCredential
from .constants import Domain
from .net import DomainTransport
from .unix_rpc import RpcError, call

SYSTEM_SOCKET = os.getenv("CLIENTFLOW_SYSTEM_SOCKET", "/run/clientflow/system.sock")
FWUPDMGR = Path("/usr/bin/fwupdmgr")
FIRMWARE_STATUS_TTL_SECONDS = max(300, int(os.getenv("CLIENTFLOW_FIRMWARE_STATUS_TTL_SECONDS", "21600")))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_fwupd_json(*args: str, timeout: int = 45) -> tuple[int, dict[str, Any] | None, str | None]:
    if not FWUPDMGR.is_file() or not os.access(FWUPDMGR, os.X_OK):
        return 127, None, "fwupdmgr_missing"
    completed = subprocess.run(
        [str(FWUPDMGR), *args, "--json"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    raw = completed.stdout.decode("utf-8", errors="replace").strip()
    error = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
    if completed.returncode not in {0, 2, 101}:
        return completed.returncode, None, error or f"fwupdmgr_exit_{completed.returncode}"
    if not raw:
        return completed.returncode, {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return completed.returncode, None, "fwupdmgr_invalid_json"
    if not isinstance(value, dict):
        return completed.returncode, None, "fwupdmgr_invalid_json"
    return completed.returncode, value, None


def _firmware_snapshot() -> dict[str, Any]:
    checked_at = _iso_now()
    if not FWUPDMGR.is_file() or not os.access(FWUPDMGR, os.X_OK):
        return {
            "supported": False,
            "provider": "fwupd",
            "update_available": False,
            "update_count": 0,
            "requires_reboot": False,
            "requires_shutdown": False,
            "checked_at": checked_at,
            "devices": [],
            "error": "fwupdmgr_missing",
        }

    devices_rc, devices_doc, devices_error = _run_fwupd_json("get-devices", timeout=15)
    updates_rc, updates_doc, updates_error = _run_fwupd_json("get-updates", timeout=20)
    if devices_doc is None:
        return {
            "supported": False,
            "provider": "fwupd",
            "update_available": False,
            "update_count": 0,
            "requires_reboot": False,
            "requires_shutdown": False,
            "checked_at": checked_at,
            "devices": [],
            "error": devices_error or f"fwupdmgr_get_devices_exit_{devices_rc}",
        }

    candidates = [] if updates_doc is None else updates_doc.get("Devices", [])
    if not isinstance(candidates, list):
        candidates = []
    sanitized: list[dict[str, Any]] = []
    requires_reboot = False
    requires_shutdown = False
    for raw in candidates[:32]:
        if not isinstance(raw, dict):
            continue
        flags_raw = raw.get("Flags")
        flags = [str(item)[:80] for item in flags_raw] if isinstance(flags_raw, list) else []
        requires_reboot = requires_reboot or "needs-reboot" in flags
        requires_shutdown = requires_shutdown or "needs-shutdown" in flags
        sanitized.append({
            "device_id": str(raw.get("DeviceId") or "")[:128] or None,
            "name": str(raw.get("Name") or "Ukendt firmwareenhed")[:160],
            "vendor": str(raw.get("Vendor") or "")[:120] or None,
            "version": str(raw.get("Version") or "")[:120] or None,
            "flags": flags,
        })

    error = updates_error
    return {
        "supported": True,
        "provider": "fwupd",
        "update_available": bool(sanitized),
        "update_count": len(sanitized),
        "requires_reboot": requires_reboot,
        "requires_shutdown": requires_shutdown,
        "checked_at": checked_at,
        "devices": sanitized,
        "error": error,
        "get_updates_exit_code": updates_rc,
    }


class FirmwareStatusCache:
    def __init__(self) -> None:
        self._value: dict[str, Any] | None = None
        self._loaded_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        ttl = 300 if self._value is not None and self._value.get("error") else FIRMWARE_STATUS_TTL_SECONDS
        if self._value is None or now - self._loaded_at >= ttl:
            try:
                self._value = _firmware_snapshot()
            except Exception as exc:
                self._value = {
                    "supported": False,
                    "provider": "fwupd",
                    "update_available": False,
                    "update_count": 0,
                    "requires_reboot": False,
                    "requires_shutdown": False,
                    "checked_at": _iso_now(),
                    "devices": [],
                    "error": f"firmware_status_error:{type(exc).__name__}",
                }
            self._loaded_at = now
        return dict(self._value)


def build_handler(transport: DomainTransport):
    def handle(context: CommandContext) -> dict[str, Any]:
        payload = dict(context.payload)
        try:
            return call(
                SYSTEM_SOCKET,
                {
                    "action": context.command_type,
                    "client_id": context.client_id,
                    "command_id": context.command_id,
                    "schema_version": context.schema_version,
                    "payload": payload,
                },
                timeout=7250 if context.command_type in {"update_os", "update_firmware"} else 1850,
            )
        except RpcError as exc:
            message = str(exc)
            in_doubt = "system_command_in_doubt" in message or "system_command_journal" in message
            retryable = not in_doubt and context.command_type in {"update_os", "update_firmware"}
            code = "system_command_in_doubt" if in_doubt else "system_broker_error"
            raise CommandRejected(code, message, retryable=retryable) from exc
    return handle


def main() -> int:
    credential = DomainCredential.load(Domain.SYSTEM)
    transport = DomainTransport(credential)
    firmware_cache = FirmwareStatusCache()
    QueueAgent(
        transport,
        build_handler(transport),
        lease_seconds=300,
        status_payload=lambda: {
            "broker_socket": os.path.exists(SYSTEM_SOCKET),
            "firmware": firmware_cache.snapshot(),
        },
        piggyback_status_on_claim=True,
    ).run_forever()
    return 0
