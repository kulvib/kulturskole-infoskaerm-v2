from __future__ import annotations

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
RUNUSER = Path("/usr/sbin/runuser")
XDG_USER_DIR = Path("/usr/bin/xdg-user-dir")
GIO = Path("/usr/bin/gio")
MAX_JSON_BYTES = 128 * 1024
_ALLOWED_NETWORK_TYPES = {"wifi", "802-11-wireless", "ethernet", "802-3-ethernet"}
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


def write_factory_state(*, client_name: str, operator_user: str) -> None:
    _atomic_root_json(
        FACTORY_STATE,
        {
            "schema_version": 1,
            "client_name": normalize_client_name(client_name),
            "operator_user": validate_local_user(operator_user),
        },
    )


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


def configure_network_interactive(label: str) -> dict[str, str] | None:
    _networkmanager_ready()
    print()
    line()
    print(f"NETVÆRKSKONTROL · {label} · kablet først, WiFi hvis nødvendigt")
    line()
    while True:
        active = _active_connections()
        if active and _backend_healthy():
            ok("Netværk er aktivt, og ClientFlow-backend kan nås.")
            return None

        warn("Der er ikke bekræftet forbindelse til ClientFlow-backend endnu.")
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
        print("Du kan genstarte manuelt med: sudo systemctl --no-block --ignore-inhibitors reboot")
        return False
    for remaining in range(seconds, 0, -1):
        print(f"Genstarter om {remaining} sekunder...")
        time.sleep(1)
    result = subprocess.run(
        [str(SYSTEMCTL), "--no-block", "--ignore-inhibitors", "reboot"],
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
