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
import urllib.error
import urllib.request

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
        package = temp / str(artifact["file"])
        # Do not ask the runner's mutable APT index to resolve an old exact
        # release package. Ubuntu archive pools retain immutable package files
        # after package indexes advance. The production recovery path never
        # downloads this file: it consumes the exact hash-locked bytes already
        # embedded in the approved whole bundle. This CI authority probe only
        # proves that those locked bytes still match Canonical's archive copy.
        request = urllib.request.Request(
            str(artifact["archive_url"]),
            headers={"User-Agent": "ClientFlow-preclaim-bootstrap-probe/1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response, package.open("xb") as output:
                remaining = int(artifact["size"]) + 1
                while remaining > 0:
                    chunk = response.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    output.write(chunk)
                    remaining -= len(chunk)
                if response.read(1):
                    raise ProbeError("Ubuntu archive artifact exceeds repo-locked size")
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            package.unlink(missing_ok=True)
            raise ProbeError(f"Unable to fetch locked APT artifact from canonical Ubuntu archive: {exc}") from exc
        if not package.is_file() or package.is_symlink():
            raise ProbeError("Canonical Ubuntu archive download did not materialize the locked APT artifact")
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
