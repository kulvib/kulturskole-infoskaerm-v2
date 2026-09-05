from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import tarfile
import tempfile
from typing import Any

from .bundle import open_verified_bundle


class HostBootstrapError(RuntimeError):
    pass


APT_BOOTSTRAP_ROLE = "apt-recovery"
PLATFORM_LOCK_NAME = "runtime-platform-inputs.lock.json"
RUN_PATH = "/run/clientflow-preclaim-bootstrap"
APT_GET = Path("/usr/bin/apt-get")
CURL = Path("/usr/bin/curl")
DPKG = Path("/usr/bin/dpkg")
DPKG_DEB = Path("/usr/bin/dpkg-deb")


def _run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
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
        raise HostBootstrapError(
            f"Host-bootstrap kommando fejlede ({result.returncode}): {' '.join(command)}\n"
            + result.stdout[-4000:]
        )
    return result


def _binary_works(path: Path, *args: str) -> bool:
    if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [str(path), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise HostBootstrapError("Host-bootstrap kan ikke læse /etc/os-release") from exc
    values: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _require_target_host() -> None:
    release = _os_release()
    if (release.get("ID"), release.get("VERSION_ID")) != ("ubuntu", "26.04"):
        raise HostBootstrapError(
            f"Fresh install kræver Ubuntu 26.04, fik {release.get('ID')} {release.get('VERSION_ID')}"
        )
    if platform.machine() != "x86_64":
        raise HostBootstrapError(f"Fresh install kræver x86_64/amd64, fik {platform.machine()}")
    if not _binary_works(DPKG, "--version") or not _binary_works(DPKG_DEB, "--version"):
        raise HostBootstrapError("APT-recovery kræver fungerende dpkg og dpkg-deb på Ubuntu-host")
    architecture = _run([str(DPKG), "--print-architecture"], timeout=30).stdout.strip()
    if architecture != "amd64":
        raise HostBootstrapError(f"Fresh install kræver dpkg architecture amd64, fik {architecture}")


def _sha256_path(path: Path) -> tuple[int, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise HostBootstrapError("Bootstrap artifact er ikke en almindelig fil")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
        return size, digest.hexdigest()
    finally:
        os.close(descriptor)


def _select_apt_bootstrap_artifact(lock: dict[str, Any]) -> dict[str, Any]:
    if lock.get("schema_version") != 1:
        raise HostBootstrapError("Platform-lock har ukendt schema")
    artifacts = lock.get("preclaim_bootstrap_artifacts")
    if not isinstance(artifacts, list):
        raise HostBootstrapError("Platform-lock mangler preclaim_bootstrap_artifacts")
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("bootstrap_role") == APT_BOOTSTRAP_ROLE
    ]
    if len(matches) != 1:
        raise HostBootstrapError("Platform-lock skal indeholde præcis ét canonical APT recovery-artifact")
    artifact = dict(matches[0])
    expected = {
        "package": "apt",
        "architecture": "amd64",
        "trust_authority": "ubuntu-signed-apt-repository",
        "ubuntu_suite": "resolute",
    }
    for key, value in expected.items():
        if artifact.get(key) != value:
            raise HostBootstrapError(f"APT recovery-artifact har ugyldig {key}")
    name = str(artifact.get("file") or "")
    version = str(artifact.get("version") or "")
    digest = str(artifact.get("sha256") or "")
    size = artifact.get("size")
    if not name or Path(name).name != name or not name.startswith("apt_") or not name.endswith("_amd64.deb"):
        raise HostBootstrapError("APT recovery-artifact har ugyldigt filnavn")
    expected_archive_url = f"https://archive.ubuntu.com/ubuntu/pool/main/a/apt/{name}"
    if artifact.get("archive_url") != expected_archive_url:
        raise HostBootstrapError("APT recovery-artifact har ugyldig canonical Ubuntu archive URL")
    if not version or not re.fullmatch(r"[0-9A-Za-z.+:~_-]+", version):
        raise HostBootstrapError("APT recovery-artifact har ugyldig version")
    if not isinstance(size, int) or size <= 0 or size > 32 * 1024 * 1024:
        raise HostBootstrapError("APT recovery-artifact har ugyldig størrelse")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HostBootstrapError("APT recovery-artifact har ugyldig SHA-256")
    return artifact


def _platform_regions(payload, manifest: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    root = str((manifest.get("payload") or {}).get("root") or "")
    if not root:
        raise HostBootstrapError("Release-manifest mangler payload root")
    platform_prefix = f"{root}/runtime-inputs/platform/"
    bootstrap_prefix = f"{root}/runtime-inputs/bootstrap/"
    lock_region = None
    artifact_regions: dict[str, Any] = {}
    try:
        with payload.open() as source:
            with tarfile.open(fileobj=source, mode="r:") as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    region = payload.subregion(member.offset_data, member.size)
                    if member.name.startswith(platform_prefix):
                        relative = member.name[len(platform_prefix):]
                        if relative == PLATFORM_LOCK_NAME:
                            if lock_region is not None:
                                raise HostBootstrapError("Platform payload har dubleret embedded lock")
                            lock_region = region
                        continue
                    if member.name.startswith(bootstrap_prefix):
                        relative = member.name[len(bootstrap_prefix):]
                        if not relative or "/" in relative or relative in artifact_regions:
                            raise HostBootstrapError("Bootstrap payload har ugyldigt eller dubleret artifact-navn")
                        artifact_regions[relative] = region
    except (tarfile.TarError, OSError, ValueError) as exc:
        if isinstance(exc, HostBootstrapError):
            raise
        raise HostBootstrapError("Platform payload kunne ikke læses sikkert") from exc
    if lock_region is None:
        raise HostBootstrapError("Approved bundle mangler embedded platform-lock")
    try:
        lock = json.loads(lock_region.read_small(max_bytes=512 * 1024).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HostBootstrapError("Embedded platform-lock er ugyldig") from exc
    if not isinstance(lock, dict):
        raise HostBootstrapError("Embedded platform-lock skal være et JSON-objekt")
    artifact = _select_apt_bootstrap_artifact(lock)
    region = artifact_regions.get(str(artifact["file"]))
    if region is None:
        raise HostBootstrapError("Approved bundle mangler locked APT recovery-artifact")
    if region.size != int(artifact["size"]) or region.sha256() != str(artifact["sha256"]):
        raise HostBootstrapError("Embedded APT recovery-artifact matcher ikke platform-lock")
    return artifact, region


def _verify_deb_metadata(package_path: Path, artifact: dict[str, Any]) -> None:
    fields = _run(
        [str(DPKG_DEB), "--field", str(package_path), "Package", "Version", "Architecture"],
        timeout=30,
    ).stdout.splitlines()
    values: dict[str, str] = {}
    for line in fields:
        if ": " in line:
            key, value = line.split(": ", 1)
            values[key.strip()] = value.strip()
    expected = {
        "Package": str(artifact["package"]),
        "Version": str(artifact["version"]),
        "Architecture": str(artifact["architecture"]),
    }
    if values != expected:
        raise HostBootstrapError(f"APT recovery .deb metadata matcher ikke lock: {values}")
    size, digest = _sha256_path(package_path)
    if (size, digest) != (int(artifact["size"]), str(artifact["sha256"])):
        raise HostBootstrapError("APT recovery .deb ændrede exact bytes før installation")


def _installed_package_identity(package: str) -> tuple[str, str, str] | None:
    result = subprocess.run(
        [str(DPKG), "-s", package],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        return None
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields[key] = value.strip()
    if fields.get("Status") != "install ok installed":
        return None
    return (
        str(fields.get("Package") or ""),
        str(fields.get("Version") or ""),
        str(fields.get("Architecture") or ""),
    )


def _install_apt_from_file(package_path: Path, artifact: dict[str, Any]) -> None:
    _verify_deb_metadata(package_path, artifact)
    installed = _installed_package_identity("apt")
    if installed is not None:
        _package, installed_version, architecture = installed
        if architecture != "amd64":
            raise HostBootstrapError("Installeret apt package har forkert architecture")
        comparison = subprocess.run(
            [str(DPKG), "--compare-versions", installed_version, "gt", str(artifact["version"])],
            check=False,
        )
        if comparison.returncode == 0:
            raise HostBootstrapError(
                "Installeret apt-version er nyere end release-bundlens recovery-artifact; "
                "fresh install afviser automatisk downgrade"
            )
    _run([str(DPKG), "--install", str(package_path)], timeout=180)
    if not _binary_works(APT_GET, "--version"):
        raise HostBootstrapError("APT recovery-artifact blev installeret, men apt-get er stadig ikke funktionsdygtig")
    identity = _installed_package_identity("apt")
    if identity is None or identity[1] != str(artifact["version"]) or identity[2] != "amd64":
        raise HostBootstrapError("APT package identity matcher ikke recovery-artifact efter installation")


def _recover_apt_from_bundle(bundle: Path, *, expected_bundle_sha256: str) -> None:
    manifest, payload, _size, digest, handle = open_verified_bundle(
        bundle,
        require_deployable=True,
        required_install_mode="fresh_install",
    )
    try:
        if digest != str(expected_bundle_sha256).strip().lower():
            raise HostBootstrapError("APT recovery afviste bundle, der ikke matcher approved whole-bundle SHA-256")
        artifact, region = _platform_regions(payload, manifest)
        run_root = Path(RUN_PATH)
        run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = run_root.lstat()
        if run_root.is_symlink() or not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
            raise HostBootstrapError("Preclaim bootstrap-katalog har usikre rettigheder")
        if os.geteuid() == 0 and metadata.st_uid != 0:
            raise HostBootstrapError("Preclaim bootstrap-katalog er ikke root-owned")
        descriptor, temporary_name = tempfile.mkstemp(prefix="apt-recovery-", suffix=".deb", dir=run_root)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as output, region.open() as source:
                remaining = region.size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise HostBootstrapError("APT recovery-artifact sluttede før deklareret størrelse")
                    output.write(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            _install_apt_from_file(temporary, artifact)
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        handle.close()


def _ensure_curl() -> None:
    if _binary_works(CURL, "--version"):
        return
    if not _binary_works(APT_GET, "--version"):
        raise HostBootstrapError("curl mangler og APT er ikke funktionsdygtig efter recovery")
    _run([str(APT_GET), "-o", "DPkg::Lock::Timeout=120", "update"], timeout=300)
    _run(
        [
            str(APT_GET),
            "-o",
            "DPkg::Lock::Timeout=120",
            "-y",
            "--no-install-recommends",
            "install",
            "--reinstall",
            "curl",
        ],
        timeout=300,
    )
    if not _binary_works(CURL, "--version"):
        raise HostBootstrapError("curl kunne ikke etableres automatisk via canonical Ubuntu APT")


def ensure_preclaim_host_readiness(bundle: Path, *, expected_bundle_sha256: str) -> dict[str, str]:
    """Establish the non-ClientFlow host prerequisites before enrollment can be consumed."""
    if os.geteuid() != 0:
        raise HostBootstrapError("Preclaim host-bootstrap kræver root")
    _require_target_host()
    apt_state = "present"
    if not _binary_works(APT_GET, "--version"):
        _recover_apt_from_bundle(bundle, expected_bundle_sha256=expected_bundle_sha256)
        apt_state = "recovered_from_approved_bundle"
    _ensure_curl()
    if not _binary_works(APT_GET, "--version") or not _binary_works(CURL, "--version"):
        raise HostBootstrapError("Preclaim host-readiness kunne ikke bevises fail-closed")
    return {"apt": apt_state, "curl": "ready"}
