#!/usr/bin/env python3
"""GitHub/CI target-host gate for canonical Ubuntu 26.04 ClientFlow clients."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "client" / "release" / "lib"))

from clientflow_release.runtime_prepare import CLIENTFLOW_ENTRYPOINTS  # noqa: E402
from clientflow_release.systemd_contract import validate_release_systemd_contract  # noqa: E402
from clientflow_release.transaction import Layout, _apply_definitions  # noqa: E402


class HostGateError(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int = 60) -> str:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        raise HostGateError(f"Kommando fejlede: {' '.join(command)}\n{result.stdout[-8000:]}")
    return result.stdout


def _os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def _host_identity() -> dict[str, str]:
    release = _os_release()
    if (release.get("ID"), release.get("VERSION_ID")) != ("ubuntu", "26.04"):
        raise HostGateError(f"CI target host er ikke Ubuntu 26.04: {release.get('ID')} {release.get('VERSION_ID')}")
    if platform.machine() != "x86_64":
        raise HostGateError(f"CI target host er ikke x86_64: {platform.machine()}")
    architecture = _run(["/usr/bin/dpkg", "--print-architecture"]).strip()
    if architecture != "amd64":
        raise HostGateError(f"CI target host dpkg architecture er {architecture}")
    if sys.executable != "/usr/bin/python3":
        raise HostGateError(f"Host gate skal køres med /usr/bin/python3, fik {sys.executable}")
    if sys.version_info[:2] != (3, 14):
        raise HostGateError(f"Ubuntu 26.04 system Python skal være 3.14.x, fik {platform.python_version()}")
    systemd = _run(["/usr/bin/systemd-analyze", "--version"]).splitlines()[0]
    match = re.search(r"systemd\s+(\d+)", systemd)
    if not match or int(match.group(1)) < 259:
        raise HostGateError(f"Ubuntu 26.04 systemd contract kræver >=259, fik {systemd}")
    return {
        "os": release.get("PRETTY_NAME", "Ubuntu 26.04"),
        "architecture": architecture,
        "python": platform.python_version(),
        "systemd": systemd,
    }


def _source_contract(repo: Path) -> dict[str, object]:
    release_input = json.loads((repo / "client/release/release-input.json").read_text(encoding="utf-8"))
    lock = json.loads((repo / "client/release/runtime-platform-inputs.lock.json").read_text(encoding="utf-8"))
    host = lock.get("host_requirements") or {}
    if (
        release_input.get("minimum_ubuntu_lts"),
        release_input.get("architecture"),
        release_input.get("runtime_python"),
    ) != ("26.04", "amd64", "3.13.14"):
        raise HostGateError("release-input target/runtime contract er driftet")
    if (
        host.get("os_id"),
        host.get("version_id"),
        host.get("architecture"),
        lock.get("runtime_python"),
    ) != ("ubuntu", "26.04", "amd64", "3.13.14"):
        raise HostGateError("runtime-platform lock matcher ikke Ubuntu 26.04/runtime 3.13.14 contract")

    pyproject = tomllib.loads((repo / "client/runtime/pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project") or {}
    if project.get("requires-python") != "==3.13.14":
        raise HostGateError("clientflow-runtime Python contract er driftet")
    scripts = set((project.get("scripts") or {}).keys())
    expected = set(CLIENTFLOW_ENTRYPOINTS)
    if scripts != expected:
        raise HostGateError(
            "pyproject console scripts matcher ikke relocation inventory: "
            f"missing={sorted(expected - scripts)} extra={sorted(scripts - expected)}"
        )

    # The embedded installer and client source must at least parse on the host's
    # Python 3.14 before a release candidate is allowed to be built.
    compiled = 0
    for relative in (
        "backend/clientflow_release_format",
        "client/release/lib/clientflow_release",
        "client/runtime/clientflow_runtime",
    ):
        for path in sorted((repo / relative).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            compiled += 1

    with tempfile.TemporaryDirectory(prefix="clientflow-host-source-") as temp_dir:
        temp = Path(temp_dir)
        release_root = temp / "release"
        shutil.copytree(repo / "client/systemd", release_root / "client-runtime/systemd")
        shutil.copytree(repo / "client/sysusers.d", release_root / "client-runtime/sysusers.d")
        shutil.copytree(repo / "client/tmpfiles.d", release_root / "client-runtime/tmpfiles.d")
        shutil.copytree(repo / "client/libexec", release_root / "client-runtime/libexec")
        (release_root / "release/updater").mkdir(parents=True)
        (release_root / "release/updater/clientflow-updater.pyz").write_text("source-gate\n", encoding="utf-8")
        (release_root / "runtime/bin").mkdir(parents=True)
        for name in CLIENTFLOW_ENTRYPOINTS:
            path = release_root / "runtime/bin" / name
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        for name in ("display-power", "update-os"):
            (release_root / "client-runtime/libexec" / name).chmod(0o755)

        summary = validate_release_systemd_contract(release_root)
        layout = Layout(temp / "managed")
        unit_names = _apply_definitions(layout, release_root, kiosk_user="ci-kiosk", client_id=424242)
        for name in unit_names:
            text = (layout.unit_root / name).read_text(encoding="utf-8")
            if re.search(r"@[A-Z0-9_]+@", text):
                raise HostGateError(f"Managed unit har uløst placeholder: {name}")

        # systemd 259 parses the exact source definitions on the target OS. We
        # supply a synthetic root only to satisfy Exec path existence checks.
        root = temp / "systemd-root"
        units_root = root / "etc/systemd/system"
        units_root.mkdir(parents=True)
        for name in unit_names:
            shutil.copy2(layout.unit_root / name, units_root / name)
        active = root / "opt/clientflow/active"
        active.parent.mkdir(parents=True)
        (root / "opt/clientflow/releases/ci/runtime/bin").mkdir(parents=True)
        (root / "opt/clientflow/releases/ci/client-runtime/libexec").mkdir(parents=True)
        active.symlink_to("releases/ci")
        for path in (release_root / "runtime/bin").iterdir():
            target = root / "opt/clientflow/releases/ci/runtime/bin" / path.name
            target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            target.chmod(0o755)
        for path in (release_root / "client-runtime/libexec").iterdir():
            target = root / "opt/clientflow/releases/ci/client-runtime/libexec" / path.name
            target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            target.chmod(0o755)
        for absolute in ("/bin/sh", "/usr/bin/python3"):
            target = root / absolute.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            target.chmod(0o755)
        updater = root / "usr/lib/clientflow/updater/clientflow-updater.pyz"
        updater.parent.mkdir(parents=True)
        updater.write_text("source-gate\n", encoding="utf-8")
        _run(
            [
                "/usr/bin/systemd-analyze",
                f"--root={root}",
                "--recursive-errors=no",
                "--man=no",
                "verify",
                *[str(units_root / name) for name in unit_names],
            ]
        )

    return {
        "compiled_client_python_files": compiled,
        "console_entrypoints": len(expected),
        "systemd_units": summary["unit_count"],
    }


def _load_platform_prepare(repo: Path):
    path = repo / "client/runtime/clientflow_runtime/platform_prepare.py"
    spec = importlib.util.spec_from_file_location("clientflow_ci_platform_prepare", path)
    if spec is None or spec.loader is None:
        raise HostGateError("Kunne ikke indlæse platform_prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.LOCK_PATH = repo / "client/release/runtime-platform-inputs.lock.json"
    return module


def _platform_capabilities(repo: Path) -> dict[str, object]:
    if os.geteuid() != 0:
        raise HostGateError("--install-platform-requirements skal køres som root på ephemeral CI host")
    module = _load_platform_prepare(repo)
    packages = module._requirements()
    module._ensure_packages(packages)
    module._verify_capabilities()
    return {"platform_packages": len(packages), "capabilities": "ok"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--install-platform-requirements", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        result: dict[str, object] = {"host": _host_identity(), "source": _source_contract(repo)}
        if args.install_platform_requirements:
            result["platform"] = _platform_capabilities(repo)
    except Exception as exc:
        print(f"CLIENTFLOW_UBUNTU2604_HOST_GATE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
