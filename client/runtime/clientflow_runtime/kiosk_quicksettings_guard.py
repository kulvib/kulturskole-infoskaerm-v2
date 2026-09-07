"""Legacy-compatible optional kiosk quick-settings guard.

The guard is a local, fixed-function runtime component. It only enforces the
quick-settings behaviour while optional kiosk lockdown is locally marked as
desired. When lockdown is disabled it exits without mutating the session.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from . import kiosk_session_policy

STATE_PATH = Path(os.getenv("CLIENTFLOW_KIOSK_LOCKDOWN_STATE", "/var/lib/clientflow/kiosk-lockdown/state.json"))
INTERVAL_SECONDS = max(1.0, float(os.getenv("CLIENTFLOW_LOCKDOWN_QUICKSETTINGS_INTERVAL", "2")))


def _desired() -> bool:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and value.get("desired") is True


def run() -> None:
    while _desired():
        kiosk_session_policy.enforce(lockdown_quicksettings=True)
        time.sleep(INTERVAL_SECONDS)


def main() -> int:
    if os.geteuid() != 0:
        print("CLIENTFLOW_KIOSK_QUICKSETTINGS_GUARD_FAILED: kræver root", flush=True)
        return 1
    try:
        run()
    except (OSError, ValueError, kiosk_session_policy.KioskSessionPolicyError) as exc:
        print(f"CLIENTFLOW_KIOSK_QUICKSETTINGS_GUARD_FAILED: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
