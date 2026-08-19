"""Read-only diagnostics saved only on the invoking user's desktop."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
from typing import Any

from .version import VERSION

UNITS = (
    "clientflow-status-agent.service",
    "clientflow-display-agent.service",
    "clientflow-display-runtime.service",
    "clientflow-display-power-broker.socket",
    "clientflow-livestream-agent.service",
    "clientflow-livestream-broker.service",
    "clientflow-livestream-producer.service",
    "clientflow-livestream-uploader.service",
    "clientflow-remote-desktop-agent.service",
    "clientflow-remote-desktop-capture.socket",
    "clientflow-remote-desktop-input-broker.socket",
    "clientflow-terminal-agent.service",
    "clientflow-standard-terminal-broker.socket",
    "clientflow-root-terminal-broker.socket",
    "clientflow-system-agent.service",
    "clientflow-system-broker.socket",
)


def _desktop() -> Path:
    home = Path.home()
    danish = home / "Skrivebord"
    fallback = home / "Desktop"
    if danish.is_dir():
        return danish
    if fallback.is_dir():
        return fallback
    fallback.mkdir(mode=0o700, parents=True, exist_ok=True)
    return fallback


def _systemctl(unit: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "/usr/bin/systemctl",
            "show",
            unit,
            "--property=LoadState,ActiveState,SubState,UnitFileState,MainPID,User,Group",
            "--no-pager",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    values: dict[str, Any] = {"returncode": completed.returncode}
    for line in completed.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    if completed.stderr:
        values["error"] = completed.stderr[:1000]
    return values


def main() -> int:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    output = _desktop() / f"clientflow-{VERSION}-diagnostics-{timestamp}.json"
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "uid": os.getuid(),
        "units": {unit: _systemctl(unit) for unit in UNITS},
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    print(output)
    return 0
