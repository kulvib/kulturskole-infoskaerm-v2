"""Display command agent. It has no System or other-domain control path."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .command_agent import CommandContext, CommandRejected, QueueAgent
from .config import DomainCredential
from .constants import Domain
from .display_local_control import (
    POWER_STATE_PATH,
    display_control_lock,
    record_calendar_manual_override,
    runtime_action,
    set_display_power,
)
from .net import DomainTransport
from .unix_rpc import RpcError

STATUS_PATH = Path(os.getenv("CLIENTFLOW_DISPLAY_STATUS_FILE", "/var/lib/clientflow/display-runtime/runtime-status.json"))
CALENDAR_STATUS_PATH = Path(os.getenv("CLIENTFLOW_CALENDAR_STATUS_FILE", "/var/lib/clientflow/calendar/status.json"))


def _handle(context: CommandContext) -> dict[str, Any]:
    try:
        with display_control_lock():
            if context.command_type == "set_display_power":
                state = str(context.payload.get("state") or "")
                if state not in {"on", "off"}:
                    raise CommandRejected("invalid_display_power", "state skal være on eller off")
                result = set_display_power(state)
                record_calendar_manual_override(context.command_type)
                return result
            if context.command_type in {"apply_configuration", "start_browser", "stop_browser", "reset_browser"}:
                result = runtime_action(
                    context.command_type,
                    payload=context.payload if context.command_type == "apply_configuration" else None,
                )
                if context.command_type != "apply_configuration":
                    record_calendar_manual_override(context.command_type)
                return result
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
    return {
        "runtime": _read_object(STATUS_PATH),
        "display_power": _read_object(POWER_STATE_PATH),
        "calendar": _read_object(CALENDAR_STATUS_PATH),
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
