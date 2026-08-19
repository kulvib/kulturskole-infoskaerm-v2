"""Read-only host telemetry agent. It cannot claim commands or control services."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import socket
import time
from typing import Any

from .config import DomainCredential
from .constants import Domain
from .logging_utils import configure_logging
from .net import DomainTransport, backoff_seconds
from .status import report_status


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            number = raw.strip().split()[0]
            values[key] = int(number) * 1024
    except (OSError, ValueError):
        return {}
    return values


def _uptime() -> float | None:
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def collect_host_status() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    memory = _meminfo()
    load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    return {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "uptime_seconds": _uptime(),
        "load_average": list(load),
        "memory_total_bytes": memory.get("MemTotal"),
        "memory_available_bytes": memory.get("MemAvailable"),
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
    }


def main() -> int:
    logger = configure_logging("clientflow.status")
    credential = DomainCredential.load(Domain.STATUS)
    transport = DomainTransport(credential)
    interval = max(15, int(os.getenv("CLIENTFLOW_STATUS_INTERVAL_SECONDS", "30")))
    attempt = 0
    while True:
        try:
            report_status(transport, observed_state="online", payload=collect_host_status())
            attempt = 0
            time.sleep(interval)
        except KeyboardInterrupt:
            return 0
        except Exception:
            logger.exception("status_report_failed")
            time.sleep(backoff_seconds(attempt))
            attempt += 1
