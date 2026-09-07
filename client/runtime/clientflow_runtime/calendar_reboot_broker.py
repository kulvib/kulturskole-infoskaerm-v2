"""Root-owned fixed-function reboot broker for Calendar wake only."""
from __future__ import annotations

import subprocess
from typing import Any

from .server import serve_forever
from .socket_activation import activated_socket


def handle(request: dict[str, Any]) -> dict[str, Any]:
    if int(request.get("schema_version") or 0) != 1 or request.get("action") != "reboot":
        raise ValueError("Calendar reboot broker accepterer kun schema_version=1/action=reboot")
    completed = subprocess.run(
        ["/usr/bin/systemctl", "--no-block", "--ignore-inhibitors", "reboot"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=10, check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stdout or "Calendar reboot fejlede")[:1000])
    return {"reboot_requested": True}


def main() -> int:
    serve_forever(activated_socket(), handle, name="clientflow.calendar.reboot-broker")
    return 0
