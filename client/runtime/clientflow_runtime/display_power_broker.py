"""Root-owned, fixed-function display power broker."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from .config import ClientIdentity
from .server import serve_forever
from .socket_activation import activated_socket

HELPER = Path(os.getenv("CLIENTFLOW_DISPLAY_POWER_HELPER", "/opt/clientflow/active/client-runtime/libexec/display-power"))


def handle(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("action") != "set_display_power":
        raise ValueError("Displaybroker accepterer kun set_display_power")
    state = str(request.get("state") or "")
    if state not in {"on", "off"}:
        raise ValueError("Display power state skal være on eller off")
    identity = ClientIdentity.load()
    if not HELPER.is_file() or HELPER.is_symlink():
        raise RuntimeError("Display power helper mangler eller er ugyldig")
    completed = subprocess.run(
        [str(HELPER), identity.kiosk_user, state],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stdout or "Display power helper fejlede")[:1000])
    return {"state": state, "output": (completed.stdout or "")[:1000]}


def main() -> int:
    serve_forever(activated_socket(), handle, name="clientflow.display.power-broker")
    return 0
