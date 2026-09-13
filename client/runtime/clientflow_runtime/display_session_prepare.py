#!/usr/bin/env python3
"""Prepare the graphical kiosk-session baseline before first-activation reboot.

This pre-activation helper deliberately does not install Chrome, start ClientFlow
runtime services, switch the active release, or weaken activation health. It only
materializes the minimum idempotent GDM/AccountsService login baseline that
must exist before GDM starts the canonical kiosk Wayland session.
"""
from __future__ import annotations

import os

from .display_platform_prepare import (
    DisplayPlatformPreparationError,
    prepare_graphical_login_baseline,
)


def prepare() -> None:
    if os.geteuid() != 0:
        raise DisplayPlatformPreparationError(
            "Display session preparation kræver root"
        )
    kiosk_user = os.getenv("CLIENTFLOW_KIOSK_USER", "").strip()
    if not kiosk_user:
        raise DisplayPlatformPreparationError("CLIENTFLOW_KIOSK_USER mangler")
    prepare_graphical_login_baseline(kiosk_user)


def main() -> int:
    try:
        prepare()
    except DisplayPlatformPreparationError as exc:
        print(f"DISPLAY_SESSION_PREPARE_FAILED: {exc}", flush=True)
        return 1
    print("DISPLAY_SESSION_PREPARE_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
