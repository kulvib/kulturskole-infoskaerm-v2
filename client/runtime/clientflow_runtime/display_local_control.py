"""Serialized local control operations shared by Display command and Calendar agents."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Iterator

from .atomic import atomic_write_json
from .unix_rpc import call

RUNTIME_SOCKET = os.getenv("CLIENTFLOW_DISPLAY_RUNTIME_SOCKET", "/run/clientflow/display/runtime.sock")
POWER_SOCKET = os.getenv("CLIENTFLOW_DISPLAY_POWER_SOCKET", "/run/clientflow/display-power.sock")
AGENT_STATE_DIR = Path(os.getenv("CLIENTFLOW_DISPLAY_AGENT_STATE_DIR", "/var/lib/clientflow/display-agent"))
POWER_STATE_PATH = AGENT_STATE_DIR / "power-state.json"
CONTROL_LOCK_PATH = AGENT_STATE_DIR / "control.lock"
CALENDAR_OVERRIDE_PATH = AGENT_STATE_DIR / "calendar-override.json"
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


@contextmanager
def display_control_lock() -> Iterator[None]:
    AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(CONTROL_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(descriptor, "r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        # fdopen owns the descriptor after success; only close when it failed
        # before ownership was transferred.
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise



def _boot_id() -> str | None:
    try:
        value = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return value or None


def record_calendar_manual_override(action: str) -> None:
    AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        CALENDAR_OVERRIDE_PATH,
        {
            "schema_version": 1,
            "boot_id": _boot_id(),
            "action": str(action or "")[:80],
            "created_at": time.time(),
        },
        mode=0o600,
    )


def calendar_manual_override_created_at() -> float | None:
    try:
        value = json.loads(CALENDAR_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or int(value.get("schema_version") or 0) != 1:
        return None
    current_boot = _boot_id()
    recorded_boot = str(value.get("boot_id") or "").strip()
    if current_boot is None or not recorded_boot or recorded_boot != current_boot:
        CALENDAR_OVERRIDE_PATH.unlink(missing_ok=True)
        return None
    try:
        created_at = float(value.get("created_at"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(created_at) or created_at <= 0:
        return None
    return created_at


def calendar_manual_override_active() -> bool:
    return calendar_manual_override_created_at() is not None


def clear_calendar_manual_override() -> None:
    CALENDAR_OVERRIDE_PATH.unlink(missing_ok=True)

def record_power_state(state: str) -> None:
    if state not in {"on", "off"}:
        raise ValueError("Display power state skal være on eller off")
    AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        POWER_STATE_PATH,
        {"schema_version": 1, "state": state, "updated_at": time.time()},
        mode=0o600,
    )


def set_display_power(state: str) -> dict[str, Any]:
    if state not in {"on", "off"}:
        raise ValueError("Display power state skal være on eller off")
    if state == "off":
        # Legacy parity: display sleep has a visible 5..1 pre-power countdown.
        # V2 deliberately keeps browser and display-power as separate authorities.
        call(RUNTIME_SOCKET, {"action": "display_sleep_countdown"})
    result = call(POWER_SOCKET, {"action": "set_display_power", "state": state})
    record_power_state(state)
    return result


def runtime_action(action: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if action not in {"apply_configuration", "start_browser", "stop_browser", "reset_browser"}:
        raise ValueError(f"Understøttet Display runtime action mangler for: {action}")
    request: dict[str, Any] = {"action": action}
    if action == "apply_configuration":
        if not isinstance(payload, dict):
            raise ValueError("apply_configuration kræver payload")
        request["payload"] = payload
    return call(RUNTIME_SOCKET, request)
