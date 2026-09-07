"""Canonical optional kiosk lockdown with reversible legacy-1.1.19 behaviour.

Root-only; the kiosk account is loaded from canonical local identity and is
never accepted from a remote payload.  The normal kiosk/session baseline is a
separate authority and is not rolled back here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
from typing import Any

from .config import ClientIdentity

STATE_PATH = Path(os.getenv("CLIENTFLOW_KIOSK_LOCKDOWN_STATE", "/var/lib/clientflow/kiosk-lockdown/state.json"))
POLKIT_ROOT = Path(os.getenv("CLIENTFLOW_POLKIT_RULES_DIR", "/etc/polkit-1/rules.d"))
SOURCE_DESKTOP_DIRS = (Path("/usr/share/applications"), Path("/var/lib/snapd/desktop/applications"))
SYSTEMCTL = Path("/usr/bin/systemctl")
QUICK_GUARD_UNIT = "clientflow-kiosk-quicksettings-guard.service"
EXTRA_DESKTOP_IDS = (
    "org.gnome.Settings.desktop", "gnome-control-center.desktop", "org.gnome.Nautilus.desktop", "nautilus.desktop",
    "org.gnome.Terminal.desktop", "gnome-terminal.desktop", "org.gnome.Console.desktop", "kgx.desktop", "xterm.desktop", "uxterm.desktop",
    "firefox.desktop", "firefox_firefox.desktop", "org.mozilla.firefox.desktop", "org.gnome.Software.desktop", "gnome-software.desktop",
    "snap-store_ubuntu-software.desktop", "snap-store_snap-store.desktop", "ubuntu-app-center.desktop", "org.gnome.UpdateManager.desktop",
    "update-manager.desktop", "software-properties-gtk.desktop", "org.gnome.SystemMonitor.desktop", "gnome-system-monitor.desktop",
    "org.gnome.DiskUtility.desktop", "gnome-disks.desktop", "org.gnome.Extensions.desktop", "org.gnome.ExtensionsApp.desktop",
    "org.gnome.tweaks.desktop", "gnome-tweaks.desktop", "nm-connection-editor.desktop", "bluetooth-sendto.desktop",
    "system-config-printer.desktop", "org.gnome.TextEditor.desktop", "org.gnome.gedit.desktop", "gedit.desktop",
    "org.gnome.FileRoller.desktop", "file-roller.desktop", "org.gnome.Calculator.desktop", "libreoffice-startcenter.desktop",
    "org.gnome.baobab.desktop", "org.gnome.seahorse.Application.desktop",
)
TARGET_BINARIES = (
    "/usr/bin/gnome-control-center", "/usr/bin/nautilus", "/usr/bin/gnome-terminal", "/usr/bin/kgx", "/usr/bin/console",
    "/usr/bin/xterm", "/usr/bin/uxterm", "/usr/bin/firefox", "/snap/bin/firefox", "/usr/bin/gnome-software",
    "/usr/bin/update-manager", "/usr/bin/software-updater", "/usr/bin/update-notifier", "/usr/bin/software-properties-gtk",
    "/usr/bin/ubuntu-app-center", "/snap/bin/ubuntu-app-center", "/snap/bin/snap-store", "/usr/bin/snap-store",
    "/usr/bin/synaptic", "/usr/bin/gdebi", "/usr/bin/gnome-system-monitor", "/usr/bin/gnome-disks",
    "/usr/bin/gnome-extensions-app", "/usr/bin/gnome-tweaks", "/usr/bin/nm-connection-editor", "/usr/bin/bluetooth-sendto",
    "/usr/bin/system-config-printer", "/usr/bin/gnome-text-editor", "/usr/bin/gedit", "/usr/bin/file-roller", "/usr/bin/baobab",
    "/usr/bin/seahorse", "/usr/bin/dconf-editor",
)
DENIED_PREFIXES = (
    "org.freedesktop.packagekit.", "org.debian.apt.", "org.freedesktop.systemd1.", "org.freedesktop.NetworkManager.",
    "org.freedesktop.udisks2.", "org.freedesktop.accounts.", "org.freedesktop.UPower.", "org.bluez.",
    "net.hadess.PowerProfiles.", "com.ubuntu.", "io.snapcraft.",
)
DENIED_EXACT = (
    "org.freedesktop.login1.power-off", "org.freedesktop.login1.power-off-multiple-sessions",
    "org.freedesktop.login1.reboot", "org.freedesktop.login1.reboot-multiple-sessions",
    "org.freedesktop.login1.suspend", "org.freedesktop.login1.hibernate",
)
OPTIONAL_GSETTINGS = (
    ("org.gnome.desktop.lockdown", "disable-command-line", "true"),
    ("org.gnome.settings-daemon.plugins.media-keys", "terminal", "[]"),
    ("org.gnome.desktop.session", "idle-delay", "uint32 0"),
    ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
    ("org.gnome.desktop.screensaver", "ubuntu-lock-on-suspend", "false"),
    ("org.gnome.shell", "favorite-apps", "[]"),
    ("org.gnome.settings-daemon.plugins.color", "night-light-enabled", "false"),
    ("org.gnome.desktop.interface", "color-scheme", "'default'"),
    ("org.gnome.desktop.notifications", "show-banners", "true"),
    ("org.gnome.desktop.notifications", "show-in-lock-screen", "false"),
    ("org.gnome.shell.extensions.ding", "show-home", "false"),
)

class KioskLockdownError(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int = 30, required: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout, check=False,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if required and completed.returncode != 0:
        raise KioskLockdownError(
            f"Kommando fejlede ({completed.returncode}): {' '.join(command)}\n{(completed.stdout or '')[-2000:]}"
        )
    return completed


def _account():
    identity = ClientIdentity.load()
    try:
        record = pwd.getpwnam(identity.kiosk_user)
    except KeyError as exc:
        raise KioskLockdownError("Canonical kiosk-bruger findes ikke") from exc
    if identity.kiosk_user == "root" or record.pw_uid < 1000:
        raise KioskLockdownError("Afviser lockdown på root/systembruger")
    groups = _run(["/usr/bin/id", "-nG", identity.kiosk_user]).stdout.split()
    if {"sudo", "admin", "wheel"} & set(groups):
        raise KioskLockdownError("Afviser lockdown på admin/sudo-bruger")
    home = Path(record.pw_dir)
    if not home.is_dir() or home.is_symlink() or home.stat().st_uid != record.pw_uid:
        raise KioskLockdownError("Canonical kiosk-home mangler eller har forkert ejerskab")
    return identity.kiosk_user, record, home


def _paths(home: Path):
    state_dir = home / ".local/share/clientflow-lockdown"
    return home / ".local/share/applications", state_dir, state_dir / "desktop-backups", state_dir / "hidden-desktop-entries.txt"


def _allowed(desktop_id: str) -> bool:
    value = desktop_id.lower()
    return "clientflow" in value or "aktiver-clientflow" in value or "activate-clientflow" in value


def _write_state(desired: bool, status_value: str, message: str, kiosk_user: str) -> dict[str, Any]:
    payload = {
        "schema_version": 1, "desired": desired, "status": status_value, "message": message,
        "kiosk_user": kiosk_user, "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_name(f".{STATE_PATH.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_PATH)
    return payload


def status() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, json.JSONDecodeError):
        pass
    kiosk_user, _, _ = _account()
    return {"schema_version": 1, "desired": False, "status": "disabled", "message": "Kiosk lockdown er ikke anvendt", "kiosk_user": kiosk_user, "updated_at": None}


def _write_blocked(app_dir: Path, backup_dir: Path, desktop_id: str, uid: int, gid: int) -> None:
    target = app_dir / desktop_id
    backup = backup_dir / f"{desktop_id}.bak"
    if target.is_file() and "X-ClientFlow-Lockdown=true" not in target.read_text(encoding="utf-8", errors="ignore"):
        shutil.copy2(target, backup)
    target.write_text(
        "[Desktop Entry]\nType=Application\nName=Blocked by ClientFlow kiosk lockdown\n"
        "Hidden=true\nNoDisplay=true\nX-ClientFlow-Lockdown=true\n",
        encoding="utf-8",
    )
    os.chown(target, uid, gid)
    os.chmod(target, 0o644)


def _hide_launchers(home: Path, record) -> None:
    app_dir, state_dir, backup_dir, manifest = _paths(home)
    for path in (app_dir, state_dir, backup_dir):
        path.mkdir(parents=True, exist_ok=True)
    desktop_ids = set(EXTRA_DESKTOP_IDS)
    for source in SOURCE_DESKTOP_DIRS:
        if source.is_dir():
            desktop_ids.update(path.name for path in source.glob("*.desktop"))
    desktop_ids = {value for value in desktop_ids if not _allowed(value)}
    for desktop_id in sorted(desktop_ids):
        _write_blocked(app_dir, backup_dir, desktop_id, record.pw_uid, record.pw_gid)
    manifest.write_text("".join(f"{value}\n" for value in sorted(desktop_ids)), encoding="utf-8")
    for path in (app_dir, state_dir, backup_dir, manifest):
        os.chown(path, record.pw_uid, record.pw_gid)


def _restore_launchers(home: Path, record) -> None:
    app_dir, state_dir, backup_dir, manifest = _paths(home)
    desktop_ids: list[str] = []
    try:
        desktop_ids.extend(value.strip() for value in manifest.read_text(encoding="utf-8").splitlines() if value.strip())
    except OSError:
        pass
    if app_dir.is_dir():
        for path in app_dir.glob("*.desktop"):
            try:
                if "X-ClientFlow-Lockdown=true" in path.read_text(encoding="utf-8", errors="ignore"):
                    desktop_ids.append(path.name)
            except OSError:
                pass
    for desktop_id in sorted(set(desktop_ids)):
        target = app_dir / desktop_id
        backup = backup_dir / f"{desktop_id}.bak"
        if backup.is_file():
            shutil.copy2(backup, target)
            os.chown(target, record.pw_uid, record.pw_gid)
            backup.unlink(missing_ok=True)
        else:
            try:
                if target.is_file() and "X-ClientFlow-Lockdown=true" in target.read_text(encoding="utf-8", errors="ignore"):
                    target.unlink()
            except OSError:
                pass
    manifest.unlink(missing_ok=True)
    for path in (backup_dir, state_dir):
        try:
            path.rmdir()
        except OSError:
            pass


def _apply_acl(kiosk_user: str, enabled: bool) -> None:
    if not Path("/usr/bin/setfacl").is_file():
        raise KioskLockdownError("acl/setfacl mangler")
    for raw in TARGET_BINARIES:
        if not Path(raw).exists():
            continue
        if enabled:
            _run(["/usr/bin/setfacl", "-m", f"u:{kiosk_user}:---", raw])
        else:
            _run(["/usr/bin/setfacl", "-x", f"u:{kiosk_user}", raw])


def _apply_polkit(kiosk_user: str, enabled: bool) -> None:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in kiosk_user)
    path = POLKIT_ROOT / f"49-clientflow-kiosk-lockdown-{safe}.rules"
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    user_literal = json.dumps(kiosk_user)
    prefixes = json.dumps(list(DENIED_PREFIXES))
    exact = json.dumps(list(DENIED_EXACT))
    text = (
        "// ClientFlow optional kiosk lockdown. Generated; remove via rollback.\n"
        "polkit.addRule(function(action, subject) {\n"
        f"  if (subject.user !== {user_literal}) return polkit.Result.NOT_HANDLED;\n"
        f"  var id=action.id||\"\"; var prefixes={prefixes}; var exact={exact};\n"
        "  for (var i=0;i<prefixes.length;i++) if (id.indexOf(prefixes[i])===0) return polkit.Result.NO;\n"
        "  for (var j=0;j<exact.length;j++) if (id===exact[j]) return polkit.Result.NO;\n"
        "  if (id.indexOf(\"package\")!==-1 || id.indexOf(\"software\")!==-1 || id.indexOf(\"update\")!==-1) return polkit.Result.NO;\n"
        "  return polkit.Result.NOT_HANDLED;\n});\n"
    )
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o644)


def _apply_gsettings(kiosk_user: str, record, enabled: bool) -> None:
    base = [
        "/usr/sbin/runuser", "-u", kiosk_user, "--", "env", f"HOME={record.pw_dir}",
        f"XDG_RUNTIME_DIR=/run/user/{record.pw_uid}", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{record.pw_uid}/bus",
        "/usr/bin/gsettings",
    ]
    for schema, key, value in OPTIONAL_GSETTINGS:
        command = [*base, "set", schema, key, value] if enabled else [*base, "reset", schema, key]
        _run(command, required=False)


def _set_quick_guard_running(enabled: bool) -> None:
    if not SYSTEMCTL.is_file():
        raise KioskLockdownError("systemctl mangler til kiosk quick-settings guard")
    verb = "restart" if enabled else "stop"
    _run([str(SYSTEMCTL), verb, QUICK_GUARD_UNIT], timeout=30, required=enabled)


def apply() -> dict[str, Any]:
    kiosk_user, record, home = _account()
    _write_state(True, "applying", "Kiosk lockdown anvendes", kiosk_user)
    _hide_launchers(home, record)
    _apply_acl(kiosk_user, True)
    _apply_polkit(kiosk_user, True)
    _apply_gsettings(kiosk_user, record, True)
    # The optional quick-settings guard is part of the applied contract.
    # Do not publish terminal applied state until systemd accepted the guard.
    _set_quick_guard_running(True)
    return _write_state(True, "applied", "Kiosk lockdown aktiv på kiosk-brugeren", kiosk_user)


def rollback() -> dict[str, Any]:
    kiosk_user, record, home = _account()
    _write_state(False, "rolling_back", "Kiosk lockdown rulles tilbage", kiosk_user)
    _set_quick_guard_running(False)
    _restore_launchers(home, record)
    _apply_acl(kiosk_user, False)
    _apply_polkit(kiosk_user, False)
    _apply_gsettings(kiosk_user, record, False)
    return _write_state(False, "disabled", "Kiosk lockdown slået fra på kiosk-brugeren", kiosk_user)


def main() -> int:
    if os.geteuid() != 0:
        print("CLIENTFLOW_KIOSK_LOCKDOWN_FAILED: kræver root", flush=True)
        return 1
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").strip().lower()
    try:
        if action == "apply":
            result = apply()
        elif action == "rollback":
            result = rollback()
        elif action == "status":
            result = status()
        else:
            raise KioskLockdownError("Brug apply|rollback|status")
    except (OSError, ValueError, KioskLockdownError) as exc:
        print(f"CLIENTFLOW_KIOSK_LOCKDOWN_FAILED: {exc}", flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
