"""Read-only canonical host telemetry agent. It cannot claim commands or control services."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
from typing import Any

from .config import DomainCredential
from .constants import Domain, SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS
from .logging_utils import configure_logging
from .net import DomainTransport, backoff_seconds
from .status import report_status

ACTIVE_SYSTEMD_ROOT = Path("/opt/clientflow/active/client-runtime/systemd")
SYS_CLASS_NET = Path("/sys/class/net")


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


def _safe_run(command: list[str], *, timeout: int = 5) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ip_json(*args: str) -> list[dict[str, Any]]:
    result = _safe_run(["/usr/sbin/ip", "-j", *args])
    if result is None or result.returncode != 0:
        return []
    try:
        value = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _default_interface() -> str | None:
    for args in (("route", "show", "default"), ("-6", "route", "show", "default")):
        for row in _ip_json(*args):
            dev = str(row.get("dev") or "").strip()
            if dev:
                return dev
    return None


def _interface_type(name: str | None) -> str | None:
    if not name:
        return None
    if name.startswith(("wl", "wlan")):
        return "wifi"
    if name.startswith(("en", "eth")):
        return "lan"
    return "other"


def _interface_mac(name: str | None) -> str | None:
    if not name:
        return None
    try:
        value = (SYS_CLASS_NET / name / "address").read_text(encoding="ascii").strip().lower()
    except OSError:
        return None
    return value or None


def _interface_ip(name: str | None) -> str | None:
    if not name:
        return None
    rows = _ip_json("address", "show", "dev", name)
    for family in ("inet", "inet6"):
        for row in rows:
            for address in row.get("addr_info") or []:
                if address.get("family") != family or address.get("scope") != "global":
                    continue
                value = str(address.get("local") or "").strip()
                if value:
                    return value
    return None


def _first_interface(kind: str) -> str | None:
    try:
        names = sorted(path.name for path in SYS_CLASS_NET.iterdir())
    except OSError:
        return None
    return next((name for name in names if _interface_type(name) == kind), None)


def _network_status() -> dict[str, Any]:
    active = _default_interface()
    active_ip = _interface_ip(active)
    wifi = _first_interface("wifi")
    lan = _first_interface("lan")
    connected = bool(active and active_ip)
    return {
        "network_status": "ok" if connected else "no_network",
        "network_has_connection": connected,
        "active_network_type": _interface_type(active),
        "active_network_interface": active,
        "active_network_ip": active_ip,
        "active_network_mac": _interface_mac(active),
        "wifi_ip_address": _interface_ip(wifi),
        "wifi_mac_address": _interface_mac(wifi),
        "lan_ip_address": _interface_ip(lan),
        "lan_mac_address": _interface_mac(lan),
    }


def _time_status() -> dict[str, Any]:
    result = _safe_run(
        [
            "/usr/bin/timedatectl",
            "show",
            "--property=Timezone",
            "--property=NTP",
            "--property=NTPSynchronized",
            "--value",
        ]
    )
    lines = (result.stdout or "").splitlines() if result is not None and result.returncode == 0 else []

    def tri(value: str | None) -> bool | None:
        normalized = str(value or "").strip().lower()
        if normalized in {"yes", "true", "1"}:
            return True
        if normalized in {"no", "false", "0"}:
            return False
        return None

    return {
        "diagnostics_updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "system_timezone": lines[0].strip() if len(lines) > 0 and lines[0].strip() else None,
        "ntp_enabled": tri(lines[1] if len(lines) > 1 else None),
        "ntp_synchronized": tri(lines[2] if len(lines) > 2 else None),
        "client_time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _service_status() -> dict[str, str]:
    try:
        units = sorted(
            path.name
            for path in ACTIVE_SYSTEMD_ROOT.iterdir()
            if path.is_file() and path.suffix in {".service", ".socket", ".target", ".timer"}
        )
    except OSError:
        return {}
    if not units:
        return {}
    result = _safe_run(["/usr/bin/systemctl", "is-active", *units], timeout=15)
    if result is None:
        return {}
    states = (result.stdout or "").splitlines()
    if len(states) != len(units):
        return {}
    return {unit: state.strip() or "unknown" for unit, state in zip(units, states)}


def _ubuntu_version() -> str | None:
    try:
        values = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        return None
    return values.get("PRETTY_NAME") or values.get("VERSION_ID")


def collect_host_status() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    memory = _meminfo()
    load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    payload: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "ubuntu_version": _ubuntu_version(),
        "uptime_seconds": _uptime(),
        "load_average": list(load),
        "memory_total_bytes": memory.get("MemTotal"),
        "memory_available_bytes": memory.get("MemAvailable"),
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "services": _service_status(),
    }
    payload.update(_network_status())
    payload.update(_time_status())
    return payload


def main() -> int:
    logger = configure_logging("clientflow.status")
    credential = DomainCredential.load(Domain.STATUS)
    transport = DomainTransport(credential)
    attempt = 0
    while True:
        try:
            report_status(transport, observed_state="online", payload=collect_host_status())
            attempt = 0
            time.sleep(SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            return 0
        except Exception:
            logger.exception("status_report_failed")
            time.sleep(backoff_seconds(attempt))
            attempt += 1
