#!/usr/bin/env python3
"""Destructive-on-ephemeral-host proof of apt/curl preclaim recovery on Ubuntu 26.04."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "client/release/lib"))

from clientflow_release import host_bootstrap  # noqa: E402


class ProbeError(RuntimeError):
    pass


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 300) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "DEBIAN_FRONTEND": "noninteractive",
        },
    )
    if result.returncode != 0:
        raise ProbeError(f"Probe command failed: {' '.join(command)}\n{result.stdout[-8000:]}")
    return result.stdout


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args()
    repo = args.repo.resolve()
    if os.geteuid() != 0:
        raise SystemExit("probe_requires_root")
    host_bootstrap._require_target_host()
    lock = json.loads((repo / "client/release/runtime-platform-inputs.lock.json").read_text(encoding="utf-8"))
    artifact = host_bootstrap._select_apt_bootstrap_artifact(lock)

    with tempfile.TemporaryDirectory(prefix="clientflow-preclaim-host-probe-") as temp_name:
        temp = Path(temp_name)
        _run(["/usr/bin/apt-get", "-o", "DPkg::Lock::Timeout=120", "update"])
        _run(
            [
                "/usr/bin/apt-get",
                "-o",
                "DPkg::Lock::Timeout=120",
                "download",
                f"apt={artifact['version']}",
            ],
            cwd=temp,
        )
        matches = sorted(temp.glob("apt_*_amd64.deb"))
        if len(matches) != 1:
            raise ProbeError(f"Expected one apt recovery package, found {len(matches)}")
        package = matches[0]
        if _sha256(package) != (int(artifact["size"]), str(artifact["sha256"])):
            raise ProbeError("Ubuntu signed APT download does not match repo-locked recovery artifact")
        host_bootstrap._verify_deb_metadata(package, artifact)

        apt_get = Path("/usr/bin/apt-get")
        curl = Path("/usr/bin/curl")
        apt_backup = temp / "apt-get.original"
        curl_backup = temp / "curl.original"
        shutil.copy2(apt_get, apt_backup)
        shutil.copy2(curl, curl_backup)
        try:
            apt_get.unlink()
            if host_bootstrap._binary_works(apt_get, "--version"):
                raise ProbeError("apt-get removal probe did not create missing state")
            host_bootstrap._install_apt_from_file(package, artifact)
            if not host_bootstrap._binary_works(apt_get, "--version"):
                raise ProbeError("apt recovery path did not restore apt-get")

            curl.unlink()
            if host_bootstrap._binary_works(curl, "--version"):
                raise ProbeError("curl removal probe did not create missing state")
            host_bootstrap._ensure_curl()
            if not host_bootstrap._binary_works(curl, "--version"):
                raise ProbeError("curl recovery path did not restore curl")
        finally:
            # Restore the runner's exact original command bytes even when the
            # recovery probe succeeded, so the destructive check cannot leak
            # a changed host binary into later CI steps.
            shutil.copy2(apt_backup, apt_get)
            shutil.copy2(curl_backup, curl)

    print("CLIENTFLOW_PRECLAIM_HOST_BOOTSTRAP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
