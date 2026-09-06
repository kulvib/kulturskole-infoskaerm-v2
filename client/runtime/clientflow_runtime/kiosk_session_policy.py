"""Bounded recurring kiosk-session baseline for Ubuntu 26.04.

The policy only mutates host/session settings while the canonical local kiosk
session is active on seat0.  cfadmin, frozen ClientFlow domains and credentials
are intentionally outside this authority.
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import subprocess

KIOSK_USER = "clientflow-kiosk"
LOGINCTL = Path("/usr/bin/loginctl")
RUNUSER = Path("/usr/sbin/runuser")
GSETTINGS = Path("/usr/bin/gsettings")
NMCLI = Path("/usr/bin/nmcli")
RFKILL = Path("/usr/sbin/rfkill")
POWERPROFILESCTL = Path("/usr/bin/powerprofilesctl")
WPCTL = Path("/usr/bin/wpctl")


class KioskSessionPolicyError(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
        },
        check=False,
    )
    if check and completed.returncode != 0:
        raise KioskSessionPolicyError(
            f"Kommando fejlede ({completed.returncode}): {' '.join(command)}\n"
            f"{(completed.stdout or '')[-4000:]}"
        )
    return completed


def _session_properties(session_id: str) -> dict[str, str]:
    result = _run(
        [
            str(LOGINCTL),
            "show-session",
            session_id,
            "--property=Name",
            "--property=Active",
            "--property=Remote",
            "--property=Seat",
        ],
        check=False,
    )
    if result.returncode != 0:
        return {}
    values: dict[str, str] = {}
    for raw in result.stdout.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key] = value
    return values


def _active_local_kiosk_session() -> str | None:
    if not LOGINCTL.is_file() or not os.access(LOGINCTL, os.X_OK):
        raise KioskSessionPolicyError("Ubuntu host mangler /usr/bin/loginctl")
    result = _run([str(LOGINCTL), "list-sessions", "--no-legend", "--no-pager"])
    for raw in result.stdout.splitlines():
        parts = raw.split()
        if not parts:
            continue
        session_id = parts[0]
        properties = _session_properties(session_id)
        if (
            properties.get("Name") == KIOSK_USER
            and properties.get("Active", "").lower() == "yes"
            and properties.get("Remote", "").lower() == "no"
            and properties.get("Seat") == "seat0"
        ):
            return session_id
    return None


def _user_command(record: pwd.struct_passwd, command: list[str]) -> list[str]:
    runtime_dir = Path(f"/run/user/{record.pw_uid}")
    return [
        str(RUNUSER),
        "-u",
        KIOSK_USER,
        "--",
        "env",
        f"HOME={record.pw_dir}",
        f"XDG_RUNTIME_DIR={runtime_dir}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir / 'bus'}",
        *command,
    ]


def _apply_gsettings(record: pwd.struct_passwd) -> None:
    runtime_dir = Path(f"/run/user/{record.pw_uid}")
    bus = runtime_dir / "bus"
    if not bus.exists():
        print("CLIENTFLOW_KIOSK_SESSION_POLICY_OPTIONAL: session bus ikke klar", flush=True)
        return
    for schema, key, value in (
        ("org.gnome.settings-daemon.plugins.color", "night-light-enabled", "false"),
        ("org.gnome.desktop.interface", "color-scheme", "'default'"),
    ):
        _run(_user_command(record, [str(GSETTINGS), "set", schema, key, value]))


def _apply_audio(record: pwd.struct_passwd) -> None:
    if not WPCTL.is_file() or not os.access(WPCTL, os.X_OK):
        print("CLIENTFLOW_KIOSK_SESSION_POLICY_OPTIONAL: /usr/bin/wpctl mangler", flush=True)
        return
    runtime_dir = Path(f"/run/user/{record.pw_uid}")
    if not (runtime_dir / "pipewire-0").exists():
        print("CLIENTFLOW_KIOSK_SESSION_POLICY_OPTIONAL: PipeWire sink ikke klar", flush=True)
        return
    base = _user_command(record, [str(WPCTL)])
    _run([*base, "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
    _run([*base, "set-volume", "@DEFAULT_AUDIO_SINK@", "0.60"])


def enforce() -> None:
    if os.geteuid() != 0:
        raise KioskSessionPolicyError("Kiosk session-policy kræver root")
    for binary in (RUNUSER, GSETTINGS, NMCLI, RFKILL):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise KioskSessionPolicyError(f"Ubuntu kiosk-baseline mangler {binary}")

    session_id = _active_local_kiosk_session()
    if session_id is None:
        print("CLIENTFLOW_KIOSK_SESSION_POLICY_SKIPPED: ingen aktiv lokal kiosk-session", flush=True)
        return
    try:
        record = pwd.getpwnam(KIOSK_USER)
    except KeyError as exc:
        raise KioskSessionPolicyError("Canonical kiosk-bruger findes ikke") from exc
    if record.pw_uid == 0 or record.pw_dir != f"/home/{KIOSK_USER}":
        raise KioskSessionPolicyError("Canonical kiosk-account contract er ugyldig")

    # System-level quick-settings are only reasserted while kiosk owns seat0.
    _run([str(NMCLI), "radio", "wifi", "on"])
    _run([str(RFKILL), "block", "bluetooth"])

    if POWERPROFILESCTL.is_file() and os.access(POWERPROFILESCTL, os.X_OK):
        _run([str(POWERPROFILESCTL), "set", "balanced"])
    else:
        print("CLIENTFLOW_KIOSK_SESSION_POLICY_OPTIONAL: powerprofilesctl mangler", flush=True)

    _apply_gsettings(record)
    _apply_audio(record)
    print(f"CLIENTFLOW_KIOSK_SESSION_POLICY_OK: session={session_id}", flush=True)


def main() -> int:
    try:
        enforce()
    except (OSError, ValueError, KioskSessionPolicyError) as exc:
        print(f"CLIENTFLOW_KIOSK_SESSION_POLICY_FAILED: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
