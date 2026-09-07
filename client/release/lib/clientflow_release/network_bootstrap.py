from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid


NMCLI = Path("/usr/bin/nmcli")
CURL = Path("/usr/bin/curl")
IP = Path("/usr/sbin/ip")

_ALLOWED_BOOTSTRAP_CONNECTION_TYPES = {
    "wifi",
    "802-11-wireless",
    "ethernet",
    "802-3-ethernet",
}
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class NetworkBootstrapError(RuntimeError):
    pass


def normalize_client_name(value: str | None) -> str:
    name = str(value or "").strip()
    if not name:
        raise NetworkBootstrapError("Fresh install kræver et eksplicit klientnavn før enrollment")
    if len(name) > 120 or _CONTROL_RE.search(name):
        raise NetworkBootstrapError("Klientnavn er ugyldigt")
    return name


def normalize_locality(value: str | None) -> str | None:
    locality = str(value or "").strip()
    if not locality:
        return None
    if len(locality) > 200 or _CONTROL_RE.search(locality):
        raise NetworkBootstrapError("Lokation er ugyldig")
    return locality


def normalize_connection_uuid(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError as exc:
        raise NetworkBootstrapError("Bootstrap NetworkManager UUID er ugyldig") from exc


def _run(command: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise NetworkBootstrapError(
            f"Netværkskommando fejlede ({result.returncode}): {' '.join(command)}\n{result.stdout[-4000:]}"
        )
    return result


def _require_networkmanager() -> None:
    if not NMCLI.is_file():
        raise NetworkBootstrapError(
            "Ubuntu Desktop fresh install kræver /usr/bin/nmcli (NetworkManager)"
        )
    running = _run([str(NMCLI), "--terse", "--fields", "RUNNING", "general"]).stdout.strip().lower()
    if running != "running":
        raise NetworkBootstrapError("NetworkManager er ikke running")


def _device_rows() -> list[dict[str, str]]:
    result = _run(
        [
            str(NMCLI),
            "--terse",
            "--escape",
            "no",
            "--fields",
            "DEVICE,TYPE,STATE,CONNECTION",
            "device",
            "status",
        ]
    )
    rows: list[dict[str, str]] = []
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        parts = raw.split(":", 3)
        while len(parts) < 4:
            parts.append("")
        rows.append(
            {
                "device": parts[0].strip(),
                "type": parts[1].strip(),
                "state": parts[2].strip(),
                "connection": parts[3].strip(),
            }
        )
    return rows


def _active_connections() -> dict[str, dict[str, str]]:
    result = _run(
        [
            str(NMCLI),
            "--terse",
            "--escape",
            "no",
            "--fields",
            "UUID,TYPE,NAME",
            "connection",
            "show",
            "--active",
        ]
    )
    rows: dict[str, dict[str, str]] = {}
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        parts = raw.split(":", 2)
        while len(parts) < 3:
            parts.append("")
        try:
            connection_uuid = str(uuid.UUID(parts[0].strip()))
        except ValueError:
            continue
        rows[connection_uuid] = {
            "uuid": connection_uuid,
            "type": parts[1].strip(),
            "name": parts[2].strip(),
        }
    return rows


def _all_connections() -> dict[str, dict[str, str]]:
    result = _run(
        [
            str(NMCLI),
            "--terse",
            "--escape",
            "no",
            "--fields",
            "UUID,TYPE,NAME",
            "connection",
            "show",
        ]
    )
    rows: dict[str, dict[str, str]] = {}
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        parts = raw.split(":", 2)
        while len(parts) < 3:
            parts.append("")
        try:
            connection_uuid = str(uuid.UUID(parts[0].strip()))
        except ValueError:
            continue
        rows[connection_uuid] = {
            "uuid": connection_uuid,
            "type": parts[1].strip(),
            "name": parts[2].strip(),
        }
    return rows


def _probe_backend_health(backend_url: str, *, ca_file: Path | None = None) -> None:
    if not CURL.is_file():
        raise NetworkBootstrapError("Preclaim host-readiness skulle have etableret /usr/bin/curl")
    command = [
        str(CURL),
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--max-time",
        "12",
    ]
    if ca_file is not None:
        command.extend(["--cacert", str(ca_file.resolve())])
    command.append(backend_url.rstrip("/") + "/health")
    raw = _run(command, timeout=20).stdout
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NetworkBootstrapError("Backend /health returnerede ikke gyldig JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise NetworkBootstrapError("Backend /health er ikke canonical healthy")


def ensure_preclaim_network_readiness(
    backend_url: str,
    *,
    ca_file: Path | None = None,
    bootstrap_connection_uuid: str | None = None,
) -> dict[str, object]:
    """Prove NetworkManager connectivity + backend health before enrollment secrets are read."""
    _require_networkmanager()
    devices = _device_rows()
    connected = [
        row
        for row in devices
        if row["state"] == "connected"
        and row["device"]
        and row["device"] != "lo"
        and row["type"] not in {"loopback", "dummy"}
    ]
    if not connected:
        raise NetworkBootstrapError(
            "Ingen aktiv NetworkManager-forbindelse; tilslut Ethernet eller WiFi før enrollment"
        )
    _probe_backend_health(backend_url, ca_file=ca_file)

    marker = None
    requested_uuid = normalize_connection_uuid(bootstrap_connection_uuid)
    if requested_uuid is not None:
        active = _active_connections()
        row = active.get(requested_uuid)
        if row is None:
            raise NetworkBootstrapError(
                "Den markerede bootstrap NetworkManager-forbindelse er ikke aktiv"
            )
        if row["type"] not in _ALLOWED_BOOTSTRAP_CONNECTION_TYPES:
            raise NetworkBootstrapError(
                "Kun aktiv WiFi/Ethernet må markeres som ClientFlow bootstrap-forbindelse"
            )
        marker = dict(row)

    return {
        "backend_health": "ok",
        "connected_devices": connected,
        "bootstrap_connection": marker,
    }


def cleanup_bootstrap_connection(marker: dict[str, object] | None) -> dict[str, object]:
    """Delete only the exact NetworkManager profile explicitly recorded by fresh install."""
    if not marker:
        return {"status": "not_marked"}
    connection_uuid = normalize_connection_uuid(str(marker.get("uuid") or ""))
    expected_type = str(marker.get("type") or "")
    expected_name = str(marker.get("name") or "")
    if connection_uuid is None or expected_type not in _ALLOWED_BOOTSTRAP_CONNECTION_TYPES:
        raise NetworkBootstrapError("Gemte bootstrap NetworkManager metadata er ugyldige")

    _require_networkmanager()
    current = _all_connections().get(connection_uuid)
    if current is None:
        return {"status": "already_absent", "uuid": connection_uuid}
    if current["type"] != expected_type or current["name"] != expected_name:
        raise NetworkBootstrapError(
            "Bootstrap NetworkManager UUID matcher ikke længere den oprindeligt markerede profil"
        )

    _run([str(NMCLI), "connection", "delete", "uuid", connection_uuid], timeout=30)
    if connection_uuid in _all_connections():
        raise NetworkBootstrapError("Bootstrap NetworkManager-profilen findes stadig efter cleanup")
    return {"status": "deleted", "uuid": connection_uuid}


def collect_network_facts() -> dict[str, str | None]:
    """Collect the same bounded WiFi/LAN facts accepted by the enrollment backend."""
    ip_binary = IP if IP.is_file() else Path(shutil.which("ip") or "")
    facts: dict[str, str | None] = {
        "wifi_ip_address": None,
        "wifi_mac_address": None,
        "lan_ip_address": None,
        "lan_mac_address": None,
    }
    net_root = Path("/sys/class/net")
    if not net_root.is_dir():
        return facts

    for interface_path in sorted(net_root.iterdir(), key=lambda item: item.name):
        interface = interface_path.name
        if interface == "lo":
            continue
        mac = None
        try:
            value = (interface_path / "address").read_text(encoding="utf-8").strip().lower()
            if value:
                mac = value
        except OSError:
            pass
        ip_address = None
        if ip_binary and ip_binary.is_file():
            result = subprocess.run(
                [str(ip_binary), "-4", "-o", "addr", "show", "dev", interface],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for raw in result.stdout.splitlines():
                    fields = raw.split()
                    if "inet" in fields:
                        index = fields.index("inet")
                        if index + 1 < len(fields):
                            ip_address = fields[index + 1].split("/", 1)[0]
                            break
        wireless = (
            interface.startswith(("wl", "wlan", "wifi"))
            or (interface_path / "wireless").exists()
        )
        prefix = "wifi" if wireless else "lan"
        if facts[f"{prefix}_ip_address"] is None and ip_address:
            facts[f"{prefix}_ip_address"] = ip_address
        if facts[f"{prefix}_mac_address"] is None and mac:
            facts[f"{prefix}_mac_address"] = mac
    return facts
