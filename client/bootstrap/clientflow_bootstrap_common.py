from __future__ import annotations

import getpass
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import termios
import time
import tty
import urllib.error
import urllib.request
import uuid

BACKEND_URL = "https://api.display.planiq.dk"
BOOTSTRAP_ROOT = Path("/var/lib/clientflow-bootstrap")
FACTORY_STATE = BOOTSTRAP_ROOT / "factory-state.json"
USB_STATE = BOOTSTRAP_ROOT / "usb-state.json"
PERSISTENT_ROOT = Path("/usr/local/lib/clientflow-bootstrap")
PLANIQ_DISPLAY_DESKTOP_ICON = PERSISTENT_ROOT / "planiq-display-mark.png"
SYSTEMCTL = Path("/usr/bin/systemctl")
NMCLI = Path("/usr/bin/nmcli")
NETPLAN = Path("/usr/sbin/netplan")
IP = Path("/usr/sbin/ip")
RUNUSER = Path("/usr/sbin/runuser")
XDG_USER_DIR = Path("/usr/bin/xdg-user-dir")
GIO = Path("/usr/bin/gio")
VISUDO = Path("/usr/sbin/visudo")
GDM_CONFIG = Path("/etc/gdm3/custom.conf")
ACCOUNTS_SERVICE_ROOT = Path("/var/lib/AccountsService/users")
FACTORY_ACTIVATION_SUDOERS = Path("/etc/sudoers.d/clientflow-factory-activation")
KIOSK_USER = "clientflow-kiosk"
KIOSK_DISPLAY_NAME = "ClientFlow kiosk user"
ADMIN_USER = "cfadmin"
ADMIN_DISPLAY_NAME = "ClientFlow local admin"
_PRIVILEGED_KIOSK_GROUPS = ("sudo", "adm", "admin", "wheel", "lpadmin", "lxd")
_FACTORY_DISABLED_AUTOSTARTS = (
    "update-notifier.desktop",
    "ubuntu-advantage-notification.desktop",
    "update-manager.desktop",
    "org.gnome.Software.desktop",
    "gnome-software-service.desktop",
    "snap-store_ubuntu-software.desktop",
    "snap-store.desktop",
    "apport-gtk.desktop",
    "ubuntu-report-on-upgrade.desktop",
    "update-notifier-crash.desktop",
    "software-properties-gtk.desktop",
    "firefox.desktop",
)
MAX_JSON_BYTES = 128 * 1024
_ALLOWED_NETWORK_TYPES = {"wifi", "802-11-wireless", "ethernet", "802-3-ethernet"}
_FORGET_NETWORK_TYPES = {"wifi", "802-11-wireless", "ethernet", "802-3-ethernet", "gsm", "cdma", "vpn", "wireguard"}
_NETPLAN_FORGET_KEYS = ("network.ethernets", "network.wifis", "network.modems", "network.tunnels", "network.nm-devices")
_NETWORKMANAGER_GENERATED_ROOT = Path("/run/NetworkManager/system-connections")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CF_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


class BootstrapError(RuntimeError):
    pass


def line() -> None:
    print("=" * 90)


def banner(text: str) -> None:
    print()
    line()
    print(f"CLIENTFLOW INSTALLATION · {text}")
    line()


def phase(text: str) -> None:
    print()
    line()
    print(f"[FASE] {text}")
    line()


def ok(text: str) -> None:
    print(f"[OK] {text}")


def warn(text: str) -> None:
    print(f"[ADVARSEL] {text}")


def fail(text: str) -> None:
    print(f"[FEJL] {text}", file=sys.stderr)


def require_root() -> None:
    if os.geteuid() != 0:
        raise BootstrapError("Kør ClientFlow-klargøringen med administratorrettigheder.")



def _ensure_root_directory(path: Path, *, mode: int) -> None:
    try:
        meta = path.lstat()
    except FileNotFoundError:
        path.mkdir(parents=False, mode=mode)
        os.chown(path, 0, 0)
        os.chmod(path, mode)
        meta = path.lstat()
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
        raise BootstrapError(f"ClientFlow root-katalog er ugyldigt: {path}")
    if meta.st_uid != 0:
        raise BootstrapError(f"ClientFlow root-katalog er ikke root-owned: {path}")
    if meta.st_mode & 0o022:
        raise BootstrapError(f"ClientFlow root-katalog er skrivbart for group/other: {path}")
    os.chmod(path, mode)


def _write_user_file_no_follow(path: Path, content: str, *, user: str, mode: int) -> None:
    account = pwd.getpwnam(validate_local_user(user))
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except IsADirectoryError as exc:
        raise BootstrapError(f"Desktop-målet er et katalog og afvises: {path}") from exc
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise BootstrapError(f"Desktop-målet ændrede sig under sikker oprettelse: {path}") from exc
    try:
        os.fchown(fd, account.pw_uid, account.pw_gid)
        os.fchmod(fd, mode)
        payload = content.encode("utf-8")
        with os.fdopen(fd, "wb", closefd=True) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            fd = -1
    finally:
        if fd >= 0:
            os.close(fd)


def _atomic_root_file(path: Path, content: str, *, mode: int) -> None:
    parent = path.parent
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(parent))
    temporary = Path(temporary_name)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, mode)
        payload = content.encode("utf-8")
        with os.fdopen(fd, "wb", closefd=True) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_json_read(path: Path) -> dict[str, object] | None:
    try:
        meta = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
        raise BootstrapError(f"Ugyldig ClientFlow bootstrap-state: {path}")
    if meta.st_uid != 0 or meta.st_mode & 0o077:
        raise BootstrapError(f"Usikker ownership/permissions på ClientFlow bootstrap-state: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        raise BootstrapError("ClientFlow bootstrap-state er for stor")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise BootstrapError("ClientFlow bootstrap-state har ugyldigt format")
    return data


def _atomic_root_json(path: Path, data: dict[str, object]) -> None:
    if path.parent == BOOTSTRAP_ROOT:
        _ensure_root_directory(BOOTSTRAP_ROOT, mode=0o700)
    else:
        raise BootstrapError(f"Uventet bootstrap-state katalog: {path.parent}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with os.fdopen(fd, "wb", closefd=True) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def load_factory_state() -> dict[str, object] | None:
    return _safe_json_read(FACTORY_STATE)


def write_factory_state(*, client_name: str, operator_user: str, handoff_ready: bool = False) -> None:
    _atomic_root_json(
        FACTORY_STATE,
        {
            "schema_version": 2,
            "client_name": normalize_client_name(client_name),
            "operator_user": validate_local_user(operator_user),
            "kiosk_user": KIOSK_USER,
            "admin_user": ADMIN_USER,
            "handoff_ready": bool(handoff_ready),
        },
    )



def _run_account_command(command: list[str], *, input_text: str | None = None) -> None:
    result = subprocess.run(
        command,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        raise BootstrapError(
            f"Kommando fejlede ({result.returncode}): {' '.join(command)}\n{(result.stdout or '')[-2000:]}"
        )


def _account_groups(user: str) -> set[str]:
    account = pwd.getpwnam(user)
    names: set[str] = set()
    for gid in os.getgrouplist(user, account.pw_gid):
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            continue
    return names


def _remove_group_membership(user: str, group: str) -> None:
    try:
        members = grp.getgrnam(group).gr_mem
    except KeyError:
        return
    if user not in members:
        return
    result = subprocess.run(
        ["/usr/bin/gpasswd", "--delete", user, group],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 3}:
        raise BootstrapError(f"Kunne ikke fjerne {user} fra gruppen {group}")


def _ensure_factory_user(name: str, *, comment: str) -> None:
    try:
        pwd.getpwnam(name)
    except KeyError:
        _run_account_command([
            "/usr/sbin/useradd",
            "--create-home",
            "--user-group",
            "--shell",
            "/bin/bash",
            "--comment",
            comment,
            name,
        ])
    else:
        _run_account_command(["/usr/sbin/usermod", "--shell", "/bin/bash", "--comment", comment, name])


def _prompt_admin_password() -> str:
    print("Adminbrugeren oprettes altid som: cfadmin")
    print("Password vises ikke, gemmes ikke i ClientFlow-state og skrives ikke i loggen.")
    while True:
        first = getpass.getpass("Nyt password til cfadmin: ")
        second = getpass.getpass("Gentag password til cfadmin: ")
        if first != second:
            warn("De to cfadmin-passwords er ikke ens. Prøv igen.")
            continue
        if len(first) < 8:
            warn("cfadmin-password skal være mindst 8 tegn. Prøv igen.")
            continue
        if any(ch in first for ch in ("\n", "\r", ":")):
            warn("cfadmin-password indeholder ugyldige tegn. Prøv igen.")
            continue
        return first


def validate_factory_human_accounts() -> None:
    try:
        kiosk = pwd.getpwnam(KIOSK_USER)
        admin = pwd.getpwnam(ADMIN_USER)
    except KeyError as exc:
        raise BootstrapError(f"Factory-konto mangler: {exc.args[0]}") from exc
    if kiosk.pw_uid < 1000 or kiosk.pw_uid == 0 or admin.pw_uid < 1000 or admin.pw_uid == 0:
        raise BootstrapError("Kiosk/admin skal være normale lokale brugere")
    if kiosk.pw_dir != f"/home/{KIOSK_USER}" or admin.pw_dir != f"/home/{ADMIN_USER}":
        raise BootstrapError("Kiosk/admin home matcher ikke factory-kontrakten")
    if kiosk.pw_shell != "/bin/bash" or admin.pw_shell != "/bin/bash":
        raise BootstrapError("Kiosk/admin shell matcher ikke factory-kontrakten")
    privileged = _account_groups(KIOSK_USER).intersection(_PRIVILEGED_KIOSK_GROUPS)
    if privileged:
        raise BootstrapError(f"Kiosk-brugeren har privilegerede grupper: {', '.join(sorted(privileged))}")
    if "sudo" not in _account_groups(ADMIN_USER):
        raise BootstrapError("cfadmin mangler sudo-gruppen")
    kiosk_status = subprocess.run(
        ["/usr/bin/passwd", "--status", KIOSK_USER],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if kiosk_status.returncode != 0 or len(kiosk_status.stdout.split()) < 2 or kiosk_status.stdout.split()[1] == "L":
        raise BootstrapError("Kiosk-brugeren er låst og kan ikke bruges til GDM autologin")
    admin_status = subprocess.run(
        ["/usr/bin/passwd", "--status", ADMIN_USER],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if admin_status.returncode != 0 or len(admin_status.stdout.split()) < 2 or admin_status.stdout.split()[1] != "P":
        raise BootstrapError("cfadmin mangler et aktivt password")


def _ubuntu_version_id(os_release: Path = Path("/etc/os-release")) -> str:
    try:
        lines = os_release.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BootstrapError("Ubuntu VERSION_ID kunne ikke læses") from exc
    for line in lines:
        if line.startswith("VERSION_ID="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if re.fullmatch(r"[0-9]{2}\.[0-9]{2}", value):
                return value
            break
    raise BootstrapError("Ubuntu VERSION_ID er ugyldig")


def _ensure_user_owned_directory(path: Path, *, user: str, mode: int = 0o700) -> None:
    account = pwd.getpwnam(validate_local_user(user))
    try:
        meta = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=mode)
        os.chown(path, account.pw_uid, account.pw_gid)
        os.chmod(path, mode)
        meta = path.lstat()
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
        raise BootstrapError(f"GNOME onboarding-katalog er ugyldigt: {path}")
    if meta.st_uid != account.pw_uid or meta.st_gid != account.pw_gid:
        raise BootstrapError(f"GNOME onboarding-katalog har forkert ejerskab: {path}")
    os.chmod(path, mode)


def _gnome_initial_setup_marker_paths(
    user: str,
    *,
    os_release: Path = Path("/etc/os-release"),
) -> tuple[Path, Path]:
    account = pwd.getpwnam(validate_local_user(user))
    home = Path(account.pw_dir)
    try:
        meta = home.lstat()
    except FileNotFoundError as exc:
        raise BootstrapError(f"Home mangler for {user}: {home}") from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
        raise BootstrapError(f"Home er ugyldigt for {user}: {home}")
    if meta.st_uid != account.pw_uid:
        raise BootstrapError(f"Home har forkert ejerskab for {user}: {home}")
    config_root = home / ".config"
    upgrade_root = config_root / "gnome-initial-setup"
    return (
        config_root / "gnome-initial-setup-done",
        upgrade_root / f"upgrade-{_ubuntu_version_id(os_release)}-done",
    )


def prepare_factory_gnome_initial_setup_markers(
    user: str,
    *,
    os_release: Path = Path("/etc/os-release"),
) -> None:
    account = pwd.getpwnam(validate_local_user(user))
    home = Path(account.pw_dir)
    first, upgrade = _gnome_initial_setup_marker_paths(user, os_release=os_release)
    _ensure_user_owned_directory(home / ".config", user=user)
    _ensure_user_owned_directory(home / ".config/gnome-initial-setup", user=user)
    _write_user_file_no_follow(first, "yes\n", user=user, mode=0o600)
    _write_user_file_no_follow(upgrade, "yes\n", user=user, mode=0o600)


def validate_factory_gnome_initial_setup_markers(
    user: str,
    *,
    os_release: Path = Path("/etc/os-release"),
) -> None:
    account = pwd.getpwnam(validate_local_user(user))
    for marker in _gnome_initial_setup_marker_paths(user, os_release=os_release):
        try:
            meta = marker.lstat()
        except FileNotFoundError as exc:
            raise BootstrapError(f"GNOME onboarding-marker mangler for {user}: {marker}") from exc
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
            raise BootstrapError(f"GNOME onboarding-marker er ugyldig for {user}: {marker}")
        if meta.st_uid != account.pw_uid or meta.st_gid != account.pw_gid:
            raise BootstrapError(f"GNOME onboarding-marker har forkert ejerskab for {user}: {marker}")
        if stat.S_IMODE(meta.st_mode) != 0o600:
            raise BootstrapError(f"GNOME onboarding-marker har forkert mode for {user}: {marker}")
        try:
            value = marker.read_text(encoding="utf-8")
        except OSError as exc:
            raise BootstrapError(f"GNOME onboarding-marker kan ikke læses for {user}: {marker}") from exc
        if value != "yes\n":
            raise BootstrapError(f"GNOME onboarding-marker har ugyldigt indhold for {user}: {marker}")


def _factory_disabled_autostart_content(name: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name=ClientFlow disabled {name}\n"
        "Hidden=true\n"
        "X-GNOME-Autostart-enabled=false\n"
        "NoDisplay=true\n"
    )


def prepare_factory_popup_autostarts(user: str) -> None:
    """Suppress known stock Ubuntu update/crash/report popups before first login."""
    account = pwd.getpwnam(validate_local_user(user))
    home = Path(account.pw_dir)
    _ensure_user_owned_directory(home / ".config", user=user)
    autostart = home / ".config/autostart"
    _ensure_user_owned_directory(autostart, user=user)
    for name in _FACTORY_DISABLED_AUTOSTARTS:
        _write_user_file_no_follow(
            autostart / name,
            _factory_disabled_autostart_content(name),
            user=user,
            mode=0o644,
        )


def validate_factory_popup_autostarts(user: str) -> None:
    account = pwd.getpwnam(validate_local_user(user))
    autostart = Path(account.pw_dir) / ".config/autostart"
    try:
        directory_meta = autostart.lstat()
    except FileNotFoundError as exc:
        raise BootstrapError(f"Ubuntu popup-autostart katalog mangler for {user}: {autostart}") from exc
    if stat.S_ISLNK(directory_meta.st_mode) or not stat.S_ISDIR(directory_meta.st_mode):
        raise BootstrapError(f"Ubuntu popup-autostart katalog er ugyldigt for {user}: {autostart}")
    if directory_meta.st_uid != account.pw_uid or directory_meta.st_gid != account.pw_gid:
        raise BootstrapError(f"Ubuntu popup-autostart katalog har forkert ejerskab for {user}: {autostart}")
    if stat.S_IMODE(directory_meta.st_mode) != 0o700:
        raise BootstrapError(f"Ubuntu popup-autostart katalog har forkert mode for {user}: {autostart}")
    for name in _FACTORY_DISABLED_AUTOSTARTS:
        path = autostart / name
        try:
            meta = path.lstat()
        except FileNotFoundError as exc:
            raise BootstrapError(f"Ubuntu popup-autostart override mangler for {user}: {path}") from exc
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
            raise BootstrapError(f"Ubuntu popup-autostart override er ugyldig for {user}: {path}")
        if meta.st_uid != account.pw_uid or meta.st_gid != account.pw_gid:
            raise BootstrapError(f"Ubuntu popup-autostart override har forkert ejerskab for {user}: {path}")
        if stat.S_IMODE(meta.st_mode) != 0o644:
            raise BootstrapError(f"Ubuntu popup-autostart override har forkert mode for {user}: {path}")
        try:
            value = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BootstrapError(f"Ubuntu popup-autostart override kan ikke læses for {user}: {path}") from exc
        if value != _factory_disabled_autostart_content(name):
            raise BootstrapError(f"Ubuntu popup-autostart override har ugyldigt indhold for {user}: {path}")


def provision_factory_human_accounts() -> None:
    require_root()
    password = _prompt_admin_password()
    _ensure_factory_user(KIOSK_USER, comment=KIOSK_DISPLAY_NAME)
    _ensure_factory_user(ADMIN_USER, comment=ADMIN_DISPLAY_NAME)
    for group in _PRIVILEGED_KIOSK_GROUPS:
        _remove_group_membership(KIOSK_USER, group)
    _run_account_command(["/usr/bin/passwd", "--delete", KIOSK_USER])
    _run_account_command(["/usr/sbin/usermod", "--unlock", KIOSK_USER])
    try:
        grp.getgrnam("sudo")
    except KeyError:
        _run_account_command(["/usr/sbin/groupadd", "--force", "sudo"])
    _run_account_command(["/usr/sbin/usermod", "--append", "--groups", "sudo", ADMIN_USER])
    try:
        _run_account_command(["/usr/sbin/chpasswd"], input_text=f"{ADMIN_USER}:{password}\n")
    finally:
        password = ""
    validate_factory_human_accounts()
    for username in (KIOSK_USER, ADMIN_USER):
        prepare_factory_gnome_initial_setup_markers(username)
        prepare_factory_popup_autostarts(username)
    ok(
        "cfadmin og clientflow-kiosk er oprettet og valideret; kiosk har ingen privilegerede grupper, "
        "GNOME first-login/upgrade onboarding er markeret færdig, og kendte Ubuntu update/crash/report "
        "popup-autostarts er deaktiveret før første login for begge konti."
    )


def _replace_ini_section_keys(text: str, section: str, replacements: dict[str, str]) -> str:
    if f"[{section}]" not in text:
        text = f"[{section}]\n" + text
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    seen: set[str] = set()
    inserted_missing = False
    for line_text in lines:
        stripped = line_text.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not inserted_missing:
                for key, value in replacements.items():
                    if key not in seen:
                        out.append(f"{key}={value}")
                inserted_missing = True
            in_section = stripped == f"[{section}]"
        if in_section and "=" in line_text and not stripped.startswith(("#", ";")):
            key = line_text.split("=", 1)[0].strip()
            if key in replacements:
                if key not in seen:
                    out.append(f"{key}={replacements[key]}")
                    seen.add(key)
                continue
        out.append(line_text)
    if in_section and not inserted_missing:
        for key, value in replacements.items():
            if key not in seen:
                out.append(f"{key}={value}")
    return "\n".join(out).rstrip() + "\n"


def prepare_factory_graphical_login() -> None:
    require_root()
    if not Path("/usr/sbin/gdm3").is_file():
        raise BootstrapError("GDM3 mangler; factory-handoff kan ikke etablere kiosk-login")
    if not Path("/usr/share/wayland-sessions/ubuntu.desktop").is_file():
        raise BootstrapError("Ubuntu Wayland-session mangler; factory-handoff kan ikke fortsætte")
    GDM_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    current = GDM_CONFIG.read_text(encoding="utf-8") if GDM_CONFIG.exists() else "[daemon]\n"
    updated = _replace_ini_section_keys(
        current,
        "daemon",
        {"AutomaticLoginEnable": "true", "AutomaticLogin": KIOSK_USER, "WaylandEnable": "true"},
    )
    _atomic_root_file(GDM_CONFIG, updated, mode=0o644)
    ACCOUNTS_SERVICE_ROOT.mkdir(parents=True, exist_ok=True)
    account_file = ACCOUNTS_SERVICE_ROOT / KIOSK_USER
    account_text = "[User]\nSession=ubuntu\nXSession=ubuntu\nSystemAccount=false\nFullName=ClientFlow kiosk user\n"
    _atomic_root_file(account_file, account_text, mode=0o644)
    subprocess.run([str(SYSTEMCTL), "set-default", "graphical.target"], check=False)
    enabled = subprocess.run([str(SYSTEMCTL), "enable", "gdm.service"], check=False).returncode == 0
    if not enabled:
        subprocess.run([str(SYSTEMCTL), "enable", "gdm3.service"], check=False)
    ok("GDM autologin er klargjort til clientflow-kiosk på Ubuntu Wayland.")


def install_customer_activation_sudoers() -> None:
    require_root()
    parent_meta = PERSISTENT_ROOT.lstat()
    if (
        stat.S_ISLNK(parent_meta.st_mode)
        or not stat.S_ISDIR(parent_meta.st_mode)
        or parent_meta.st_uid != 0
        or (parent_meta.st_mode & 0o022)
    ):
        raise BootstrapError("Kundeaktiveringshelperens katalog har ugyldig ownership/permissions")
    helper = PERSISTENT_ROOT / "clientflow-fresh-install"
    meta = helper.lstat()
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or (meta.st_mode & 0o022):
        raise BootstrapError("Kundeaktiveringshelper har ugyldig ownership/permissions")
    FACTORY_ACTIVATION_SUDOERS.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# Temporary ClientFlow factory-to-customer activation capability.\n"
        f"{KIOSK_USER} ALL=(root) NOPASSWD: {helper} \"\"\n"
    )
    _atomic_root_file(FACTORY_ACTIVATION_SUDOERS, content, mode=0o440)
    if not VISUDO.is_file():
        raise BootstrapError("visudo mangler; midlertidig kundeaktiveringsret kan ikke valideres")
    result = subprocess.run(
        [str(VISUDO), "-cf", str(FACTORY_ACTIVATION_SUDOERS)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        FACTORY_ACTIVATION_SUDOERS.unlink(missing_ok=True)
        raise BootstrapError(f"Midlertidig sudoers-regel er ugyldig: {(result.stdout or '')[-1000:]}")
    ok("Kiosk-brugeren har kun passwordfri ret til den eksakte, root-ejede kundeaktiveringshelper uden argumenter.")


def remove_customer_activation_sudoers() -> None:
    FACTORY_ACTIVATION_SUDOERS.unlink(missing_ok=True)


def install_customer_launcher_trust_helper(user: str) -> None:
    account = pwd.getpwnam(validate_local_user(user))
    home = Path(account.pw_dir)
    helper = Path("/usr/local/bin/clientflow-trust-customer-activation")
    desktop_candidates = [str(desktop_dir(user)), str(home / "Desktop"), str(home / "Skrivebord")]
    script = "#!/usr/bin/env bash\nset -u\n" + "\n".join(
        f'if [ -f {shlex.quote(path + "/02 Aktiver ClientFlow.desktop")} ]; then gio set {shlex.quote(path + "/02 Aktiver ClientFlow.desktop")} metadata::trusted true >/dev/null 2>&1 || true; fi'
        for path in dict.fromkeys(desktop_candidates)
    ) + "\n"
    _atomic_root_file(helper, script, mode=0o755)
    config = home / ".config"
    autostart = config / "autostart"
    for directory in (config, autostart):
        try:
            metadata = directory.lstat()
        except FileNotFoundError:
            directory.mkdir(mode=0o755)
            os.chown(directory, account.pw_uid, account.pw_gid)
            metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise BootstrapError(f"Kiosk autostart-katalog er ugyldigt: {directory}")
        if metadata.st_uid != account.pw_uid:
            raise BootstrapError(f"Kiosk autostart-katalog ejes ikke af kiosk-brugeren: {directory}")
    target = autostart / "clientflow-trust-customer-activation.desktop"
    content = "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=ClientFlow activation icon trust",
        "Exec=/usr/local/bin/clientflow-trust-customer-activation",
        "Terminal=false",
        "X-GNOME-Autostart-enabled=true",
        "NoDisplay=true",
        "",
    ])
    _write_user_file_no_follow(target, content, user=user, mode=0o644)


def cleanup_customer_launcher_trust_helper(user: str) -> None:
    try:
        home = user_home(user)
    except (BootstrapError, KeyError):
        return
    (home / ".config/autostart/clientflow-trust-customer-activation.desktop").unlink(missing_ok=True)
    Path("/usr/local/bin/clientflow-trust-customer-activation").unlink(missing_ok=True)


def _generated_networkmanager_profiles() -> list[tuple[str, str]]:
    profiles: list[tuple[str, str]] = []
    if not _NETWORKMANAGER_GENERATED_ROOT.is_dir():
        return profiles
    for path in sorted(_NETWORKMANAGER_GENERATED_ROOT.glob("*.nmconnection")):
        try:
            meta = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
            raise BootstrapError(f"NetworkManager generated profile er ugyldig: {path.name}")
        section = ""
        connection_type = ""
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line_text = raw_line.strip()
            if line_text.startswith("[") and line_text.endswith("]"):
                section = line_text[1:-1]
                continue
            if section == "connection" and line_text.startswith("type="):
                connection_type = line_text.split("=", 1)[1].strip()
                break
        if connection_type:
            profiles.append((path.name, connection_type))
    return profiles


def _validate_persistent_network_cleanup() -> None:
    if not NETPLAN.is_file():
        raise BootstrapError("netplan mangler; persistent factory-netværk kan ikke valideres")
    result = _run([str(NETPLAN), "generate"], timeout=60)
    if result.returncode != 0:
        raise BootstrapError(
            f"Netplan kunne ikke validere factory-netværkscleanup: {(result.stdout or '')[-1000:]}"
        )
    leftovers = [
        name
        for name, connection_type in _generated_networkmanager_profiles()
        if connection_type in _FORGET_NETWORK_TYPES
    ]
    if leftovers:
        raise BootstrapError(
            "Persistent Netplan factory-profiler kan regenereres efter cleanup: "
            + ", ".join(leftovers)
        )


def _forget_persistent_netplan_networks() -> None:
    if not NETPLAN.is_file():
        raise BootstrapError("netplan mangler; persistent factory-netværk kan ikke fjernes")
    for key in _NETPLAN_FORGET_KEYS:
        result = _run([str(NETPLAN), "set", f"{key}=null"], timeout=30)
        if result.returncode != 0:
            raise BootstrapError(
                f"Kunne ikke fjerne persistent Netplan factory-konfiguration ({key}): "
                f"{(result.stdout or '')[-1000:]}"
            )
    _validate_persistent_network_cleanup()


def forget_saved_networks() -> int:
    _networkmanager_ready()
    rows = _all_connections()
    deleted = 0
    for connection_uuid, row in rows.items():
        if row.get("type") not in _FORGET_NETWORK_TYPES:
            continue
        print(f"Sletter gemt forbindelse: {row.get('name') or 'ukendt'} ({row.get('type')})")
        result = _run([str(NMCLI), "connection", "delete", "uuid", connection_uuid], timeout=30)
        if result.returncode == 0:
            deleted += 1
        else:
            raise BootstrapError(
                f"Kunne ikke slette gemt NetworkManager-profil: {row.get('name') or connection_uuid}"
            )
    _forget_persistent_netplan_networks()
    remaining = [
        row for row in _all_connections().values() if row.get("type") in _FORGET_NETWORK_TYPES
    ]
    if remaining:
        names = ", ".join(str(row.get("name") or row.get("uuid")) for row in remaining)
        raise BootstrapError(f"Gemte netværksprofiler findes stadig efter factory-cleanup: {names}")
    if deleted:
        ok(f"Slettede {deleted} gemte netværksforbindelse(r) og persistent Netplan-state.")
    else:
        ok("Ingen gemte NetworkManager-forbindelser fundet; persistent Netplan-state er ryddet.")
    return deleted


def validate_factory_handoff(*, client_name: str, operator_user: str) -> None:
    state = load_factory_state()
    if not isinstance(state, dict) or state.get("schema_version") != 2:
        raise BootstrapError("Factory-state mangler eller har forkert schema")
    if state.get("client_name") != normalize_client_name(client_name):
        raise BootstrapError("Factory-state klientnavn matcher ikke")
    if state.get("operator_user") != validate_local_user(operator_user):
        raise BootstrapError("Factory-state operator matcher ikke")
    validate_factory_human_accounts()
    for username in (KIOSK_USER, ADMIN_USER):
        validate_factory_gnome_initial_setup_markers(username)
        validate_factory_popup_autostarts(username)
    gdm = GDM_CONFIG.read_text(encoding="utf-8") if GDM_CONFIG.is_file() else ""
    if "AutomaticLoginEnable=true" not in gdm or f"AutomaticLogin={KIOSK_USER}" not in gdm or "WaylandEnable=true" not in gdm:
        raise BootstrapError("GDM factory-handoff peger ikke på canonical kiosk-bruger")
    launcher = desktop_dir(KIOSK_USER) / "02 Aktiver ClientFlow.desktop"
    if not launcher.is_file():
        raise BootstrapError("02 Aktiver ClientFlow mangler på kiosk-skrivebordet")
    if not FACTORY_ACTIVATION_SUDOERS.is_file():
        raise BootstrapError("Midlertidig kundeaktiveringsret mangler")
    result = subprocess.run([str(VISUDO), "-cf", str(FACTORY_ACTIVATION_SUDOERS)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if result.returncode != 0:
        raise BootstrapError("Midlertidig kundeaktiveringsret kan ikke valideres med visudo")
    leftovers = [row for row in _all_connections().values() if row.get("type") in _FORGET_NETWORK_TYPES]
    if leftovers:
        raise BootstrapError("Factory-handoff har stadig gemte NetworkManager-profiler")
    _validate_persistent_network_cleanup()
    write_factory_state(client_name=client_name, operator_user=operator_user, handoff_ready=True)
    ok("Factory → kunde handoff er valideret fail-closed før reboot.")

def load_usb_state() -> dict[str, object] | None:
    return _safe_json_read(USB_STATE)


def write_usb_state(*, operator_user: str, network_marker: dict[str, str] | None) -> None:
    _atomic_root_json(
        USB_STATE,
        {
            "schema_version": 1,
            "operator_user": validate_local_user(operator_user),
            "network_marker": network_marker,
        },
    )


def clear_usb_state() -> None:
    USB_STATE.unlink(missing_ok=True)


def sudo_user() -> str:
    candidate = str(os.environ.get("SUDO_USER") or "").strip()
    if not candidate or candidate == "root":
        raise BootstrapError("ClientFlow-klargøring skal startes fra den lokale Ubuntu-installationsbruger via sudo.")
    return validate_local_user(candidate)


def validate_local_user(name: str) -> str:
    value = str(name or "").strip()
    if not value or len(value) > 64 or _CONTROL_RE.search(value):
        raise BootstrapError("Ugyldigt lokalt brugernavn")
    try:
        account = pwd.getpwnam(value)
    except KeyError as exc:
        raise BootstrapError(f"Lokal bruger findes ikke: {value}") from exc
    if account.pw_uid < 1000 or account.pw_uid >= 65000:
        raise BootstrapError("ClientFlow-klargøring kræver en normal lokal Ubuntu-bruger")
    return value


def normalize_client_name(value: str | None) -> str:
    name = str(value or "").strip()
    if not name:
        raise BootstrapError("Klientnavn må ikke være tomt")
    if len(name) > 120 or _CONTROL_RE.search(name):
        raise BootstrapError("Klientnavn er ugyldigt")
    return name


def normalize_locality(value: str | None) -> str | None:
    locality = str(value or "").strip()
    if not locality:
        return None
    if len(locality) > 200 or _CONTROL_RE.search(locality):
        raise BootstrapError("Lokation er ugyldig")
    return locality


def prompt_client_name_confirmed(existing: str | None = None) -> str:
    current = str(existing or "").strip()
    while True:
        print()
        line()
        print("KLIENTNAVN")
        line()
        if current:
            print("Klientnavn der er fundet på klienten:\n")
            print(f"  {current}\n")
            answer = input("Vil du bruge dette klientnavn? [J/n]: ").strip().lower() or "j"
            if answer in {"j", "ja", "y", "yes"}:
                return normalize_client_name(current)
            if answer not in {"n", "nej", "no"}:
                warn("Ugyldigt valg. Svar j for behold eller n for ændr.")
                continue
            current = ""
        else:
            print("Der er ikke fundet et eksisterende klientnavn.")

        while True:
            value = input("Klientnavn, defineres på kontoret og vises senere ude hos kunden: ").strip()
            if value:
                value = normalize_client_name(value)
                break
            warn("Klientnavn må ikke være tomt. Prøv igen.")
        print("\nKlientnavn bliver:\n")
        print(f"  {value}\n")
        answer = input("Er dette korrekt? [J/n]: ").strip().lower() or "j"
        if answer in {"j", "ja", "y", "yes"}:
            return value
        if answer in {"n", "nej", "no"}:
            print("Indtast klientnavn igen.")
            continue
        warn("Ugyldigt valg. Svar j for korrekt eller n for ændr.")


def prompt_locality() -> str | None:
    return normalize_locality(input("Lokation/rum hos kunden (valgfri, Enter = tom): "))


def _cf_normalize(text: str) -> str:
    value = (text or "").upper()
    if value.startswith("CF-"):
        value = value[3:]
    elif value.startswith("CF"):
        value = value[2:]
    return "".join(ch for ch in value if ch in _CF_ALLOWED)[:12]


def format_cf_code(raw: str) -> str:
    slots = list("____________")
    for index, char in enumerate(_cf_normalize(raw)):
        slots[index] = char
    return "CF-{}{}{}{}-{}{}{}{}-{}{}{}{}".format(*slots)


def final_cf_code(raw: str) -> str:
    value = _cf_normalize(raw)
    return f"CF-{value[0:4]}-{value[4:8]}-{value[8:12]}"


def valid_cf_code(value: str) -> bool:
    return re.fullmatch(r"CF-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", value or "") is not None


def read_cf_code() -> str:
    if not sys.stdin.isatty():
        raise BootstrapError("CF-koden skal indtastes fra en interaktiv terminal")
    raw = ""
    old = termios.tcgetattr(sys.stdin)

    def redraw(message: str = "") -> None:
        sys.stderr.write("\r\033[KIndtast aktiveringskode: " + format_cf_code(raw))
        if message:
            sys.stderr.write("  " + message)
        sys.stderr.flush()

    try:
        tty.setraw(sys.stdin.fileno())
        redraw()
        while True:
            char = sys.stdin.read(1)
            if char in {"\r", "\n"}:
                code = final_cf_code(raw)
                if valid_cf_code(code):
                    sys.stderr.write("\n")
                    return code
                redraw("(udfyld alle 12 tegn)")
                continue
            if char in {"\x03", "\x04"}:
                raise KeyboardInterrupt
            if char in {"\x7f", "\b"}:
                raw = _cf_normalize(raw)[:-1]
                redraw()
                continue
            if char == "\x1b":
                sys.stdin.read(1)
                sys.stdin.read(1)
                redraw()
                continue
            upper = char.upper()
            if upper in _CF_ALLOWED or upper in "- \t":
                raw = _cf_normalize(raw + upper)
            redraw()
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


def _run(command: list[str], *, timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "LC_ALL": "C", "LANG": "C.UTF-8"},
    )
    if check and result.returncode != 0:
        raise BootstrapError(f"Kommando fejlede ({result.returncode}): {' '.join(command)}\n{result.stdout[-3000:]}")
    return result


def _nm_rows(fields: str, *args: str) -> list[list[str]]:
    result = _run([str(NMCLI), "--terse", "--escape", "no", "--fields", fields, *args], timeout=30, check=True)
    return [line.split(":") for line in result.stdout.splitlines() if line.strip()]


def _all_connections() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for parts in _nm_rows("UUID,TYPE,NAME", "connection", "show"):
        if len(parts) < 3:
            continue
        raw_uuid, type_name = parts[0].strip(), parts[1].strip()
        name = ":".join(parts[2:]).strip()
        try:
            connection_uuid = str(uuid.UUID(raw_uuid))
        except ValueError:
            continue
        result[connection_uuid] = {"uuid": connection_uuid, "type": type_name, "name": name}
    return result


def _active_connections() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for parts in _nm_rows("UUID,TYPE,NAME", "connection", "show", "--active"):
        if len(parts) < 3:
            continue
        try:
            connection_uuid = str(uuid.UUID(parts[0].strip()))
        except ValueError:
            continue
        result[connection_uuid] = {
            "uuid": connection_uuid,
            "type": parts[1].strip(),
            "name": ":".join(parts[2:]).strip(),
        }
    return result


def _backend_healthy() -> bool:
    request = urllib.request.Request(BACKEND_URL + "/health", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            return False
        data = json.loads(raw.decode("utf-8"))
        return isinstance(data, dict) and data.get("status") == "ok"
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def _networkmanager_ready() -> None:
    if not NMCLI.is_file():
        raise BootstrapError("Ubuntu Desktop-klargøring kræver NetworkManager/nmcli")
    result = _run([str(NMCLI), "--terse", "--fields", "RUNNING", "general"], timeout=10, check=True)
    if result.stdout.strip().lower() != "running":
        raise BootstrapError("NetworkManager er ikke running")


def _new_owned_connection(before: set[str], preferred_name: str) -> dict[str, str] | None:
    after = _all_connections()
    created = [row for connection_uuid, row in after.items() if connection_uuid not in before]
    exact = [row for row in created if row["name"] == preferred_name and row["type"] in _ALLOWED_NETWORK_TYPES]
    if len(exact) == 1:
        return dict(exact[0])
    return None


def _wifi_scan() -> list[tuple[str, str, str]]:
    _run([str(NMCLI), "radio", "wifi", "on"], timeout=10)
    _run([str(NMCLI), "device", "wifi", "rescan"], timeout=20)
    time.sleep(3)
    result = _run(
        [str(NMCLI), "--terse", "--escape", "no", "--fields", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
        timeout=30,
        check=True,
    )
    strongest: dict[str, tuple[str, str]] = {}
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        parts = raw.rsplit(":", 2)
        if len(parts) != 3:
            continue
        ssid, signal, security = (part.strip() for part in parts)
        if not ssid:
            continue
        try:
            strength = int(signal)
        except ValueError:
            strength = -1
        previous = strongest.get(ssid)
        if previous is None or strength > int(previous[0] or -1):
            strongest[ssid] = (str(strength), security or "åbent")
    return sorted(((ssid, sig, sec) for ssid, (sig, sec) in strongest.items()), key=lambda row: int(row[1]), reverse=True)


def _connect_wifi(ssid: str, *, hidden: bool = False) -> dict[str, str] | None:
    before = set(_all_connections())
    profile_name = f"ClientFlow bootstrap {uuid.uuid4().hex[:8]}"
    command = [str(NMCLI), "--ask", "--wait", "45", "device", "wifi", "connect", ssid, "name", profile_name]
    if hidden:
        command += ["hidden", "yes"]
    print(f"Forbinder til WiFi: {ssid}")
    result = subprocess.run(command, timeout=90, check=False)
    if result.returncode != 0:
        warn("WiFi-forbindelsen blev ikke etableret.")
        return None
    return _new_owned_connection(before, profile_name)


def _show_network_status() -> tuple[bool, bool]:
    print("[STATUS] Samlet netværksstatus")
    rows = _nm_rows("DEVICE,TYPE,STATE,CONNECTION", "device", "status")
    wired_connected = False
    any_connected = False
    print("[STATUS] Kablet netværk / Ethernet")
    wired_found = False
    for parts in rows:
        if len(parts) < 4:
            continue
        device, type_name, state = parts[0].strip(), parts[1].strip(), parts[2].strip()
        connection = ":".join(parts[3:]).strip()
        if state == "connected":
            any_connected = True
        if type_name not in {"ethernet", "802-3-ethernet"}:
            continue
        wired_found = True
        if state == "connected":
            wired_connected = True
        ip_address = "ingen"
        if IP.is_file():
            result = _run([str(IP), "-4", "-o", "addr", "show", "dev", device], timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                fields = result.stdout.split()
                if "inet" in fields:
                    index = fields.index("inet")
                    if index + 1 < len(fields):
                        ip_address = fields[index + 1].split("/", 1)[0]
        mac_path = Path("/sys/class/net") / device / "address"
        carrier_path = Path("/sys/class/net") / device / "carrier"
        mac = mac_path.read_text(encoding="ascii", errors="ignore").strip() if mac_path.is_file() else "ukendt"
        carrier = carrier_path.read_text(encoding="ascii", errors="ignore").strip() if carrier_path.is_file() else "?"
        print(
            f"  {device}: state={state or '?'} connection={connection} carrier={carrier} "
            f"ip={ip_address} mac={mac or 'ukendt'}"
        )
    if not wired_found:
        warn("Ingen kablede netværksenheder fundet. Fortsætter med mulighed for WiFi.")
    elif wired_connected:
        ok("Kablet netværk er aktivt i NetworkManager.")
    else:
        warn("Ingen aktiv kablet forbindelse fundet. Tilslut kabel eller brug WiFi.")

    print("[STATUS] NetworkManager-enheder")
    for parts in rows:
        print("  " + ":".join(parts))
    if IP.is_file():
        print("[STATUS] IP-adresser")
        result = _run([str(IP), "-brief", "addr"], timeout=10)
        for line_text in result.stdout.splitlines():
            print(f"  {line_text}")
    if _backend_healthy():
        ok("ClientFlow-backend svarer.")
        backend_ok = True
    else:
        warn("ClientFlow-backend svarer ikke endnu.")
        backend_ok = False
    return wired_connected, any_connected and backend_ok


def configure_network_interactive(label: str) -> dict[str, str] | None:
    _networkmanager_ready()
    print()
    line()
    print(f"NETVÆRKSKONTROL · {label} · kablet først, WiFi hvis nødvendigt")
    line()
    print(f"[STATUS] Netværk for {label}")
    print("Denne fase kontrollerer altid kablet netværk først. Hvis Ethernet ikke virker, vises en WiFi-liste.")
    while True:
        wired_connected, backend_ready = _show_network_status()
        if backend_ready:
            if wired_connected:
                ok("Kablet netværk er aktivt, og ClientFlow-backend kan nås.")
            else:
                ok("Netværk er aktivt via WiFi/anden forbindelse, og ClientFlow-backend kan nås.")
            return None

        warn("Der er ikke bekræftet forbindelse til ClientFlow-backend endnu.")
        if not wired_connected:
            warn("Kablet netværk virker ikke. Viser WiFi-liste nu.")
        networks = _wifi_scan()
        if networks:
            print("\nTilgængelige WiFi-netværk:")
            for index, (ssid, signal, security) in enumerate(networks, start=1):
                print(f"  {index:2d}) {ssid:<32} signal={signal}% sikkerhed={security}")
        else:
            warn("Ingen WiFi-netværk fundet lige nu.")
        print("\nVælg nummer fra listen, eller:")
        print("  R) Scan igen")
        print("  M) Indtast WiFi-navn manuelt/skjult netværk")
        print("  N) Åbn nmtui")
        print("  K) Jeg har sat kabel i - test igen")
        print("  A) Afslut")
        choice = input("Valg: ").strip() or "R"
        lowered = choice.lower()
        if lowered == "r" or lowered == "k":
            continue
        if lowered == "a":
            raise BootstrapError("Afsluttet uden netværk")
        if lowered == "n":
            nmtui = Path("/usr/bin/nmtui")
            if nmtui.is_file():
                subprocess.run([str(nmtui)], check=False)
            else:
                warn("nmtui findes ikke.")
            continue
        if lowered == "m":
            ssid = input("WiFi navn / SSID: ").strip()
            if not ssid:
                warn("SSID var tomt.")
                continue
            marker = _connect_wifi(ssid, hidden=True)
            time.sleep(3)
            if _backend_healthy():
                ok("WiFi er aktivt, og ClientFlow-backend kan nås.")
                return marker
            if marker is not None:
                forget_owned_connection(marker)
                warn("Den ClientFlow-oprettede WiFi-profil blev fjernet igen, fordi backend ikke kunne nås.")
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(networks):
            marker = _connect_wifi(networks[int(choice) - 1][0])
            time.sleep(3)
            if _backend_healthy():
                ok("WiFi er aktivt, og ClientFlow-backend kan nås.")
                return marker
            if marker is not None:
                forget_owned_connection(marker)
                warn("Den ClientFlow-oprettede WiFi-profil blev fjernet igen, fordi backend ikke kunne nås.")
            continue
        warn("Ugyldigt valg.")


def forget_owned_connection(marker: dict[str, object] | None) -> bool:
    if not marker:
        return False
    raw_uuid = str(marker.get("uuid") or "")
    expected_name = str(marker.get("name") or "")
    expected_type = str(marker.get("type") or "")
    try:
        connection_uuid = str(uuid.UUID(raw_uuid))
    except ValueError as exc:
        raise BootstrapError("Gemte NetworkManager metadata er ugyldige") from exc
    if expected_type not in _ALLOWED_NETWORK_TYPES:
        raise BootstrapError("Gemte NetworkManager metadata har ugyldig type")
    current = _all_connections().get(connection_uuid)
    if current is None:
        return False
    if current["name"] != expected_name or current["type"] != expected_type:
        raise BootstrapError("Bootstrap-netværkets UUID matcher ikke længere den oprindelige profil")
    _run([str(NMCLI), "connection", "delete", "uuid", connection_uuid], timeout=30, check=True)
    return True


def user_home(user: str) -> Path:
    return Path(pwd.getpwnam(validate_local_user(user)).pw_dir)



def _prepare_desktop_directory(user: str, candidate: Path) -> Path:
    account = pwd.getpwnam(validate_local_user(user))
    home = Path(account.pw_dir)
    try:
        home_real = home.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError(f"Brugerens home-katalog kan ikke valideres: {home}") from exc
    resolved = candidate.resolve(strict=False)
    if resolved != home_real and home_real not in resolved.parents:
        raise BootstrapError("XDG Desktop peger uden for brugerens home-katalog")
    try:
        meta = candidate.lstat()
    except FileNotFoundError:
        candidate.mkdir(parents=True, exist_ok=False)
        os.chown(candidate, account.pw_uid, account.pw_gid)
        meta = candidate.lstat()
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
        raise BootstrapError(f"XDG Desktop er ikke et reelt katalog: {candidate}")
    if meta.st_uid != account.pw_uid:
        raise BootstrapError(f"XDG Desktop ejes ikke af den forventede bruger: {candidate}")
    return candidate


def desktop_dir(user: str) -> Path:
    user = validate_local_user(user)
    home = user_home(user)
    if RUNUSER.is_file() and XDG_USER_DIR.is_file():
        result = subprocess.run(
            [str(RUNUSER), "-u", user, "--", "env", f"HOME={home}", f"XDG_CONFIG_HOME={home / '.config'}", str(XDG_USER_DIR), "DESKTOP"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
        candidate = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None
        if candidate is not None and candidate.is_absolute() and (candidate == home or home in candidate.parents):
            return _prepare_desktop_directory(user, candidate)
    config = home / ".config/user-dirs.dirs"
    if config.is_file():
        match = re.search(r'^XDG_DESKTOP_DIR="\$HOME/(.*)"$', config.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if match and ".." not in Path(match.group(1)).parts:
            candidate = home / match.group(1)
            return _prepare_desktop_directory(user, candidate)
    candidate = home / "Desktop"
    return _prepare_desktop_directory(user, candidate)


def _trust_desktop_file(user: str, path: Path) -> None:
    account = pwd.getpwnam(user)
    meta = path.lstat()
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
        raise BootstrapError(f"Desktop-launcher er ikke en reel fil: {path}")
    if meta.st_uid != account.pw_uid or (meta.st_mode & 0o022):
        raise BootstrapError(f"Desktop-launcher har ugyldig ownership/permissions: {path}")
    runtime = Path(f"/run/user/{account.pw_uid}")
    bus = runtime / "bus"
    if GIO.is_file() and bus.exists() and RUNUSER.is_file():
        subprocess.run(
            [str(RUNUSER), "-u", user, "--", "env", f"HOME={account.pw_dir}", f"XDG_RUNTIME_DIR={runtime}", f"DBUS_SESSION_BUS_ADDRESS=unix:path={bus}", str(GIO), "set", str(path), "metadata::trusted", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )


def write_desktop_launcher(user: str, *, filename: str, name: str, comment: str, exec_path: str) -> Path:
    desktop = desktop_dir(user)
    target = desktop / filename
    content = "\n".join(
        [
            "[Desktop Entry]",
            "Version=1.0",
            "Type=Application",
            f"Name={name}",
            f"Comment={comment}",
            "Terminal=false",
            f"Exec={exec_path}",
            f"Icon={PLANIQ_DISPLAY_DESKTOP_ICON}",
            "Categories=Utility;System;",
            "StartupNotify=true",
            "X-GNOME-Trusted=true",
            "",
        ]
    )
    _write_user_file_no_follow(target, content, user=user, mode=0o755)
    _trust_desktop_file(user, target)
    return target


def remove_desktop_install_icons(user: str) -> None:
    home = user_home(user)
    directories = {desktop_dir(user), home / "Desktop", home / "Skrivebord"}
    names = {
        "01 Klient klargøring.desktop",
        "02 Aktiver ClientFlow.desktop",
        "02 Aktiver ClientFlow.sh",
        "Aktiver ClientFlow.desktop",
    }
    for directory in directories:
        if not directory.exists():
            continue
        for name in names:
            (directory / name).unlink(missing_ok=True)


def install_terminal_launcher(path: Path, *, title: str, command: str) -> None:
    quoted_title = shlex.quote(title)
    quoted_command = shlex.quote(command)
    script = f'''#!/usr/bin/env bash\nset -euo pipefail\nif command -v ptyxis >/dev/null 2>&1; then\n  exec ptyxis --title={quoted_title} -- bash -lc {quoted_command}\nelif command -v x-terminal-emulator >/dev/null 2>&1; then\n  exec x-terminal-emulator -T {quoted_title} -e bash -lc {quoted_command}\nelif command -v gnome-terminal >/dev/null 2>&1; then\n  exec gnome-terminal --title={quoted_title} -- bash -lc {quoted_command}\nelif command -v kgx >/dev/null 2>&1; then\n  exec kgx --title {quoted_title} -- bash -lc {quoted_command}\nelif command -v xterm >/dev/null 2>&1; then\n  exec xterm -T {quoted_title} -e bash -lc {quoted_command}\nelse\n  exec bash -lc {quoted_command}\nfi\n'''
    _atomic_root_file(path, script, mode=0o755)


def confirmed_reboot(reason: str, *, seconds: int = 5) -> bool:
    print(f"\nFlowet er færdigt og kræver genstart: {reason}")
    print("Maskinen genstarter IKKE automatisk. Du skal bekræfte først.")
    answer = input("Vil du genstarte nu? [j/N]: ").strip().lower() or "n"
    if answer not in {"j", "ja", "y", "yes"}:
        warn("Genstart er ikke udført. Genstart manuelt senere for at fuldføre flowet.")
        print("Du kan genstarte manuelt med: sudo systemctl --no-block --check-inhibitors=no reboot")
        return False
    for remaining in range(seconds, 0, -1):
        print(f"Genstarter om {remaining} sekunder...")
        time.sleep(1)
    result = subprocess.run(
        [str(SYSTEMCTL), "--no-block", "--check-inhibitors=no", "reboot"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise BootstrapError(f"Kunne ikke køe genstart: {(result.stdout or '')[-1000:]}")
    return True


def install_persistent_bootstrap(source_dir: Path) -> None:
    require_root()
    source_dir = source_dir.resolve()
    required = {
        "clientflow_bootstrap_common.py": 0o444,
        "clientflow-factory-prepare": 0o555,
        "clientflow-fresh-install": 0o555,
        "planiq-display-mark.png": 0o444,
    }
    _ensure_root_directory(PERSISTENT_ROOT, mode=0o755)
    for name, mode in required.items():
        source = source_dir / name
        meta = source.lstat()
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
            raise BootstrapError(f"Bootstrap-kildefil er ugyldig: {source}")
        data = source.read_bytes()
        target = PERSISTENT_ROOT / name
        fd, temporary_name = tempfile.mkstemp(prefix=f".{name}.", dir=str(PERSISTENT_ROOT))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb", closefd=True) as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chown(temporary, 0, 0)
            os.chmod(temporary, mode)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
