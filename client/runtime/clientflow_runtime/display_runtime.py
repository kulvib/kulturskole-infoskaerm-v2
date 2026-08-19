"""Unprivileged display runtime. It controls only the kiosk browser process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import time
from typing import Any

from .atomic import atomic_write_json
from .logging_utils import configure_logging
from .unix_rpc import RpcError, encode_message, read_message

STATE_DIR = Path(os.getenv("CLIENTFLOW_DISPLAY_STATE_DIR", "/var/lib/clientflow/display"))
RUNTIME_DIR = Path(os.getenv("CLIENTFLOW_DISPLAY_RUNTIME_DIR", "/run/clientflow/display"))
CONFIG_PATH = STATE_DIR / "configuration.json"
SOCKET_PATH = RUNTIME_DIR / "runtime.sock"
STATUS_PATH = STATE_DIR / "runtime-status.json"
PID_PATH = RUNTIME_DIR / "browser.pid"

_BROWSER_BINARIES = {
    "chromium": Path("/usr/bin/chromium"),
    "chromium-browser": Path("/usr/bin/chromium-browser"),
    "google-chrome-stable": Path("/usr/bin/google-chrome-stable"),
}
_ALLOWED_BROWSER_BINARIES = frozenset(_BROWSER_BINARIES)

_ALLOWED_CONFIGURATION_KEYS = {
    "kiosk_url",
    "browser_refresh_interval_sec",
    "browser_binary",
    "browser_arguments",
    "display_environment",
}


class DisplayRuntime:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.display.runtime")
        self.browser: subprocess.Popen[bytes] | None = None
        self.configuration: dict[str, Any] = self._load_configuration()

    def _load_configuration(self) -> dict[str, Any]:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Displaykonfiguration er ugyldig") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Displaykonfiguration skal være et objekt")
        return data

    def _status(self, state: str, **details: Any) -> None:
        payload = {
            "schema_version": 1,
            "state": state,
            "browser_pid": self.browser.pid if self.browser and self.browser.poll() is None else None,
            "updated_at": time.time(),
            **details,
        }
        atomic_write_json(STATUS_PATH, payload, mode=0o640)

    def _validate_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        unknown = set(payload) - _ALLOWED_CONFIGURATION_KEYS
        if unknown:
            raise ValueError(f"Ukendte displayfelter: {', '.join(sorted(unknown))}")
        kiosk_url = str(payload.get("kiosk_url") or "").strip()
        if not kiosk_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("kiosk_url skal bruge HTTPS")
        interval = int(payload.get("browser_refresh_interval_sec", 900))
        if not 30 <= interval <= 86400:
            raise ValueError("browser_refresh_interval_sec er uden for interval")
        browser_arguments = payload.get("browser_arguments", [])
        if not isinstance(browser_arguments, list) or any(not isinstance(item, str) for item in browser_arguments):
            raise ValueError("browser_arguments skal være en liste af strenge")
        forbidden = {"--remote-debugging-address", "--remote-debugging-port", "--user-data-dir"}
        if any(any(argument == item or argument.startswith(item + "=") for item in forbidden) for argument in browser_arguments):
            raise ValueError("browser_arguments indeholder en forbudt kontrolparameter")
        environment = payload.get("display_environment", {})
        if not isinstance(environment, dict):
            raise ValueError("display_environment skal være et objekt")
        allowed_env = {"DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}
        if set(environment) - allowed_env or any(not isinstance(value, str) for value in environment.values()):
            raise ValueError("display_environment indeholder ugyldige værdier")
        browser_binary = str(payload.get("browser_binary") or "chromium").strip()
        if browser_binary not in _ALLOWED_BROWSER_BINARIES:
            raise ValueError("browser_binary er ikke tilladt")
        return {
            "kiosk_url": kiosk_url,
            "browser_refresh_interval_sec": interval,
            "browser_binary": browser_binary,
            "browser_arguments": browser_arguments,
            "display_environment": environment,
        }

    def apply_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        configuration = self._validate_configuration(payload)
        atomic_write_json(CONFIG_PATH, configuration, mode=0o640)
        self.configuration = configuration
        self.restart_browser()
        return {"applied": True}

    def _browser_command(self) -> tuple[list[str], dict[str, str]]:
        if not self.configuration:
            raise RuntimeError("Displaykonfiguration mangler")
        requested = str(self.configuration.get("browser_binary") or "chromium")
        if requested not in _ALLOWED_BROWSER_BINARIES:
            raise RuntimeError("Browserbinary er ikke tilladt")
        binary_path = _BROWSER_BINARIES[requested]
        if binary_path.is_symlink() or not binary_path.is_file() or not os.access(binary_path, os.X_OK):
            raise RuntimeError(f"Browserbinary blev ikke fundet som fast fil: {requested}")
        binary = str(binary_path)
        data_dir = STATE_DIR / "browser-profile"
        data_dir.mkdir(parents=True, exist_ok=True)
        command = [
            binary,
            "--kiosk",
            "--no-first-run",
            "--disable-component-update",
            "--disable-features=TranslateUI",
            f"--user-data-dir={data_dir}",
            *list(self.configuration.get("browser_arguments") or []),
            str(self.configuration["kiosk_url"]),
        ]
        environment = {
            "HOME": str(STATE_DIR),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": os.getenv("LANG", "C.UTF-8"),
        }
        environment.update(dict(self.configuration.get("display_environment") or {}))
        return command, environment

    def start_browser(self) -> None:
        if self.browser and self.browser.poll() is None:
            return
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
        PID_PATH.write_text(f"{self.browser.pid}\n", encoding="ascii")
        self._status("running")

    def stop_browser(self) -> None:
        process = self.browser
        self.browser = None
        PID_PATH.unlink(missing_ok=True)
        if process is None or process.poll() is not None:
            self._status("stopped")
            return
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

    def restart_browser(self) -> None:
        self.stop_browser()
        self.start_browser()

    def reload_browser(self) -> None:
        # The runtime intentionally exposes no browser debugging socket. A controlled
        # process restart is the deterministic reload primitive.
        self.restart_browser()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = str(request.get("action") or "")
        if action == "apply_configuration":
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload skal være et objekt")
            return self.apply_configuration(payload)
        if action == "reload_browser":
            self.reload_browser()
            return {"reloaded": True}
        if action == "restart_browser":
            self.restart_browser()
            return {"restarted": True}
        if action == "status":
            return {
                "state": "running" if self.browser and self.browser.poll() is None else "stopped",
                "pid": self.browser.pid if self.browser and self.browser.poll() is None else None,
            }
        raise ValueError("Ukendt displayruntimehandling")

    def run(self) -> int:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        SOCKET_PATH.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o660)
        server.listen(8)
        server.setblocking(False)
        selector = selectors.DefaultSelector()
        selector.register(server, selectors.EVENT_READ)
        if self.configuration:
            try:
                self.start_browser()
            except Exception:
                self.logger.exception("browser_start_failed")
                self._status("failed", error="browser_start_failed")
        try:
            while True:
                if self.browser and self.browser.poll() is not None:
                    code = self.browser.returncode
                    self.browser = None
                    PID_PATH.unlink(missing_ok=True)
                    self._status("failed", exit_code=code)
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
            self.stop_browser()
            server.close()
            SOCKET_PATH.unlink(missing_ok=True)


def main() -> int:
    return DisplayRuntime().run()
