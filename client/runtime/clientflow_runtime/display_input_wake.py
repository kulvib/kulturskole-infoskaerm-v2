"""Physical keyboard/mouse wake worker for the Display domain.

This worker deliberately owns only the narrow action "display power on". It
never starts Chrome, never reboots the host and never bypasses the canonical
Display power broker.
"""
from __future__ import annotations

import json
import logging
import select
import time

from evdev import InputDevice, ecodes, list_devices

from .display_local_control import (
    POWER_STATE_PATH,
    display_control_lock,
    record_calendar_manual_override,
    set_display_power,
)

MANUAL_WAKE_GRACE_SECONDS = 20.0
DEVICE_RESCAN_SECONDS = 5.0
LOGGER = logging.getLogger("clientflow.display_input_wake")


def _power_state() -> tuple[str | None, float | None]:
    try:
        payload = json.loads(POWER_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    state = str(payload.get("state") or "").strip().lower()
    try:
        updated_at = float(payload.get("updated_at"))
    except (TypeError, ValueError):
        updated_at = None
    return (state if state in {"on", "off"} else None), updated_at


def _manual_wake_allowed(*, now: float | None = None) -> bool:
    state, updated_at = _power_state()
    if state != "off" or updated_at is None:
        return False
    current = time.time() if now is None else float(now)
    return current - updated_at >= MANUAL_WAKE_GRACE_SECONDS


def _is_user_input(event) -> bool:
    if event.type == ecodes.EV_KEY:
        return int(event.value) == 1
    if event.type in {ecodes.EV_REL, ecodes.EV_ABS}:
        return int(event.value) != 0
    return False


def _open_input_devices() -> list[InputDevice]:
    devices: list[InputDevice] = []
    for path in list_devices():
        try:
            device = InputDevice(path)
            capabilities = device.capabilities(verbose=False)
            if any(kind in capabilities for kind in (ecodes.EV_KEY, ecodes.EV_REL, ecodes.EV_ABS)):
                devices.append(device)
            else:
                device.close()
        except (OSError, PermissionError):
            continue
    return devices


def _close_devices(devices: list[InputDevice]) -> None:
    for device in devices:
        try:
            device.close()
        except OSError:
            pass


def _wake_from_physical_input() -> bool:
    with display_control_lock():
        if not _manual_wake_allowed():
            return False
        set_display_power("on")
        record_calendar_manual_override("manual_input_wake")
        return True


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    devices: list[InputDevice] = []
    next_rescan = 0.0
    try:
        while True:
            monotonic_now = time.monotonic()
            if monotonic_now >= next_rescan or not devices:
                _close_devices(devices)
                devices = _open_input_devices()
                next_rescan = monotonic_now + DEVICE_RESCAN_SECONDS
            if not devices:
                time.sleep(1.0)
                continue
            try:
                readable, _, _ = select.select(devices, [], [], 1.0)
            except (OSError, ValueError):
                _close_devices(devices)
                devices = []
                continue
            for device in readable:
                try:
                    events = list(device.read())
                except OSError:
                    _close_devices(devices)
                    devices = []
                    break
                if not _manual_wake_allowed():
                    continue
                if any(_is_user_input(event) for event in events):
                    if _wake_from_physical_input():
                        LOGGER.info("display_woke_from_physical_input device=%s", device.path)
                        # Ignore the remainder of this input burst. The persisted
                        # state is now on, so further events cannot retrigger.
                        break
    finally:
        _close_devices(devices)


def main() -> int:
    run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
