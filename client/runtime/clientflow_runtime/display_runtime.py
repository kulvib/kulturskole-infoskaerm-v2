"""Unprivileged Display runtime for the canonical Google Chrome kiosk process."""
from __future__ import annotations

import grp
import json
import os
from pathlib import Path
import pwd
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import time
from typing import Any
from urllib.parse import urlsplit

from .atomic import atomic_write_json
from .display_shared_file import atomic_write_shared_json
from .logging_utils import configure_logging
from .unix_rpc import RpcError, encode_message, read_message

STATE_DIR = Path(os.getenv("CLIENTFLOW_DISPLAY_STATE_DIR", "/var/lib/clientflow/display-runtime"))
RUNTIME_DIR = Path(os.getenv("CLIENTFLOW_DISPLAY_RUNTIME_DIR", "/run/clientflow/display"))
CONFIG_PATH = STATE_DIR / "configuration.json"
SOCKET_PATH = RUNTIME_DIR / "runtime.sock"
STATUS_PATH = STATE_DIR / "runtime-status.json"
PID_PATH = RUNTIME_DIR / "browser.pid"
PROFILE_DIR = STATE_DIR / "browser-profile"
CHROME_BINARY = Path("/usr/bin/google-chrome-stable")
CONTROL_GROUP_NAME = os.getenv("CLIENTFLOW_DISPLAY_CONTROL_GROUP", "clientflow-display-control")
_ALLOWED_CONFIGURATION_KEYS = {"schema_version", "revision", "kiosk_url"}
BOOT_START_COUNTDOWN_SECONDS = 10
CONFIGURATION_START_COUNTDOWN_SECONDS = 10
MANUAL_START_COUNTDOWN_SECONDS = 10
RESET_BROWSER_COUNTDOWN_SECONDS = 10
DISPLAY_SLEEP_COUNTDOWN_SECONDS = 10
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
BOOT_MARKER_PATH = STATE_DIR / "browser-boot.json"
CALENDAR_PREVIEW_PATH = STATE_DIR / "calendar-preview.json"
LOCAL_GUI_STATUS_PATH = STATE_DIR / "local-gui-status.json"
LOCAL_DISPLAY_POWER_PATH = STATE_DIR / "local-display-power.json"
LOCAL_GUI_SCRIPT = Path("/opt/clientflow/active/client-runtime/libexec/local-gui")
SYSTEM_PYTHON = Path("/usr/bin/python3")


class DisplayRuntime:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.display.runtime")
        self.browser: subprocess.Popen[bytes] | None = None
        self.local_gui: subprocess.Popen[bytes] | None = None
        self.configuration: dict[str, Any] = self._load_configuration()
        self.browser_requested = bool(self.configuration.get("kiosk_url"))
        self.next_start_attempt = 0.0
        self.next_gui_start_attempt = 0.0
        self.boot_start_pending = False
        self.display_power = self._load_display_power()
        self.shared_group_gid: int | None = None

    @staticmethod
    def _control_group_gid() -> int:
        try:
            return grp.getgrnam(CONTROL_GROUP_NAME).gr_gid
        except KeyError as exc:
            raise RuntimeError("Display control-gruppen mangler") from exc

    def _prepare_shared_permissions(self) -> None:
        gid = self._control_group_gid()
        for directory in (STATE_DIR, RUNTIME_DIR):
            directory.mkdir(parents=True, exist_ok=True)
            os.chown(directory, -1, gid)
            os.chmod(directory, 0o750)
        for path, mode in ((CONFIG_PATH, 0o640), (STATUS_PATH, 0o640)):
            if path.exists():
                os.chown(path, -1, gid)
                os.chmod(path, mode)
        self.shared_group_gid = gid

    def _load_configuration(self) -> dict[str, Any]:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Displaykonfiguration er ugyldig") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Displaykonfiguration skal være et objekt")
        return self._validate_configuration(data)

    @staticmethod
    def _load_display_power() -> str:
        try:
            value = json.loads(LOCAL_DISPLAY_POWER_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "unknown"
        state = str(value.get("state") or "") if isinstance(value, dict) else ""
        return state if state in {"on", "off"} else "unknown"

    def _status(self, state: str, **details: Any) -> None:
        payload = {
            "schema_version": 1,
            "configuration_revision": self.configuration.get("revision") if self.configuration else None,
            "state": state,
            "browser_pid": self.browser.pid if self.browser and self.browser.poll() is None else None,
            "browser_requested": bool(self.browser_requested),
            "display_power": self.display_power,
            "updated_at": time.time(),
            **details,
        }
        atomic_write_shared_json(STATUS_PATH, payload, mode=0o640, group_gid=self.shared_group_gid)

    @staticmethod
    def _boot_id() -> str | None:
        try:
            value = BOOT_ID_PATH.read_text(encoding="ascii").strip()
        except OSError:
            return None
        return value or None

    def _boot_start_required(self) -> bool:
        boot_id = self._boot_id()
        if not boot_id:
            return False
        try:
            current = json.loads(BOOT_MARKER_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        return not (isinstance(current, dict) and current.get("boot_id") == boot_id)

    def _mark_browser_start_this_boot(self) -> None:
        boot_id = self._boot_id()
        if not boot_id:
            return
        atomic_write_shared_json(
            BOOT_MARKER_PATH,
            {"schema_version": 1, "boot_id": boot_id, "updated_at": time.time()},
            mode=0o640,
            group_gid=self.shared_group_gid,
        )

    def _start_browser_with_boot_policy(self) -> dict[str, Any]:
        if self.boot_start_pending:
            self._clear_browser_profile(reason="system_start")
            self._countdown("countdown", BOOT_START_COUNTDOWN_SECONDS, reason="system_start")
            self._mark_browser_start_this_boot()
            self.boot_start_pending = False
        return self.start_browser()

    def _countdown(self, step: str, seconds: int, *, reason: str) -> None:
        for remaining in range(max(0, int(seconds)), 0, -1):
            self._status(
                "countdown",
                step=step,
                countdown_remaining=remaining,
                countdown_reason=reason,
            )
            time.sleep(1)

    @staticmethod
    def _normalize_kiosk_url(value: Any) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if len(raw) > 2048:
            raise ValueError("kiosk_url er for lang")
        try:
            parsed = urlsplit(raw)
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("kiosk_url er ugyldig") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("kiosk_url må ikke indeholde login-oplysninger")
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() == "https" and host and parsed.netloc:
            return raw
        if parsed.scheme.lower() == "http" and host in {"localhost", "127.0.0.1"}:
            return raw
        raise ValueError("kiosk_url kræver HTTPS; HTTP er kun tilladt til localhost eller 127.0.0.1")

    def _validate_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        unknown = set(payload) - _ALLOWED_CONFIGURATION_KEYS
        if unknown:
            raise ValueError(f"Ukendte displayfelter: {', '.join(sorted(unknown))}")
        try:
            schema_version = int(payload.get("schema_version"))
            revision = int(payload.get("revision"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Displaykonfiguration mangler schema_version/revision") from exc
        if schema_version != 1 or revision < 1:
            raise ValueError("Displaykonfigurationens schema_version/revision er ugyldig")
        return {
            "schema_version": 1,
            "revision": revision,
            "kiosk_url": self._normalize_kiosk_url(payload.get("kiosk_url")),
        }

    def apply_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        configuration = self._validate_configuration(payload)
        current_revision = int(self.configuration.get("revision") or 0) if self.configuration else 0
        if configuration["revision"] < current_revision:
            raise ValueError("Displaykonfigurationens revision er ældre end den aktive revision")
        if configuration["revision"] == current_revision and self.configuration and configuration != self.configuration:
            raise ValueError("Displaykonfigurationens revision matcher ikke det allerede anvendte indhold")
        changed = configuration != self.configuration
        atomic_write_shared_json(CONFIG_PATH, configuration, mode=0o640, group_gid=self.shared_group_gid)
        self.configuration = configuration
        if changed:
            if configuration["kiosk_url"]:
                self.browser_requested = True
                self.stop_browser(preserve_request=True)
                self._clear_browser_profile(reason="configuration_change")
                self._countdown("countdown", CONFIGURATION_START_COUNTDOWN_SECONDS, reason="configuration_change")
                self.start_browser()
            else:
                self.browser_requested = False
                self.stop_browser()
        else:
            self._status("running" if self.browser and self.browser.poll() is None else "stopped")
        return {"applied": True, "revision": configuration["revision"]}

    @staticmethod
    def _run_text(command: list[str]) -> str:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
        if result.returncode != 0:
            raise RuntimeError(f"Kommando fejlede ({result.returncode}): {' '.join(command)}: {result.stderr.strip()}")
        return result.stdout.strip()

    @classmethod
    def _loginctl_value(cls, kind: str, ident: str, prop: str) -> str:
        return cls._run_text(["/usr/bin/loginctl", f"show-{kind}", ident, "-p", prop, "--value"]).strip()

    def _graphical_environment(self) -> dict[str, str]:
        uid = os.getuid()
        if uid == 0:
            raise RuntimeError("Display-runtime må ikke køre som root")
        account = pwd.getpwuid(uid)
        session_id = self._loginctl_value("seat", "seat0", "ActiveSession")
        if not session_id:
            raise RuntimeError("Ingen aktiv seat0-session")
        props = {
            key: self._loginctl_value("session", session_id, key)
            for key in ("Name", "User", "Seat", "Remote", "Class", "Type", "Active", "State", "LockedHint")
        }
        if props["Name"] != account.pw_name or props["User"] != str(uid):
            raise RuntimeError("Aktiv grafisk session tilhører ikke den konfigurerede kiosk-bruger")
        if props["Seat"] != "seat0" or props["Remote"] != "no" or props["Class"] != "user":
            raise RuntimeError("Aktiv session er ikke en lokal seat0-brugersession")
        if props["Type"] != "wayland" or props["Active"] != "yes" or props["State"] != "active":
            raise RuntimeError("Aktiv kiosk-session er ikke en aktiv Wayland-session")
        if props["LockedHint"] == "yes":
            raise RuntimeError("Aktiv kiosk-session er låst")

        runtime = Path(f"/run/user/{uid}")
        bus = runtime / "bus"
        try:
            bus_stat = bus.stat()
        except OSError as exc:
            raise RuntimeError("Kiosk-brugerens D-Bus session mangler") from exc
        if bus_stat.st_uid != uid or not stat.S_ISSOCK(bus_stat.st_mode):
            raise RuntimeError("Kiosk-brugerens D-Bus session er ugyldig")

        wayland_candidates: list[Path] = []
        for candidate in runtime.glob("wayland-*"):
            try:
                metadata = candidate.stat()
            except OSError:
                continue
            if metadata.st_uid == uid and stat.S_ISSOCK(metadata.st_mode):
                wayland_candidates.append(candidate)
        if not wayland_candidates:
            raise RuntimeError("Kiosk-brugerens Wayland-socket mangler")
        wayland_candidates.sort(key=lambda item: (item.name != "wayland-0", item.name))
        wayland = wayland_candidates[0]
        return {
            "HOME": account.pw_dir,
            "USER": account.pw_name,
            "LOGNAME": account.pw_name,
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": os.getenv("LANG", "C.UTF-8"),
            "XDG_RUNTIME_DIR": str(runtime),
            "WAYLAND_DISPLAY": wayland.name,
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}",
            "XDG_SESSION_TYPE": "wayland",
            "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
            "DESKTOP_SESSION": "ubuntu",
            "GDK_BACKEND": "wayland",
        }

    @staticmethod
    def _load_json_object(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _clear_stale_process_singleton(self) -> None:
        lock = PROFILE_DIR / "SingletonLock"
        if not lock.exists() and not lock.is_symlink():
            return
        if not lock.is_symlink():
            raise RuntimeError("Chrome SingletonLock er ikke et symlink; afviser profil-overtagelse")
        target = os.readlink(lock)
        host, separator, pid_text = target.rpartition("-")
        if not separator or not host or not pid_text.isdigit():
            raise RuntimeError("Chrome SingletonLock har ukendt format")
        pid = int(pid_text)
        if host == socket.gethostname():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise RuntimeError("Chrome-profilen ejes af en aktiv proces") from exc
            else:
                raise RuntimeError("Chrome-profilen ejes af en aktiv proces")
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            path = PROFILE_DIR / name
            if path.is_dir() and not path.is_symlink():
                raise RuntimeError(f"Chrome {name} er uventet et katalog")
            path.unlink(missing_ok=True)

    def _clear_browser_profile(self, *, reason: str) -> None:
        profile = PROFILE_DIR.resolve(strict=False)
        state = STATE_DIR.resolve(strict=False)
        if profile.parent != state or profile.name != "browser-profile":
            raise RuntimeError("Display-browserprofilens sti er ugyldig")
        self._status("resetting", step="clear_cookies", clear_reason=reason)
        if profile.exists():
            shutil.rmtree(profile, ignore_errors=False)

    def _prepare_profile(self, kiosk_url: str) -> None:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._clear_stale_process_singleton()
        default_dir = PROFILE_DIR / "Default"
        default_dir.mkdir(parents=True, exist_ok=True)
        for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs", "Preferences.tmp"):
            (default_dir / name).unlink(missing_ok=True)
        (PROFILE_DIR / "Local State.tmp").unlink(missing_ok=True)

        local_state_path = PROFILE_DIR / "Local State"
        local_state = self._load_json_object(local_state_path)
        local_state.setdefault("browser", {})["has_seen_welcome_page"] = True
        local_state.setdefault("browser", {})["enabled_labs_experiments"] = []
        local_state.setdefault("profile", {})["last_used"] = "Default"
        local_state.setdefault("profile", {})["last_active_profiles"] = ["Default"]
        atomic_write_json(local_state_path, local_state, mode=0o600)

        prefs_path = default_dir / "Preferences"
        prefs = self._load_json_object(prefs_path)
        profile = prefs.setdefault("profile", {})
        profile["exit_type"] = "Normal"
        profile["exited_cleanly"] = True
        profile["password_manager_enabled"] = False
        profile.setdefault("default_content_setting_values", {}).update(
            {"notifications": 2, "popups": 2, "geolocation": 2, "media_stream_mic": 2, "media_stream_camera": 2}
        )
        prefs["credentials_enable_service"] = False
        prefs["credentials_enable_autosignin"] = False
        prefs.setdefault("browser", {}).update(
            {"check_default_browser": False, "has_seen_welcome_page": True, "show_home_button": False}
        )
        prefs.setdefault("signin", {})["allowed"] = False
        prefs.setdefault("translate", {})["enabled"] = False
        prefs.setdefault("autofill", {}).update({"profile_enabled": False, "credit_card_enabled": False})
        prefs.setdefault("payments", {})["can_make_payment_enabled"] = False
        prefs.setdefault("session", {}).update(
            {"restore_on_startup": 4, "startup_urls": [kiosk_url], "restore_on_startup_migrated": True}
        )
        prefs.setdefault("extensions", {})["alerts_initialized"] = True
        atomic_write_json(prefs_path, prefs, mode=0o600)

    def _browser_command(self) -> tuple[list[str], dict[str, str]]:
        kiosk_url = self.configuration.get("kiosk_url") if self.configuration else None
        if not kiosk_url:
            raise RuntimeError("Displaykonfiguration mangler kiosk_url")
        if not CHROME_BINARY.exists() or not os.access(CHROME_BINARY, os.X_OK):
            raise RuntimeError("Canonical Google Chrome Stable executable mangler")
        environment = self._graphical_environment()
        self._prepare_profile(str(kiosk_url))
        command = [
            str(CHROME_BINARY),
            "--ozone-platform=wayland",
            "--start-fullscreen",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--noerrdialogs",
            "--disable-session-crashed-bubble",
            "--disable-infobars",
            "--disable-sync",
            "--password-store=basic",
            "--disable-notifications",
            "--deny-permission-prompts",
            "--disable-prompt-on-repost",
            "--disable-save-password-bubble",
            "--disable-component-update",
            "--disable-domain-reliability",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
            "--disable-search-engine-choice-screen",
            "--block-new-web-contents",
            "--disable-pinch",
            "--overscroll-history-navigation=0",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-features=Translate,TranslateUI,ChromeWhatsNewUI,PrivacySandboxSettings4,AutofillServerCommunication,PasswordManagerOnboarding,OptimizationHints,MediaRouter",
            str(kiosk_url),
        ]
        return command, environment

    def start_browser(self) -> dict[str, Any]:
        self.browser_requested = True
        if self.browser and self.browser.poll() is None:
            self._status("running")
            return {"started": False, "already_running": True, "pid": self.browser.pid}
        try:
            command, environment = self._browser_command()
            self.browser = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
        except (OSError, RuntimeError) as exc:
            self.browser = None
            self.next_start_attempt = time.monotonic() + 5.0
            self._status("waiting_session", error=str(exc)[:240])
            raise
        PID_PATH.write_text(f"{self.browser.pid}\n", encoding="ascii")
        self.next_start_attempt = 0.0
        self._status("running")
        return {"started": True, "pid": self.browser.pid}

    def request_start_browser(self, *, source: str) -> dict[str, Any]:
        source = str(source or "backend").strip().lower()
        if source not in {"backend", "gui", "calendar", "runtime"}:
            raise ValueError("Ukendt browser-startkilde")
        if self.browser and self.browser.poll() is None:
            return self.start_browser()
        self.browser_requested = True
        # Product contract: explicit backend/local-GUI Start is a clean start.
        # Calendar wake and internal runtime recovery preserve the profile.
        if source in {"backend", "gui"}:
            self._clear_browser_profile(reason=f"{source}_start")
            self._countdown("countdown", MANUAL_START_COUNTDOWN_SECONDS, reason=f"{source}_start")
        return self.start_browser()

    def stop_browser(self, *, preserve_request: bool = False) -> dict[str, Any]:
        if not preserve_request:
            self.browser_requested = False
        self.next_start_attempt = 0.0
        process = self.browser
        self.browser = None
        PID_PATH.unlink(missing_ok=True)
        if process is None or process.poll() is not None:
            self._status("stopped")
            return {"stopped": True, "was_running": False}
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        self._status("stopped")
        return {"stopped": True, "was_running": True}

    def restart_browser(self) -> dict[str, Any]:
        self.browser_requested = True
        self.stop_browser(preserve_request=True)
        result = self.start_browser()
        return {"restarted": True, **result}

    def reset_browser(self) -> dict[str, Any]:
        self.browser_requested = True
        self.stop_browser(preserve_request=True)
        self._clear_browser_profile(reason="reset_browser")
        self._countdown("countdown", RESET_BROWSER_COUNTDOWN_SECONDS, reason="reset_browser")
        result = self.start_browser()
        return {"reset": True, **result}

    def display_sleep_countdown(self) -> dict[str, Any]:
        self._countdown(
            "display_sleep_countdown",
            DISPLAY_SLEEP_COUNTDOWN_SECONDS,
            reason="display_power_off",
        )
        return {"countdown": True, "seconds": DISPLAY_SLEEP_COUNTDOWN_SECONDS}

    def _local_gui_environment(self) -> dict[str, str]:
        environment = self._graphical_environment()
        gui_root = STATE_DIR / "local-gui"
        for name in ("cache", "config", "data"):
            (gui_root / name).mkdir(parents=True, exist_ok=True)
        environment.update({
            "XDG_CACHE_HOME": str(gui_root / "cache"),
            "XDG_CONFIG_HOME": str(gui_root / "config"),
            "XDG_DATA_HOME": str(gui_root / "data"),
            "CLIENTFLOW_DISPLAY_RUNTIME_SOCKET": str(SOCKET_PATH),
            "CLIENTFLOW_GUI_STATUS_PATH": str(LOCAL_GUI_STATUS_PATH),
            "CLIENTFLOW_CALENDAR_PREVIEW_PATH": str(CALENDAR_PREVIEW_PATH),
            "CLIENTFLOW_DISPLAY_STATUS_PATH": str(STATUS_PATH),
        })
        client_id = str(os.getenv("CLIENTFLOW_CLIENT_ID") or "").strip()
        if client_id:
            environment["CLIENTFLOW_CLIENT_ID"] = client_id
        return environment

    def start_local_gui(self) -> dict[str, Any]:
        if self.local_gui and self.local_gui.poll() is None:
            return {"started": False, "already_running": True, "pid": self.local_gui.pid}
        if not SYSTEM_PYTHON.is_file() or not os.access(SYSTEM_PYTHON, os.X_OK):
            raise RuntimeError("Ubuntu system-Python mangler til ClientFlow GUI")
        if not LOCAL_GUI_SCRIPT.is_file() or LOCAL_GUI_SCRIPT.is_symlink():
            raise RuntimeError("ClientFlow local GUI mangler i releasepayload")
        environment = self._local_gui_environment()
        LOCAL_GUI_STATUS_PATH.unlink(missing_ok=True)
        self.local_gui = subprocess.Popen(
            [str(SYSTEM_PYTHON), str(LOCAL_GUI_SCRIPT)],
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            env=environment,
            start_new_session=False,
            close_fds=True,
        )
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.local_gui.poll() is not None:
                raise RuntimeError("ClientFlow local GUI afsluttede under opstart")
            status = self._load_json_object(LOCAL_GUI_STATUS_PATH)
            if status.get("state") == "running" and int(status.get("pid") or 0) == self.local_gui.pid:
                self.next_gui_start_attempt = 0.0
                return {"started": True, "pid": self.local_gui.pid}
            time.sleep(0.1)
        self.stop_local_gui()
        raise RuntimeError("ClientFlow local GUI blev ikke klar inden timeout")

    def stop_local_gui(self) -> None:
        process = self.local_gui
        self.local_gui = None
        LOCAL_GUI_STATUS_PATH.unlink(missing_ok=True)
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        LOCAL_GUI_STATUS_PATH.unlink(missing_ok=True)

    def _set_calendar_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        if int(payload.get("schema_version") or 0) != 1:
            raise ValueError("Calendar preview schema_version understøttes ikke")
        raw_days = payload.get("days")
        if not isinstance(raw_days, list) or len(raw_days) > 7:
            raise ValueError("Calendar preview skal indeholde højst 7 dage")
        days: list[dict[str, str]] = []
        for row in raw_days:
            if not isinstance(row, dict):
                raise ValueError("Calendar preview-dag er ugyldig")
            date = str(row.get("date") or "")[:10]
            status = str(row.get("status") or "").lower()
            if len(date) != 10 or status not in {"on", "off", "missing"}:
                raise ValueError("Calendar preview-dag er ugyldig")
            normalized = {"date": date, "status": status}
            if status == "on":
                normalized["onTime"] = str(row.get("onTime") or "")[:5]
                normalized["offTime"] = str(row.get("offTime") or "")[:5]
            days.append(normalized)
        atomic_write_shared_json(
            CALENDAR_PREVIEW_PATH,
            {"schema_version": 1, "days": days, "updated_at": time.time()},
            mode=0o640,
            group_gid=self.shared_group_gid,
        )
        return {"stored": True, "days": len(days)}

    def record_display_power(self, state: str) -> dict[str, Any]:
        if state not in {"on", "off"}:
            raise ValueError("Display power state skal være on eller off")
        self.display_power = state
        atomic_write_shared_json(
            LOCAL_DISPLAY_POWER_PATH,
            {"schema_version": 1, "state": state, "updated_at": time.time()},
            mode=0o640,
            group_gid=self.shared_group_gid,
        )
        current = "running" if self.browser and self.browser.poll() is None else "stopped"
        self._status(current, step="display_wake_complete" if state == "on" else "display_sleep_complete")
        return {"state": state}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = str(request.get("action") or "")
        if action == "apply_configuration":
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload skal være et objekt")
            return self.apply_configuration(payload)
        if action == "start_browser":
            payload = request.get("payload")
            source = str(payload.get("source") or "backend") if isinstance(payload, dict) else "backend"
            return self.request_start_browser(source=source)
        if action == "stop_browser":
            return self.stop_browser()
        if action == "reset_browser":
            return self.reset_browser()
        if action == "set_calendar_preview":
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload skal være et objekt")
            return self._set_calendar_preview(payload)
        if action == "record_display_power":
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload skal være et objekt")
            return self.record_display_power(str(payload.get("state") or ""))
        if action == "display_sleep_countdown":
            return self.display_sleep_countdown()
        if action == "status":
            return {
                "state": "running" if self.browser and self.browser.poll() is None else "stopped",
                "pid": self.browser.pid if self.browser and self.browser.poll() is None else None,
                "configuration_revision": self.configuration.get("revision") if self.configuration else None,
                "browser_requested": bool(self.browser_requested),
            }
        raise ValueError("Ukendt displayruntimehandling")

    def _open_server_socket(self) -> socket.socket:
        if self.shared_group_gid is None:
            raise RuntimeError("Display control-gruppen er ikke initialiseret")
        SOCKET_PATH.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(SOCKET_PATH))
            os.chown(SOCKET_PATH, -1, self.shared_group_gid)
            os.chmod(SOCKET_PATH, 0o660)
            server.listen(8)
            server.setblocking(False)
            return server
        except Exception:
            server.close()
            SOCKET_PATH.unlink(missing_ok=True)
            raise

    def run(self) -> int:
        self._prepare_shared_permissions()
        server = self._open_server_socket()
        selector = selectors.DefaultSelector()
        selector.register(server, selectors.EVENT_READ)
        self.boot_start_pending = bool(self.configuration.get("kiosk_url")) and self._boot_start_required()
        try:
            self.start_local_gui()
        except Exception:
            self.next_gui_start_attempt = time.monotonic() + 2.0
            self.logger.info("local_gui_start_waiting_for_session")
        if self.configuration.get("kiosk_url") and self.local_gui is not None:
            try:
                self._start_browser_with_boot_policy()
            except Exception:
                self.logger.exception("browser_start_waiting_for_session")
        else:
            self._status("stopped")
        try:
            while True:
                if self.browser and self.browser.poll() is not None:
                    code = self.browser.returncode
                    self.browser = None
                    PID_PATH.unlink(missing_ok=True)
                    self.next_start_attempt = time.monotonic() + 5.0
                    self._status("failed", exit_code=code, error="browser_exited")
                if self.local_gui and self.local_gui.poll() is not None:
                    code = self.local_gui.returncode
                    self.local_gui = None
                    LOCAL_GUI_STATUS_PATH.unlink(missing_ok=True)
                    self.next_gui_start_attempt = time.monotonic() + 2.0
                    self.logger.warning("local_gui_exited", extra={"event": str(code)})
                if self.local_gui is None and time.monotonic() >= self.next_gui_start_attempt:
                    try:
                        self.start_local_gui()
                    except Exception:
                        self.next_gui_start_attempt = time.monotonic() + 2.0
                if (
                    self.browser_requested
                    and self.configuration.get("kiosk_url")
                    and self.browser is None
                    and time.monotonic() >= self.next_start_attempt
                ):
                    try:
                        if self.local_gui is not None:
                            self._start_browser_with_boot_policy()
                    except Exception:
                        self.logger.info("browser_start_retry_waiting")
                for key, _ in selector.select(timeout=1):
                    connection, _ = key.fileobj.accept()
                    with connection:
                        connection.settimeout(30)
                        try:
                            result = self.handle(read_message(connection))
                            connection.sendall(encode_message({"ok": True, "result": result}))
                        except (RpcError, ValueError, RuntimeError, OSError) as exc:
                            connection.sendall(encode_message({"ok": False, "error": str(exc)}))
        except KeyboardInterrupt:
            return 0
        finally:
            self.stop_local_gui()
            self.stop_browser(preserve_request=True)
            server.close()
            SOCKET_PATH.unlink(missing_ok=True)


def main() -> int:
    return DisplayRuntime().run()
