"""Fail-closed readiness gate for the local GNOME/Wayland kiosk GUI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import subprocess
import time

STATE_DIR = Path(os.getenv("CLIENTFLOW_DISPLAY_STATE_DIR", "/var/lib/clientflow/display-runtime"))
CONFIG_PATH = STATE_DIR / "configuration.json"
STATUS_PATH = STATE_DIR / "runtime-status.json"
LOCAL_GUI_STATUS_PATH = STATE_DIR / "local-gui-status.json"
TIMEOUT_SECONDS = int(os.getenv("CLIENTFLOW_DISPLAY_READINESS_TIMEOUT_SECONDS", "90"))


class DisplayReadinessError(RuntimeError):
    pass


def _loginctl(kind: str, ident: str, prop: str) -> str:
    result = subprocess.run(
        ["/usr/bin/loginctl", f"show-{kind}", ident, "-p", prop, "--value"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        raise DisplayReadinessError(f"loginctl kunne ikke læse {kind} {ident} {prop}")
    return result.stdout.strip()


def _active_kiosk_session() -> bool:
    account = pwd.getpwuid(os.getuid())
    session = _loginctl("seat", "seat0", "ActiveSession")
    if not session:
        return False
    values = {name: _loginctl("session", session, name) for name in ("Name", "Seat", "Remote", "Type", "Active", "State", "LockedHint")}
    return (
        values["Name"] == account.pw_name
        and values["Seat"] == "seat0"
        and values["Remote"] == "no"
        and values["Type"] == "wayland"
        and values["Active"] == "yes"
        and values["State"] in {"active", "online"}
        and values["LockedHint"] != "yes"
    )


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}




def _local_gui_ready() -> bool:
    status = _read_json(LOCAL_GUI_STATUS_PATH)
    if status.get("state") != "running":
        return False
    try:
        pid = int(status.get("pid") or 0)
        updated_at = float(status.get("updated_at") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 1 or updated_at <= 0 or (time.time() - updated_at) > 5:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    return True


def ready() -> bool:
    if not _active_kiosk_session() or not _local_gui_ready():
        return False
    configuration = _read_json(CONFIG_PATH)
    kiosk_url = str(configuration.get("kiosk_url") or "").strip()
    if not kiosk_url:
        # The GUI session itself is ready. Display configuration may arrive only
        # after the approved client reconnects and the Display domain reconciles.
        return True
    status = _read_json(STATUS_PATH)
    try:
        pid = int(status.get("browser_pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return status.get("state") == "running" and bool(status.get("browser_requested")) and pid > 1


def wait_until_ready(timeout: int = TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + max(1, timeout)
    last_error = "ClientFlow GUI/session endnu ikke klar"
    while time.monotonic() < deadline:
        try:
            if ready():
                return
            last_error = "ClientFlow GUI, kiosk Wayland-session eller browser er endnu ikke klar"
        except (OSError, KeyError, DisplayReadinessError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise DisplayReadinessError(last_error)


def main() -> int:
    try:
        wait_until_ready()
    except DisplayReadinessError as exc:
        print(f"DISPLAY_READINESS_FAILED: {exc}", flush=True)
        return 1
    print("DISPLAY_READINESS_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
