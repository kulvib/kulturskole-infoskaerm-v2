"""Display command agent. It has no System or other-domain control path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from .atomic import atomic_write_json
from .command_agent import CommandContext, CommandRejected, QueueAgent
from .config import DomainCredential
from .constants import Domain
from .net import DomainTransport
from .unix_rpc import RpcError, call

RUNTIME_SOCKET = os.getenv("CLIENTFLOW_DISPLAY_RUNTIME_SOCKET", "/run/clientflow/display/runtime.sock")
POWER_SOCKET = os.getenv("CLIENTFLOW_DISPLAY_POWER_SOCKET", "/run/clientflow/display-power.sock")
STATUS_PATH = Path(os.getenv("CLIENTFLOW_DISPLAY_STATUS_FILE", "/var/lib/clientflow/display-runtime/runtime-status.json"))
AGENT_STATE_DIR = Path(os.getenv("CLIENTFLOW_DISPLAY_AGENT_STATE_DIR", "/var/lib/clientflow/display-agent"))
POWER_STATE_PATH = AGENT_STATE_DIR / "power-state.json"


def _record_power_state(state: str) -> None:
    AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        POWER_STATE_PATH,
        {"schema_version": 1, "state": state, "updated_at": time.time()},
        mode=0o600,
    )


def _handle(context: CommandContext) -> dict[str, Any]:
    try:
        if context.command_type == "set_display_power":
            state = str(context.payload.get("state") or "")
            if state not in {"on", "off"}:
                raise CommandRejected("invalid_display_power", "state skal være on eller off")
            result = call(POWER_SOCKET, {"action": "set_display_power", "state": state})
            _record_power_state(state)
            return result
        if context.command_type in {"apply_configuration", "start_browser", "stop_browser", "reset_browser"}:
            request: dict[str, Any] = {"action": context.command_type}
            if context.command_type == "apply_configuration":
                request["payload"] = context.payload
            return call(RUNTIME_SOCKET, request)
    except RpcError as exc:
        raise CommandRejected("display_broker_error", str(exc), retryable=True) from exc
    raise CommandRejected("unsupported_display_command", "Displaykommandoen er ikke implementeret")


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _status() -> dict[str, Any]:
    power = _read_object(POWER_STATE_PATH)
    return {
        "runtime": _read_object(STATUS_PATH),
        "display_power": power,
    }


def main() -> int:
    credential = DomainCredential.load(Domain.DISPLAY)
    QueueAgent(
        DomainTransport(credential),
        _handle,
        status_payload=_status,
        report_status_after_command=True,
    ).run_forever()
    return 0
