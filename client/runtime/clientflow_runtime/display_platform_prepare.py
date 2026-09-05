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
RFKILL_EXECUTABLE = Path("/usr/sbin/rfkill")
LOGIND_KIOSK_DROPIN = Path("/etc/systemd/logind.conf.d/90-clientflow-kiosk.conf")
POLKIT_KIOSK_RULE = Path("/etc/polkit-1/rules.d/90-clientflow-kiosk.rules")
SLEEP_TARGETS = ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target")
KIOSK_DISABLED_AUTOSTARTS = (
    "update-notifier.desktop",
    "update-manager.desktop",
    "org.gnome.Software.desktop",
    "gnome-software-service.desktop",
    "snap-store_ubuntu-software.desktop",
    "snap-store.desktop",
    "apport-gtk.desktop",
    "ubuntu-report-on-upgrade.desktop",
    "update-notifier-crash.desktop",
    "software-properties-gtk.desktop",
)
KIOSK_BLOCKED_DESKTOP_IDS = (
    "org.gnome.Settings.desktop",
    "gnome-control-center.desktop",
    "org.gnome.Nautilus.desktop",
    "nautilus.desktop",
    "org.gnome.Terminal.desktop",
    "gnome-terminal.desktop",
    "org.gnome.Console.desktop",
    "kgx.desktop",
    "firefox.desktop",
    "firefox_firefox.desktop",
    "org.mozilla.firefox.desktop",
    "org.gnome.Software.desktop",
    "gnome-software.desktop",
    "snap-store_ubuntu-software.desktop",
    "snap-store_snap-store.desktop",
    "ubuntu-app-center.desktop",
    "org.gnome.UpdateManager.desktop",
    "update-manager.desktop",
    "software-properties-gtk.desktop",
    "org.gnome.SystemMonitor.desktop",
    "gnome-system-monitor.desktop",
    "org.gnome.DiskUtility.desktop",
    "gnome-disks.desktop",
    "nm-connection-editor.desktop",
    "bluetooth-sendto.desktop",
    "system-config-printer.desktop",
)
KIOSK_BLOCKED_BINARIES = (
    "/usr/bin/gnome-control-center",
    "/usr/bin/gnome-terminal",
    "/usr/bin/kgx",
    "/usr/bin/firefox",
    "/snap/bin/firefox",
    "/usr/bin/gnome-software",
    "/usr/bin/update-manager",
    "/usr/bin/software-updater",
    "/usr/bin/update-notifier",
    "/usr/bin/software-properties-gtk",
    "/usr/bin/ubuntu-app-center",
    "/snap/bin/ubuntu-app-center",
    "/snap/bin/snap-store",
    "/usr/bin/snap-store",
    "/usr/bin/gnome-system-monitor",
    "/usr/bin/gnome-disks",
    "/usr/bin/nm-connection-editor",
    "/usr/bin/bluetooth-sendto",
    "/usr/bin/system-config-printer",
)


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
    output = _run(
        [
            "/usr/bin/apt-get",
            "-o",
            "DPkg::Lock::Timeout=120",
            "-s",
            "--no-install-recommends",
            "install",
            str(package_path),
        ]
    )
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
        # Ubuntu 26.04 APT can lose the absolute local-archive pathname when
        # --no-download is combined with a direct .deb install. Dependency
        # resolution is therefore proven non-mutating above, while dpkg owns
        # installation of the exact release-verified local archive bytes.
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


def _prepare_gdm(kiosk_user: str, gdm_config: Path = Path("/etc/gdm3/custom.conf")) -> bool:
    if not Path("/usr/sbin/gdm3").exists():
        raise DisplayPlatformPreparationError("GDM3 mangler; Ubuntu graphical platform-baseline er ikke komplet")
    ubuntu_session = Path("/usr/share/wayland-sessions/ubuntu.desktop")
    if not ubuntu_session.is_file():
        raise DisplayPlatformPreparationError("Ubuntu Wayland-session mangler")
    original = gdm_config.read_text(encoding="utf-8") if gdm_config.exists() else "[daemon]\n"
    text = _replace_section_keys(
        original,
        "daemon",
        {
            "AutomaticLoginEnable": "true",
            "AutomaticLogin": kiosk_user,
            "WaylandEnable": "true",
        },
    )
    if text == original and gdm_config.exists():
        return False
    _atomic_write_text(gdm_config, text)
    return True


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
    # Port the physically proven legacy Golden kiosk behaviour into the V2
    # Display/platform authority.  These settings are scoped to the kiosk user;
    # cfadmin/root and the frozen remote-management domains are untouched.
    return (
        ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
        ("org.gnome.desktop.screensaver", "idle-activation-enabled", "false"),
        ("org.gnome.desktop.screensaver", "ubuntu-lock-on-suspend", "false"),
        ("org.gnome.desktop.session", "idle-delay", "uint32 0"),
        ("org.gnome.desktop.lockdown", "disable-lock-screen", "true"),
        ("org.gnome.desktop.lockdown", "disable-command-line", "true"),
        # Preserve the legacy technician escape hatch: the kiosk user may log
        # out/switch user so cfadmin can be selected at GDM.
        ("org.gnome.desktop.lockdown", "disable-user-switching", "false"),
        ("org.gnome.desktop.lockdown", "disable-log-out", "false"),
        ("org.gnome.settings-daemon.plugins.media-keys", "terminal", "[]"),
        ("org.gnome.shell", "favorite-apps", "[]"),
        ("org.gnome.settings-daemon.plugins.color", "night-light-enabled", "false"),
        ("org.gnome.desktop.interface", "color-scheme", "'default'"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "'nothing'"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-timeout", "0"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type", "'nothing'"),
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout", "0"),
        ("org.gnome.settings-daemon.plugins.power", "idle-dim", "false"),
        ("org.gnome.settings-daemon.plugins.power", "power-button-action", "'nothing'"),
        ("org.gnome.desktop.notifications", "show-banners", "false"),
        ("org.gnome.desktop.notifications", "show-in-lock-screen", "false"),
        # Legacy 1.1.19 desktop contract: DING may remain present, but the
        # virtual Home/Trash icons are hidden. Nautilus itself must stay
        # executable because DING uses it internally on Ubuntu 26.04.
        ("org.gnome.shell.extensions.ding", "show-home", "false"),
        ("org.gnome.shell.extensions.ding", "show-trash", "false"),
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


def _prepare_kiosk_autostarts(home: Path, *, uid: int, gid: int) -> None:
    """Suppress stock Ubuntu desktop popups for the kiosk user only."""
    autostart = home / ".config/autostart"
    autostart.mkdir(parents=True, exist_ok=True)
    os.chown(autostart, uid, gid)
    for name in KIOSK_DISABLED_AUTOSTARTS:
        path = autostart / name
        _atomic_write_text(
            path,
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name=ClientFlow disabled {name}\n"
            "Hidden=true\n"
            "X-GNOME-Autostart-enabled=false\n"
            "NoDisplay=true\n",
            mode=0o644,
        )
        os.chown(path, uid, gid)


def _prepare_kiosk_application_lockdown(home: Path, *, uid: int, gid: int) -> None:
    """Hide local admin/desktop applications from the kiosk user only."""
    applications = home / ".local/share/applications"
    applications.mkdir(parents=True, exist_ok=True)
    os.chown(applications, uid, gid)
    for desktop_id in KIOSK_BLOCKED_DESKTOP_IDS:
        path = applications / desktop_id
        _atomic_write_text(
            path,
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name=ClientFlow blocked {desktop_id}\n"
            "Hidden=true\n"
            "NoDisplay=true\n"
            "X-ClientFlow-Kiosk-Lockdown=true\n",
            mode=0o644,
        )
        os.chown(path, uid, gid)


def _prepare_kiosk_binary_acl(kiosk_user: str) -> None:
    """Deny direct execution of local administration apps for the kiosk user."""
    for raw in KIOSK_BLOCKED_BINARIES:
        path = Path(raw)
        if path.exists() and not path.is_symlink():
            _run(["/usr/bin/setfacl", "-m", f"u:{kiosk_user}:---", str(path)], timeout=30)


def _prepare_kiosk_polkit_policy(kiosk_user: str, path: Path | None = None) -> None:
    """Deny kiosk-user privilege elevation while preserving logout/user switch."""
    target = path or POLKIT_KIOSK_RULE
    target.parent.mkdir(parents=True, exist_ok=True)
    user_literal = json.dumps(kiosk_user)
    text = f'''// ClientFlow V2 kiosk lockdown. Generated by display platform preparation.
polkit.addRule(function(action, subject) {{
  if (subject.user !== {user_literal}) {{
    return polkit.Result.NOT_HANDLED;
  }}
  var id = action.id || "";
  var deniedPrefixes = [
    "org.freedesktop.packagekit.",
    "org.debian.apt.",
    "org.freedesktop.systemd1.",
    "org.freedesktop.NetworkManager.",
    "org.freedesktop.udisks2.",
    "org.freedesktop.accounts.",
    "org.freedesktop.UPower.",
    "org.bluez.",
    "net.hadess.PowerProfiles.",
    "com.ubuntu.",
    "io.snapcraft."
  ];
  var deniedExact = [
    "org.freedesktop.login1.power-off",
    "org.freedesktop.login1.power-off-multiple-sessions",
    "org.freedesktop.login1.reboot",
    "org.freedesktop.login1.reboot-multiple-sessions",
    "org.freedesktop.login1.suspend",
    "org.freedesktop.login1.hibernate"
  ];
  for (var i = 0; i < deniedPrefixes.length; i++) {{
    if (id.indexOf(deniedPrefixes[i]) === 0) return polkit.Result.NO;
  }}
  for (var j = 0; j < deniedExact.length; j++) {{
    if (id === deniedExact[j]) return polkit.Result.NO;
  }}
  return polkit.Result.NOT_HANDLED;
}});
'''
    _atomic_write_text(target, text, mode=0o644)


def _prepare_logind_kiosk_policy(path: Path | None = None) -> None:
    target = path or LOGIND_KIOSK_DROPIN
    _atomic_write_text(
        target,
        "[Login]\n"
        "IdleAction=ignore\n"
        "IdleActionSec=0\n"
        "HandlePowerKey=ignore\n"
        "HandleSuspendKey=ignore\n"
        "HandleHibernateKey=ignore\n"
        "HandleLidSwitch=ignore\n"
        "HandleLidSwitchExternalPower=ignore\n"
        "HandleLidSwitchDocked=ignore\n",
        mode=0o644,
    )


def _prepare_system_kiosk_policy() -> None:
    if not RFKILL_EXECUTABLE.is_file() or not os.access(RFKILL_EXECUTABLE, os.X_OK):
        raise DisplayPlatformPreparationError("Ubuntu kiosk-baseline mangler /usr/sbin/rfkill")
    _run([str(RFKILL_EXECUTABLE), "block", "bluetooth"], timeout=30)
    _run(["/usr/bin/systemctl", "mask", *SLEEP_TARGETS], timeout=30)
    _prepare_logind_kiosk_policy()


def _prepare_graphical_kiosk(kiosk_user: str) -> bool:
    try:
        record = pwd.getpwnam(kiosk_user)
    except KeyError as exc:
        raise DisplayPlatformPreparationError(f"Kiosk-bruger findes ikke: {kiosk_user}") from exc
    if record.pw_uid == 0:
        raise DisplayPlatformPreparationError("root må ikke være kiosk-bruger")
    home = Path(record.pw_dir)
    if not home.is_dir() or home.is_symlink() or home.stat().st_uid != record.pw_uid:
        raise DisplayPlatformPreparationError("Kiosk-brugerens home mangler eller har forkert ejerskab")
    gdm_changed = _prepare_gdm(kiosk_user)
    _prepare_accounts_service(kiosk_user)
    _prepare_gnome_settings(kiosk_user, home)
    _prepare_kiosk_autostarts(home, uid=record.pw_uid, gid=record.pw_gid)
    _prepare_kiosk_application_lockdown(home, uid=record.pw_uid, gid=record.pw_gid)
    _prepare_kiosk_binary_acl(kiosk_user)
    _prepare_kiosk_polkit_policy(kiosk_user)
    return gdm_changed


def prepare() -> None:
    if os.geteuid() != 0:
        raise DisplayPlatformPreparationError("Display platform preparation kræver root")
    # clientflow-display-input-wake.service receives this standard Linux input
    # group only for physical keyboard/mouse event devices. Make the platform
    # prerequisite deterministic on minimal Ubuntu installations.
    _run(["/usr/sbin/groupadd", "--system", "--force", "input"], timeout=30)
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
    # Materialize the canonical GDM/autologin configuration without restarting
    # the display manager inside the activation transaction. Restarting gdm3
    # would terminate the interactive kiosk session that may be running the
    # installer itself. The configuration becomes authoritative on the next
    # controlled reboot, while the current approved kiosk session can complete
    # activation and runtime health checks without self-termination.
    _prepare_graphical_kiosk(kiosk_user)
    _prepare_system_kiosk_policy()


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
