"""Canonical Ubuntu 26.04 host-platform prerequisite gate.

Frozen Livestream/Remote Desktop consumers remain unchanged. This gate installs
only release-declared additive Ubuntu packages and verifies their capabilities.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess

RELEASE_ROOT = Path(os.getenv("CLIENTFLOW_RELEASE_ROOT", "/opt/clientflow/active"))
LOCK_PATH = RELEASE_ROOT / "runtime-inputs/platform/runtime-platform-inputs.lock.json"
SYSTEM_PYTHON = Path("/usr/bin/python3")
EXPECTED_TIMEZONE = "Europe/Copenhagen"


class PlatformPreparationError(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int = 600) -> str:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "DEBIAN_FRONTEND": "noninteractive",
        },
        check=False,
    )
    if completed.returncode != 0:
        raise PlatformPreparationError(
            f"Kommando fejlede ({completed.returncode}): {' '.join(command)}\n"
            f"{(completed.stdout or '')[-4000:]}"
        )
    return completed.stdout or ""


def _os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _requirements() -> list[dict]:
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlatformPreparationError("Release mangler gyldig runtime-platform-input lock") from exc
    host = data.get("host_requirements")
    if data.get("schema_version") != 1 or not isinstance(host, dict):
        raise PlatformPreparationError("Release mangler canonical host_requirements")
    if (host.get("os_id"), host.get("version_id"), host.get("architecture")) != ("ubuntu", "26.04", "amd64"):
        raise PlatformPreparationError("Host requirement er ikke Ubuntu 26.04 amd64")
    packages = host.get("packages")
    if not isinstance(packages, list) or not packages:
        raise PlatformPreparationError("Host requirement mangler package-kontrakt")
    return packages


def _installed_version(package: str) -> str | None:
    completed = subprocess.run(
        ["/usr/bin/dpkg-query", "-W", "-f=${Status}\t${Version}", package],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    parts = completed.stdout.strip().split("\t")
    return parts[1] if len(parts) == 2 and parts[0] == "install ok installed" else None


def _version_at_least(observed: str, minimum: str) -> bool:
    return subprocess.run(
        ["/usr/bin/dpkg", "--compare-versions", observed, "ge", minimum],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _ensure_packages(packages: list[dict]) -> None:
    missing: list[str] = []
    for row in packages:
        package = str(row.get("package") or "")
        minimum = str(row.get("minimum_version") or "")
        if not package or not minimum:
            raise PlatformPreparationError("Host package entry mangler package/minimum_version")
        observed = _installed_version(package)
        if observed is None or not _version_at_least(observed, minimum):
            missing.append(package)
    if missing:
        _run(["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "update"], timeout=600)
        _run(["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "-y", "--no-install-recommends", "install", *missing], timeout=1200)
    for row in packages:
        observed = _installed_version(str(row["package"]))
        if observed is None or not _version_at_least(observed, str(row["minimum_version"])):
            raise PlatformPreparationError(
                f"{row['package']}={observed!r} opfylder ikke minimum {row['minimum_version']}"
            )


def _prepare_time_integrity() -> None:
    timedatectl = "/usr/bin/timedatectl"
    current = _run([timedatectl, "show", "--property=Timezone", "--value"], timeout=30).strip()
    if current != EXPECTED_TIMEZONE:
        _run([timedatectl, "set-timezone", EXPECTED_TIMEZONE], timeout=30)
    _run([timedatectl, "set-ntp", "true"], timeout=30)
    enabled = _run([timedatectl, "show", "--property=NTP", "--value"], timeout=30).strip().lower()
    if enabled not in {"yes", "true", "1", "on"}:
        raise PlatformPreparationError("Ubuntu host-platform kunne ikke aktivere NTP")


def _verify_capabilities() -> None:
    required_binaries = (
        Path("/usr/bin/setfacl"),
        Path("/usr/bin/setpriv"),
        Path("/usr/bin/loginctl"),
        Path("/usr/bin/gdbus"),
        Path("/usr/bin/gsettings"),
        Path("/usr/bin/dbus-run-session"),
        Path("/usr/sbin/rfkill"),
        Path("/usr/bin/timedatectl"),
        SYSTEM_PYTHON,
    )
    missing_binaries = [str(path) for path in required_binaries if not path.exists() or not os.access(path, os.X_OK)]
    if missing_binaries:
        raise PlatformPreparationError("Host-platform mangler executables: " + ", ".join(missing_binaries))

    # Frozen Livestream and Remote Desktop helpers deliberately execute with
    # Ubuntu's /usr/bin/python3 so PyGObject/GI must be verified with the exact
    # interpreter they use, not ClientFlow's bundled Python 3.13 runtime.
    probe = r'''
import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gio, GLib, Gst, GstApp, Gtk, Pango
Gst.init(None)
required = (
    "pipewiresrc",
    "queue",
    "videoconvert",
    "videorate",
    "videoscale",
    "jpegenc",
    "appsink",
    "x264enc",
    "h264parse",
    "mpegtsmux",
    "hlssink",
)
missing = [name for name in required if Gst.ElementFactory.find(name) is None]
if missing:
    raise SystemExit("missing_gstreamer_elements:" + ",".join(missing))
print("CLIENTFLOW_PLATFORM_CAPABILITIES_OK")
'''
    _run([str(SYSTEM_PYTHON), "-c", probe], timeout=60)


def prepare() -> None:
    if os.geteuid() != 0:
        raise PlatformPreparationError("Platform preparation kræver root")
    release = _os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "26.04":
        raise PlatformPreparationError(
            f"Uunderstøttet platform: {release.get('ID')} {release.get('VERSION_ID')}"
        )
    if platform.machine() != "x86_64":
        raise PlatformPreparationError(f"Uunderstøttet arkitektur: {platform.machine()}")
    _ensure_packages(_requirements())
    _prepare_time_integrity()
    _verify_capabilities()


def main() -> int:
    try:
        prepare()
    except (OSError, ValueError, PlatformPreparationError) as exc:
        print(f"CLIENTFLOW_PLATFORM_PREPARE_FAILED: {exc}", flush=True)
        return 1
    print("CLIENTFLOW_PLATFORM_PREPARE_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
