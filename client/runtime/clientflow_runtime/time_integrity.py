"""Periodic ClientFlow host time-integrity enforcement for Ubuntu 26.04."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

EXPECTED_TIMEZONE = "Europe/Copenhagen"
TIMEDATECTL = Path("/usr/bin/timedatectl")


class TimeIntegrityError(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int = 30) -> str:
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
    if completed.returncode != 0:
        raise TimeIntegrityError(
            f"Kommando fejlede ({completed.returncode}): {' '.join(command)}\n"
            f"{(completed.stdout or '')[-4000:]}"
        )
    return completed.stdout or ""


def enforce() -> None:
    if os.geteuid() != 0:
        raise TimeIntegrityError("Time-integrity kræver root")
    if not TIMEDATECTL.is_file() or not os.access(TIMEDATECTL, os.X_OK):
        raise TimeIntegrityError("Ubuntu host mangler /usr/bin/timedatectl")

    current = _run([str(TIMEDATECTL), "show", "--property=Timezone", "--value"]).strip()
    if current != EXPECTED_TIMEZONE:
        _run([str(TIMEDATECTL), "set-timezone", EXPECTED_TIMEZONE])

    ntp = _run([str(TIMEDATECTL), "show", "--property=NTP", "--value"]).strip().lower()
    if ntp not in {"yes", "true", "1", "on"}:
        _run([str(TIMEDATECTL), "set-ntp", "true"])

    verified_timezone = _run(
        [str(TIMEDATECTL), "show", "--property=Timezone", "--value"]
    ).strip()
    verified_ntp = _run([str(TIMEDATECTL), "show", "--property=NTP", "--value"]).strip().lower()
    if verified_timezone != EXPECTED_TIMEZONE:
        raise TimeIntegrityError(
            f"Timezone kunne ikke fastholdes: {verified_timezone!r} != {EXPECTED_TIMEZONE!r}"
        )
    if verified_ntp not in {"yes", "true", "1", "on"}:
        raise TimeIntegrityError("NTP kunne ikke fastholdes aktiveret")


def main() -> int:
    try:
        enforce()
    except (OSError, ValueError, TimeIntegrityError) as exc:
        print(f"CLIENTFLOW_TIME_INTEGRITY_FAILED: {exc}", flush=True)
        return 1
    print("CLIENTFLOW_TIME_INTEGRITY_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
