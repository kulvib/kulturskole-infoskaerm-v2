"""Root-owned preparation for the canonical Display/Google Chrome platform contract."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile
from typing import Iterable

CHROME_PACKAGE = "google-chrome-stable"
CHROME_EXECUTABLE = Path("/usr/bin/google-chrome-stable")
DEFAULT_RELEASE_ROOT = Path("/opt/clientflow/active")
PLATFORM_RELATIVE = Path("runtime-inputs/platform")
LOCK_NAME = "runtime-platform-inputs.lock.json"
GOOGLE_REPOSITORY_MARKER = "google.com/linux/chrome"


class DisplayPlatformPreparationError(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int = 300) -> str:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
        },
    )
    if result.returncode != 0:
        raise DisplayPlatformPreparationError(
            f"Kommando fejlede ({result.returncode}): {' '.join(command)}\n{result.stdout[-4000:]}"
        )
    return result.stdout


def _sha256(path: Path) -> tuple[int, str]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise DisplayPlatformPreparationError(f"Platform artifact er ikke en regulær fil: {path.name}")
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def _load_chrome_artifact(release_root: Path) -> tuple[Path, dict[str, object]]:
    platform_root = release_root / PLATFORM_RELATIVE
    lock_path = platform_root / LOCK_NAME
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DisplayPlatformPreparationError("Release mangler gyldig runtime-platform-input lock") from exc
    if data.get("schema_version") != 1:
        raise DisplayPlatformPreparationError("runtime-platform-input lock har ukendt schema")
    raw_artifacts = data.get("platform_artifacts")
    if not isinstance(raw_artifacts, list) or len(raw_artifacts) != 1 or not isinstance(raw_artifacts[0], dict):
        raise DisplayPlatformPreparationError("Release skal have præcis ét canonical Display-platformartifact")
    artifact = dict(raw_artifacts[0])
    expected = {
        "package": CHROME_PACKAGE,
        "architecture": "amd64",
    }
    for key, value in expected.items():
        if artifact.get(key) != value:
            raise DisplayPlatformPreparationError(f"Chrome platform lock har forkert {key}")
    name = str(artifact.get("file") or "")
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise DisplayPlatformPreparationError("Chrome platform lock har ugyldigt filnavn")
    version = str(artifact.get("version") or "")
    digest = str(artifact.get("sha256") or "")
    size = artifact.get("size")
    if not version or not isinstance(size, int) or size <= 0:
        raise DisplayPlatformPreparationError("Chrome platform lock mangler version/size")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise DisplayPlatformPreparationError("Chrome platform lock har ugyldig SHA-256")
    artifact_path = platform_root / name
    actual_size, actual_digest = _sha256(artifact_path)
    if actual_size != size or actual_digest != digest:
        raise DisplayPlatformPreparationError("Embedded Google Chrome .deb matcher ikke release-lock")
    return artifact_path, artifact


def _dpkg_deb_field(package_path: Path, field: str) -> str:
    return _run(["/usr/bin/dpkg-deb", "--field", str(package_path), field], timeout=30).strip()


def _verify_deb_metadata(package_path: Path, artifact: dict[str, object]) -> None:
    for field, lock_key in (("Package", "package"), ("Version", "version"), ("Architecture", "architecture")):
        observed = _dpkg_deb_field(package_path, field)
        expected = str(artifact[lock_key])
        if observed != expected:
            raise DisplayPlatformPreparationError(
                f"Google Chrome .deb metadata mismatch: {field}={observed!r}, forventet {expected!r}"
            )


def _active_google_repo_files(apt_root: Path = Path("/etc/apt")) -> list[Path]:
    candidates = [apt_root / "sources.list"]
    sources_dir = apt_root / "sources.list.d"
    if sources_dir.is_dir():
        candidates.extend(
            sorted(
                path
                for path in sources_dir.iterdir()
                if path.is_file() and not path.is_symlink() and path.suffix in {".list", ".sources"}
            )
        )
    active: list[Path] = []
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise DisplayPlatformPreparationError(f"Kan ikke læse APT source: {path}") from exc
        if path.suffix == ".sources":
            for stanza in re.split(r"\n\s*\n", text):
                meaningful = [line.strip() for line in stanza.splitlines() if line.strip() and not line.lstrip().startswith("#")]
                joined = "\n".join(meaningful)
                if GOOGLE_REPOSITORY_MARKER not in joined:
                    continue
                enabled = next((line.split(":", 1)[1].strip().lower() for line in meaningful if line.lower().startswith("enabled:")), "yes")
                if enabled not in {"no", "false", "0"}:
                    active.append(path)
                    break
        else:
            if any(
                GOOGLE_REPOSITORY_MARKER in line
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ):
                active.append(path)
    return active


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _preconfigure_google_repo_opt_out(defaults_path: Path = Path("/etc/default/google-chrome")) -> None:
    lines = defaults_path.read_text(encoding="utf-8").splitlines() if defaults_path.exists() else []
    out: list[str] = []
    replaced = False
    for line in lines:
        if re.match(r"^\s*repo_add_once\s*=", line):
            if not replaced:
                out.append('repo_add_once="false"')
                replaced = True
            continue
        out.append(line)
    if not replaced:
        out.append('repo_add_once="false"')
    _atomic_write_text(defaults_path, "\n".join(out).rstrip() + "\n")


def _repo_opt_out_is_false(defaults_path: Path = Path("/etc/default/google-chrome")) -> bool:
    if not defaults_path.is_file():
        return False
    for line in defaults_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*repo_add_once\s*=\s*[\"']?([^\"'#\s]+)", line)
        if match:
            return match.group(1).lower() == "false"
    return False


def _installed_chrome() -> tuple[str, str, str] | None:
    result = subprocess.run(
        ["/usr/bin/dpkg-query", "-W", "-f=${Status}\t${Version}\t${Architecture}", CHROME_PACKAGE],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split("\t")
    if len(parts) != 3 or parts[0] != "install ok installed":
        return None
    return parts[0], parts[1], parts[2]


def _simulate_local_deb_install(package_path: Path) -> None:
    output = _run(["/usr/bin/apt-get", "-s", "--no-download", "install", str(package_path)])
    installs = []
    for line in output.splitlines():
        match = re.match(r"^Inst\s+(\S+)", line)
        if match:
            installs.append(match.group(1).split(":", 1)[0])
    extra = sorted(set(installs) - {CHROME_PACKAGE})
    if extra:
        raise DisplayPlatformPreparationError(
            "Ubuntu platform-baseline mangler Chrome-afhængigheder; live dependency-install er ikke tilladt: "
            + ", ".join(extra)
        )


def _ensure_exact_chrome(package_path: Path, artifact: dict[str, object]) -> None:
    expected_version = str(artifact["version"])
    expected_arch = str(artifact["architecture"])
    installed = _installed_chrome()
    if not installed or installed[1] != expected_version or installed[2] != expected_arch:
        _simulate_local_deb_install(package_path)
        _run(["/usr/bin/dpkg", "--install", str(package_path)])
    installed = _installed_chrome()
    if not installed or installed[1] != expected_version or installed[2] != expected_arch:
        raise DisplayPlatformPreparationError("Installeret Google Chrome matcher ikke release-lock")
    if not CHROME_EXECUTABLE.exists() or not os.access(CHROME_EXECUTABLE, os.X_OK):
        raise DisplayPlatformPreparationError("Canonical Google Chrome executable mangler eller er ikke executable")


def _replace_section_keys(text: str, section: str, replacements: dict[str, str]) -> str:
    lines = text.splitlines()
    if not any(line.strip() == f"[{section}]" for line in lines):
        lines = [f"[{section}]", *[f"{key}={value}" for key, value in replacements.items()], *lines]
        return "\n".join(lines).rstrip() + "\n"
    out: list[str] = []
    in_section = False
    seen: set[str] = set()
    inserted_missing = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not inserted_missing:
                for key, value in replacements.items():
                    if key not in seen:
                        out.append(f"{key}={value}")
                inserted_missing = True
            in_section = stripped == f"[{section}]"
        if in_section and "=" in line and not stripped.startswith(("#", ";")):
            key = line.split("=", 1)[0].strip()
            if key in replacements:
                if key not in seen:
                    out.append(f"{key}={replacements[key]}")
                    seen.add(key)
                continue
        out.append(line)
    if in_section and not inserted_missing:
        for key, value in replacements.items():
            if key not in seen:
                out.append(f"{key}={value}")
    return "\n".join(out).rstrip() + "\n"


def _prepare_gdm(kiosk_user: str, gdm_config: Path = Path("/etc/gdm3/custom.conf")) -> None:
    if not Path("/usr/sbin/gdm3").exists():
        raise DisplayPlatformPreparationError("GDM3 mangler; Ubuntu graphical platform-baseline er ikke komplet")
    ubuntu_session = Path("/usr/share/wayland-sessions/ubuntu.desktop")
    if not ubuntu_session.is_file():
        raise DisplayPlatformPreparationError("Ubuntu Wayland-session mangler")
    text = gdm_config.read_text(encoding="utf-8") if gdm_config.exists() else "[daemon]\n"
    text = _replace_section_keys(
        text,
        "daemon",
        {
            "AutomaticLoginEnable": "true",
            "AutomaticLogin": kiosk_user,
            "WaylandEnable": "true",
        },
    )
    _atomic_write_text(gdm_config, text)


def _prepare_accounts_service(kiosk_user: str, accounts_root: Path = Path("/var/lib/AccountsService/users")) -> None:
    path = accounts_root / kiosk_user
    text = path.read_text(encoding="utf-8") if path.exists() else "[User]\n"
    text = _replace_section_keys(
        text,
        "User",
        {
            "Session": "ubuntu",
            "XSession": "ubuntu",
            "SystemAccount": "false",
        },
    )
    _atomic_write_text(path, text)


def _gsettings_commands() -> Iterable[tuple[str, str, str]]:
    return (
        ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
        ("org.gnome.desktop.screensaver", "idle-activation-enabled", "false"),
        ("org.gnome.desktop.screensaver", "ubuntu-lock-on-suspend", "false"),
        ("org.gnome.desktop.session", "idle-delay", "uint32 0"),
        ("org.gnome.desktop.lockdown", "disable-lock-screen", "true"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "'nothing'"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-timeout", "0"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type", "'nothing'"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout", "0"),
        ("org.gnome.settings-daemon.plugins.power", "idle-dim", "false"),
        ("org.gnome.desktop.notifications", "show-banners", "false"),
        ("org.gnome.desktop.notifications", "show-in-lock-screen", "false"),
    )


def _prepare_gnome_settings(kiosk_user: str, home: Path) -> None:
    for binary in ("/usr/sbin/runuser", "/usr/bin/dbus-run-session", "/usr/bin/gsettings"):
        if not Path(binary).exists():
            raise DisplayPlatformPreparationError(f"Ubuntu graphical platform-baseline mangler {binary}")
    for schema, key, value in _gsettings_commands():
        _run(
            [
                "/usr/sbin/runuser",
                "-u",
                kiosk_user,
                "--",
                "env",
                f"HOME={home}",
                "/usr/bin/dbus-run-session",
                "--",
                "/usr/bin/gsettings",
                "set",
                schema,
                key,
                value,
            ],
            timeout=30,
        )


def _prepare_graphical_kiosk(kiosk_user: str) -> None:
    try:
        record = pwd.getpwnam(kiosk_user)
    except KeyError as exc:
        raise DisplayPlatformPreparationError(f"Kiosk-bruger findes ikke: {kiosk_user}") from exc
    if record.pw_uid == 0:
        raise DisplayPlatformPreparationError("root må ikke være kiosk-bruger")
    home = Path(record.pw_dir)
    if not home.is_dir() or home.is_symlink() or home.stat().st_uid != record.pw_uid:
        raise DisplayPlatformPreparationError("Kiosk-brugerens home mangler eller har forkert ejerskab")
    _prepare_gdm(kiosk_user)
    _prepare_accounts_service(kiosk_user)
    _prepare_gnome_settings(kiosk_user, home)


def prepare() -> None:
    if os.geteuid() != 0:
        raise DisplayPlatformPreparationError("Display platform preparation kræver root")
    kiosk_user = os.getenv("CLIENTFLOW_KIOSK_USER", "").strip()
    if not kiosk_user:
        raise DisplayPlatformPreparationError("CLIENTFLOW_KIOSK_USER mangler")
    release_root = Path(os.getenv("CLIENTFLOW_RELEASE_ROOT", str(DEFAULT_RELEASE_ROOT)))
    package_path, artifact = _load_chrome_artifact(release_root)
    _verify_deb_metadata(package_path, artifact)
    active_sources = _active_google_repo_files()
    if active_sources:
        raise DisplayPlatformPreparationError(
            "Aktivt Google Chrome APT-repository er parallel update-authority: "
            + ", ".join(str(path) for path in active_sources)
        )
    _preconfigure_google_repo_opt_out()
    if not _repo_opt_out_is_false():
        raise DisplayPlatformPreparationError("Google Chrome repo opt-out kunne ikke etableres")
    _ensure_exact_chrome(package_path, artifact)
    if _active_google_repo_files():
        raise DisplayPlatformPreparationError("Google Chrome-installation etablerede uventet et aktivt APT-repository")
    if not _repo_opt_out_is_false():
        raise DisplayPlatformPreparationError("Google Chrome-installation ændrede repo opt-out")
    _prepare_graphical_kiosk(kiosk_user)


def main() -> int:
    try:
        prepare()
    except DisplayPlatformPreparationError as exc:
        print(f"DISPLAY_PLATFORM_PREPARE_FAILED: {exc}", flush=True)
        return 1
    print("DISPLAY_PLATFORM_PREPARE_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
