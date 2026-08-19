"""Display command agent. It has no system or other-domain control path."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .command_agent import CommandContext, CommandRejected, QueueAgent
from .config import DomainCredential
from .constants import Domain
from .net import DomainTransport
from .unix_rpc import RpcError, call

RUNTIME_SOCKET = os.getenv("CLIENTFLOW_DISPLAY_RUNTIME_SOCKET", "/run/clientflow/display/runtime.sock")
POWER_SOCKET = os.getenv("CLIENTFLOW_DISPLAY_POWER_SOCKET", "/run/clientflow/display-power.sock")
STATUS_PATH = Path(os.getenv("CLIENTFLOW_DISPLAY_STATUS_FILE", "/var/lib/clientflow/display/runtime-status.json"))


def _handle(context: CommandContext) -> dict[str, Any]:
    try:
        if context.command_type == "set_display_power":
            state = str(context.payload.get("state") or "")
            if state not in {"on", "off"}:
                raise CommandRejected("invalid_display_power", "state skal være on eller off")
            return call(POWER_SOCKET, {"action": "set_display_power", "state": state})
        if context.command_type in {"apply_configuration", "reload_browser", "restart_browser"}:
            request: dict[str, Any] = {"action": context.command_type}
            if context.command_type == "apply_configuration":
                request["payload"] = context.payload
            return call(RUNTIME_SOCKET, request)
    except RpcError as exc:
        raise CommandRejected("display_broker_error", str(exc), retryable=True) from exc
    raise CommandRejected("unsupported_display_command", "Displaykommandoen er ikke implementeret")


def _status() -> dict[str, Any]:
    try:
        import json

        value = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return {"runtime": value if isinstance(value, dict) else None}
    except (OSError, json.JSONDecodeError):
        return {"runtime": None}


def main() -> int:
    credential = DomainCredential.load(Domain.DISPLAY)
    QueueAgent(DomainTransport(credential), _handle, status_payload=_status).run_forever()
    return 0
