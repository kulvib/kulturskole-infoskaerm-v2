from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import host_bootstrap  # noqa: E402


def test_platform_lock_has_one_ubuntu_signed_apt_recovery_artifact() -> None:
    lock = json.loads((ROOT / "client/release/runtime-platform-inputs.lock.json").read_text(encoding="utf-8"))
    artifact = host_bootstrap._select_apt_bootstrap_artifact(lock)
    assert artifact == {
        "file": "apt_3.2.0_amd64.deb",
        "package": "apt",
        "version": "3.2.0",
        "architecture": "amd64",
        "size": 1485978,
        "sha256": "c8f0ba37e66fc367f57a887fba686c67d9487b290ca83bc992baeedc994bf47a",
        "bootstrap_role": "apt-recovery",
        "trust_authority": "ubuntu-signed-apt-repository",
        "ubuntu_suite": "resolute",
        "ubuntu_component": "main",
    }


def test_preclaim_readiness_repairs_apt_before_curl(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_binary(path: Path, *_args: str) -> bool:
        if path == host_bootstrap.APT_GET:
            return "apt-recovered" in calls
        if path == host_bootstrap.CURL:
            return "curl-ready" in calls
        return True

    monkeypatch.setattr(host_bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(host_bootstrap, "_require_target_host", lambda: calls.append("target-host"))
    monkeypatch.setattr(host_bootstrap, "_binary_works", fake_binary)
    monkeypatch.setattr(
        host_bootstrap,
        "_recover_apt_from_bundle",
        lambda *_args, **_kwargs: calls.append("apt-recovered"),
    )
    monkeypatch.setattr(host_bootstrap, "_ensure_curl", lambda: calls.append("curl-ready"))

    result = host_bootstrap.ensure_preclaim_host_readiness(
        tmp_path / "approved.tar",
        expected_bundle_sha256="a" * 64,
    )

    assert calls == ["target-host", "apt-recovered", "curl-ready"]
    assert result == {"apt": "recovered_from_approved_bundle", "curl": "ready"}


def test_preclaim_readiness_failure_happens_before_authority_read_or_state_mutation() -> None:
    source = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    start = source.index("def install_fresh(")
    end = source.index("def _common_transaction_parser", start)
    install = source[start:end]
    readiness = install.index("ensure_preclaim_host_readiness(")
    authorities = install.index("_fresh_install_authorities(args)")
    state_mutation = install.index("ensure_real_directory(layout.state_root")
    claim = install.index("response = claim(")
    assert readiness < authorities < state_mutation < claim


def test_apt_recovery_refuses_newer_installed_version(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "apt.deb"
    package.write_bytes(b"synthetic")
    artifact = {
        "package": "apt",
        "version": "3.2.0",
        "architecture": "amd64",
        "size": len(b"synthetic"),
        "sha256": "0" * 64,
    }
    monkeypatch.setattr(host_bootstrap, "_verify_deb_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        host_bootstrap,
        "_installed_package_identity",
        lambda _package: ("apt", "3.2.1", "amd64"),
    )
    monkeypatch.setattr(
        host_bootstrap.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    with pytest.raises(host_bootstrap.HostBootstrapError, match="nyere end release-bundlens"):
        host_bootstrap._install_apt_from_file(package, artifact)


def test_curl_recovery_uses_apt_only_after_apt_is_ready(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_binary(path: Path, *_args: str) -> bool:
        if path == host_bootstrap.CURL:
            return len(calls) >= 2
        return path == host_bootstrap.APT_GET

    monkeypatch.setattr(host_bootstrap, "_binary_works", fake_binary)
    monkeypatch.setattr(
        host_bootstrap,
        "_run",
        lambda command, **_kwargs: calls.append(command) or SimpleNamespace(stdout=""),
    )

    host_bootstrap._ensure_curl()

    assert calls[0][-1] == "update"
    assert calls[1][-3:] == ["install", "--reinstall", "curl"]
