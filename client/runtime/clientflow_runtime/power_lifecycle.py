"""Bounded local host power-transition attribution.

The canonical System command domain owns remote reboot/shutdown requests.  This
module exists only to preserve evidence for *local* host transitions (GNOME,
cfadmin, physical-console tools) that bypass that queue.

A root-owned, short-lived System intent suppresses local attribution for a
canonical backend command.  Local reporter services write a durable marker
before reboot/poweroff; the read-only Status domain projects that marker after a
different boot id is observed.  No ClientFlow credential is read here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import time
import uuid
from typing import Any

from .atomic import atomic_write_json
from .config import ConfigurationError, load_secure_json

STATE_DIR = Path(os.getenv("CLIENTFLOW_POWER_EVENT_DIR", "/var/lib/clientflow/power-events"))
LOCAL_MARKER_PATH = STATE_DIR / "local-transition.json"
SYSTEM_INTENT_PATH = STATE_DIR / "system-command-intent.json"
BOOT_ID_PATH = Path(os.getenv("CLIENTFLOW_BOOT_ID_PATH", "/proc/sys/kernel/random/boot_id"))
SYSTEM_INTENT_MAX_AGE_SECONDS = 300
_VALID_ACTIONS = frozenset({"reboot", "shutdown"})


class PowerLifecycleError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _current_boot_id() -> str:
    try:
        return str(uuid.UUID(BOOT_ID_PATH.read_text(encoding="ascii").strip()))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PowerLifecycleError("power_boot_id_unavailable") from exc


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    metadata = STATE_DIR.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PowerLifecycleError("power_state_directory_invalid")
    os.chmod(STATE_DIR, 0o755)


def _load(path: Path, *, private: bool) -> dict[str, Any] | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PowerLifecycleError("power_marker_invalid")
    forbidden = 0o077 if private else 0o022
    try:
        value = load_secure_json(path, max_bytes=64 * 1024, forbidden_mode_bits=forbidden)
    except ConfigurationError as exc:
        raise PowerLifecycleError("power_marker_invalid") from exc
    if not isinstance(value, dict):
        raise PowerLifecycleError("power_marker_invalid")
    return value


def record_system_intent(
    *,
    action: str,
    command_id: str,
    source: str,
    requested_boot_id: str | None,
) -> None:
    """Record a canonical System command immediately before systemctl.

    The shutdown reporter consumes only a fresh, same-boot, same-action intent.
    A stale/crashed command therefore cannot mask a later local transition.
    """
    action = str(action or "").strip().lower()
    if action not in _VALID_ACTIONS:
        raise PowerLifecycleError("power_action_invalid")
    try:
        uuid.UUID(str(command_id))
    except ValueError as exc:
        raise PowerLifecycleError("power_command_id_invalid") from exc
    current_boot = _current_boot_id()
    if requested_boot_id:
        try:
            requested = str(uuid.UUID(str(requested_boot_id)))
        except ValueError as exc:
            raise PowerLifecycleError("power_requested_boot_id_invalid") from exc
        if requested != current_boot:
            raise PowerLifecycleError("power_requested_boot_id_mismatch")
    _ensure_state_dir()
    atomic_write_json(
        SYSTEM_INTENT_PATH,
        {
            "schema_version": 1,
            "action": action,
            "command_id": str(command_id),
            "source": str(source or "system_command")[:80],
            "boot_id": current_boot,
            "created_at_epoch": time.time(),
        },
        mode=0o600,
    )


def clear_system_intent() -> None:
    try:
        SYSTEM_INTENT_PATH.unlink()
    except FileNotFoundError:
        return


def _consume_matching_system_intent(action: str, current_boot: str) -> bool:
    intent = _load(SYSTEM_INTENT_PATH, private=True)
    if intent is None:
        return False
    matched = False
    try:
        age = max(0.0, time.time() - float(intent.get("created_at_epoch")))
        matched = (
            int(intent.get("schema_version", 0)) == 1
            and str(intent.get("action") or "") == action
            and str(intent.get("boot_id") or "") == current_boot
            and age <= SYSTEM_INTENT_MAX_AGE_SECONDS
        )
    except (TypeError, ValueError):
        matched = False
    # Consume any intent on an actual power boundary. A malformed/stale intent
    # must not survive and mask a later local transition.
    clear_system_intent()
    return matched


def mark_local_transition(action: str) -> dict[str, Any]:
    """Persist a local transition unless a fresh canonical System intent exists."""
    action = str(action or "").strip().lower()
    if action not in _VALID_ACTIONS:
        raise PowerLifecycleError("power_action_invalid")
    current_boot = _current_boot_id()
    _ensure_state_dir()
    if _consume_matching_system_intent(action, current_boot):
        return {"status": "canonical_system_command", "action": action}

    marker = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "action": action,
        "source": "local",
        "started_at": _utc_now(),
        "previous_boot_id": current_boot,
    }
    # Non-secret evidence. Root owns the file; 0644 lets the unprivileged
    # read-only Status agent report it after the next boot.
    atomic_write_json(LOCAL_MARKER_PATH, marker, mode=0o644)
    return dict(marker)


def collect_completed_local_power_event() -> dict[str, Any] | None:
    marker = _load(LOCAL_MARKER_PATH, private=False)
    if marker is None:
        return None
    if int(marker.get("schema_version", 0)) != 1:
        raise PowerLifecycleError("power_marker_schema_invalid")
    action = str(marker.get("action") or "")
    if action not in _VALID_ACTIONS or marker.get("source") != "local":
        raise PowerLifecycleError("power_marker_binding_invalid")
    try:
        event_id = str(uuid.UUID(str(marker.get("event_id") or "")))
        previous_boot = str(uuid.UUID(str(marker.get("previous_boot_id") or "")))
    except ValueError as exc:
        raise PowerLifecycleError("power_marker_binding_invalid") from exc
    current_boot = _current_boot_id()
    if current_boot == previous_boot:
        return None
    started_at = str(marker.get("started_at") or "").strip()
    if not started_at:
        raise PowerLifecycleError("power_marker_started_at_missing")
    return {
        "schema_version": 1,
        "event_id": event_id,
        "event": "reboot_completed" if action == "reboot" else "boot_after_shutdown",
        "action": action,
        "source": "local",
        "started_at": started_at,
        "previous_boot_id": previous_boot,
        "observed_boot_id": current_boot,
    }


def main(argv: list[str] | None = None) -> int:
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in _VALID_ACTIONS:
        print("usage: clientflow-power-event-marker <reboot|shutdown>", file=sys.stderr)
        return 2
    try:
        mark_local_transition(args[0])
    except Exception as exc:
        print(f"clientflow-power-event-marker: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
