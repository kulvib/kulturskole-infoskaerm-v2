"""Unprivileged, network-isolated Remote Desktop capture broker.

The broker owns no backend credential and has no cross-domain runtime
relationship.  It serves the existing local Unix RPC contract and delegates
GNOME capture to a Remote-Desktop-owned system-Python worker because PyGObject
is supplied by Ubuntu rather than the ClientFlow virtualenv.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
from pathlib import Path
import pwd
import select
import stat
import subprocess
import threading
from typing import Any

from .server import serve_forever
from .socket_activation import activated_socket

CONFIG_PATH = Path(os.getenv("CLIENTFLOW_REMOTE_DESKTOP_CONFIG", "/etc/clientflow/remote-desktop.json"))
MAX_FRAME_BYTES = 8 * 1024 * 1024
SYSTEM_PYTHON = Path("/usr/bin/python3")
MUTTER_WORKER = Path(__file__).with_name("remote_desktop_mutter_worker.py")
SHOUT_HELPER = Path(__file__).with_name("remote_desktop_shout.py")
CAPTURE_BINARIES = {
    "grim": Path("/usr/bin/grim"),
    "ffmpeg-x11": Path("/usr/bin/ffmpeg"),
}


def _trusted_executable(path: Path, *, name: str) -> str:
    """Resolve a distro-managed executable without rejecting legitimate symlinks."""
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise RuntimeError(f"{name} blev ikke fundet") from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise RuntimeError(f"{name} er ikke en eksekverbar fil")
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise RuntimeError(f"{name} har usikre ejer- eller skriverettigheder")
    return str(resolved)


def _trusted_worker(path: Path) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError("Remote Desktop Mutter-worker mangler") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("Remote Desktop Mutter-worker er ikke en fast fil")
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise RuntimeError("Remote Desktop Mutter-worker har usikre rettigheder")
    return str(path)


def _configuration() -> dict[str, Any]:
    try:
        metadata = CONFIG_PATH.lstat()
        if CONFIG_PATH.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o022:
            raise RuntimeError("Remote Desktop capture-konfigurationens rettigheder er ugyldige")
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Remote Desktop capture-konfiguration er ugyldig") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("Remote Desktop capture-konfiguration skal bruge schema_version 1")
    return value


def _kiosk_account(configuration: dict[str, Any]) -> pwd.struct_passwd:
    kiosk_user = str(configuration.get("kiosk_user") or "").strip()
    if not kiosk_user:
        raise RuntimeError("Remote Desktop capture mangler kiosk_user")
    try:
        account = pwd.getpwnam(kiosk_user)
    except KeyError as exc:
        raise RuntimeError("Remote Desktop kiosk_user findes ikke lokalt") from exc
    if os.geteuid() != account.pw_uid:
        raise RuntimeError("Remote Desktop capture-helper kører ikke som kiosk-brugeren")
    return account


def _session_environment(configuration: dict[str, Any], account: pwd.struct_passwd) -> dict[str, str]:
    runtime_dir = str(configuration.get("xdg_runtime_dir") or f"/run/user/{account.pw_uid}")
    environment = {
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": runtime_dir,
        "DBUS_SESSION_BUS_ADDRESS": str(
            configuration.get("dbus_session_bus_address") or f"unix:path={runtime_dir}/bus"
        ),
    }
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE"):
        value = configuration.get(key.lower()) or configuration.get(key)
        if value:
            environment[key] = str(value)
    return environment


def _run_direct(command: list[str], environment: dict[str, str], *, timeout: float) -> bytes:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Capture fejlede: {error}")
    if not completed.stdout or len(completed.stdout) > MAX_FRAME_BYTES:
        raise RuntimeError("Capture returnerede en tom eller for stor frame")
    return completed.stdout


class _MutterWorkerClient:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.environment_key: tuple[tuple[str, str], ...] | None = None

    def _stop_locked(self) -> None:
        process = self.process
        self.process = None
        self.environment_key = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def close(self) -> None:
        with self.lock:
            self._stop_locked()

    def _ensure_locked(self, environment: dict[str, str]) -> subprocess.Popen[str]:
        key = tuple(sorted(environment.items()))
        process = self.process
        if process is not None and process.poll() is None and self.environment_key == key:
            return process
        self._stop_locked()
        python = _trusted_executable(SYSTEM_PYTHON, name="system-python3")
        worker = _trusted_worker(MUTTER_WORKER)
        process = subprocess.Popen(
            [python, worker],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=environment,
        )
        if process.stdin is None or process.stdout is None:
            process.kill()
            raise RuntimeError("Remote Desktop Mutter-worker kunne ikke åbne IPC")
        self.process = process
        self.environment_key = key
        return process

    @staticmethod
    def _read_response(process: subprocess.Popen[str], *, timeout: float) -> dict[str, Any]:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout.fileno()], [], [], timeout)
        if not ready:
            raise TimeoutError("Remote Desktop Mutter-worker svarede ikke")
        raw = process.stdout.readline()
        if not raw:
            raise RuntimeError(f"Remote Desktop Mutter-worker stoppede med kode {process.poll()}")
        if len(raw) > 12 * 1024 * 1024:
            raise RuntimeError("Remote Desktop Mutter-worker returnerede et for stort svar")
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Remote Desktop Mutter-worker returnerede ugyldig JSON") from exc
        if not isinstance(response, dict):
            raise RuntimeError("Remote Desktop Mutter-worker returnerede ugyldigt svar")
        return response

    def capture(
        self,
        *,
        environment: dict[str, str],
        width: int,
        height: int,
        quality: int,
        monitor: str | None,
        native: bool = False,
    ) -> dict[str, Any]:
        request = {
            "action": "capture",
            "width": width,
            "height": height,
            "quality": quality,
            "native": bool(native),
        }
        if monitor:
            request["monitor"] = monitor

        with self.lock:
            for attempt in range(2):
                process = self._ensure_locked(environment)
                assert process.stdin is not None
                try:
                    process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                    process.stdin.flush()
                    response = self._read_response(process, timeout=12)
                except (BrokenPipeError, OSError, TimeoutError, RuntimeError):
                    self._stop_locked()
                    if attempt == 0:
                        continue
                    raise
                if response.get("ok") is not True:
                    raise RuntimeError(str(response.get("error") or "Mutter/PipeWire capture fejlede"))
                data = str(response.get("data") or "")
                if not data or len(data) > ((MAX_FRAME_BYTES * 4) // 3 + 16):
                    raise RuntimeError("Mutter/PipeWire returnerede en tom eller for stor frame")
                actual_width = int(response.get("width") or width)
                actual_height = int(response.get("height") or height)
                return {
                    "encoding": "base64",
                    "mime_type": "image/jpeg",
                    "data": data,
                    "width": actual_width,
                    "height": actual_height,
                    "screen_width": int(response.get("screen_width") or actual_width),
                    "screen_height": int(response.get("screen_height") or actual_height),
                    "monitor": response.get("monitor"),
                }
        raise RuntimeError("Mutter/PipeWire capture fejlede")

    def control(self, *, environment: dict[str, str], action: str) -> dict[str, Any]:
        if action != "stop_capture":
            raise ValueError("Ukendt Mutter-worker control-action")
        key = tuple(sorted(environment.items()))
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                self._stop_locked()
                return {"accepted": True, "action": action, "worker_running": False}
            if self.environment_key != key:
                self._stop_locked()
                return {"accepted": True, "action": action, "worker_running": False}
            assert process.stdin is not None
            try:
                process.stdin.write(json.dumps({"action": action}, separators=(",", ":")) + "\n")
                process.stdin.flush()
                response = self._read_response(process, timeout=5)
            except (BrokenPipeError, OSError, TimeoutError, RuntimeError):
                self._stop_locked()
                return {"accepted": True, "action": action, "worker_running": False}
            if response.get("ok") is not True:
                raise RuntimeError(str(response.get("error") or "Mutter-worker lifecycle fejlede"))
            return {"accepted": True, "action": action, "worker_running": True}

    def text(self, *, environment: dict[str, str], text: str) -> dict[str, Any]:
        request = {"action": "text", "text": text}
        with self.lock:
            for attempt in range(2):
                process = self._ensure_locked(environment)
                assert process.stdin is not None
                try:
                    process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                    process.stdin.flush()
                    response = self._read_response(process, timeout=12)
                except (BrokenPipeError, OSError, TimeoutError, RuntimeError):
                    self._stop_locked()
                    if attempt == 0:
                        continue
                    raise
                if response.get("ok") is not True:
                    raise RuntimeError(str(response.get("error") or "Mutter Unicode-input fejlede"))
                return {"accepted": True, "action": "text", "characters": int(response.get("characters") or len(text))}
        raise RuntimeError("Mutter Unicode-input fejlede")


_MUTTER = _MutterWorkerClient()
atexit.register(_MUTTER.close)


class _ShoutClient:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[bytes] | None = None

    def close(self) -> None:
        with self.lock:
            process = self.process
            self.process = None
            if process is None or process.poll() is not None:
                return
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def show(self, *, environment: dict[str, str], text: str, duration: int) -> dict[str, Any]:
        if not text or len(text) > 120:
            raise ValueError("Shout-beskeden skal være 1-120 tegn")
        duration = max(3, min(30, int(duration)))
        python = _trusted_executable(SYSTEM_PYTHON, name="system-python3")
        helper = _trusted_worker(SHOUT_HELPER)
        payload = json.dumps({"text": text, "duration": duration}, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            previous = self.process
            if previous is not None and previous.poll() is None:
                try:
                    previous.terminate()
                except Exception:
                    pass
            process = subprocess.Popen(
                [python, helper, payload],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=None,
                env=environment,
            )
            self.process = process
            try:
                returncode = process.wait(timeout=0.35)
            except subprocess.TimeoutExpired:
                return {"accepted": True, "action": "shout", "duration": duration}
            self.process = None
            if returncode != 0:
                raise RuntimeError(f"Remote Desktop shout stoppede straks med kode {returncode}")
            return {"accepted": True, "action": "shout", "duration": duration}


_SHOUT = _ShoutClient()
atexit.register(_SHOUT.close)


def _handle(request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("action") or "")
    configuration = _configuration()
    account = _kiosk_account(configuration)
    environment = _session_environment(configuration, account)
    backend = str(configuration.get("capture_backend") or "mutter-pipewire").strip().lower()

    if action == "text":
        if backend != "mutter-pipewire":
            raise RuntimeError("Unicode-tekst kræver Mutter RemoteDesktop")
        text = str(request.get("text") or "")
        if len(text) > 1000:
            raise ValueError("Tekstinput er for langt")
        return _MUTTER.text(environment=environment, text=text)

    if action == "shout":
        text = str(request.get("text") or "").strip()
        duration = max(3, min(30, int(request.get("duration") or 8)))
        return _SHOUT.show(environment=environment, text=text, duration=duration)

    if action == "stop_capture":
        if backend != "mutter-pipewire":
            return {"accepted": True, "action": action, "worker_running": False}
        return _MUTTER.control(environment=environment, action=action)

    if action == "close_worker":
        _MUTTER.close()
        return {"accepted": True, "action": action, "worker_running": False}

    if action != "capture":
        raise ValueError("Remote Desktop-helper accepterer kun capture, text, shout, stop_capture og close_worker")

    native = bool(request.get("native", False))
    width = int(request.get("width", 1280))
    height = int(request.get("height", 720))
    quality = int(request.get("quality", 85))
    if (not native and (not 320 <= width <= 7680 or not 200 <= height <= 4320)) or not 20 <= quality <= 95:
        raise ValueError("Capture-dimensioner eller kvalitet er ugyldige")

    if backend == "mutter-pipewire":
        monitor_raw = configuration.get("monitor") or configuration.get("monitor_connector")
        monitor = str(monitor_raw).strip() if monitor_raw else None
        return _MUTTER.capture(
            environment=environment,
            width=width,
            height=height,
            quality=quality,
            monitor=monitor,
            native=native,
        )

    if backend == "grim":
        binary = _trusted_executable(CAPTURE_BINARIES[backend], name="grim")
        frame = _run_direct([binary, "-t", "jpeg", "-q", str(quality), "-"], environment, timeout=10)
    elif backend == "ffmpeg-x11":
        binary = _trusted_executable(CAPTURE_BINARIES[backend], name="ffmpeg")
        display = environment.get("DISPLAY")
        if not display:
            raise RuntimeError("ffmpeg-x11 kræver DISPLAY")
        screen_width = int(request.get("screen_width", width))
        screen_height = int(request.get("screen_height", height))
        if not width <= screen_width <= 7680 or not height <= screen_height <= 4320:
            raise ValueError("Skærmdimensionerne er ugyldige")
        frame = _run_direct(
            [
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "x11grab",
                "-video_size",
                f"{screen_width}x{screen_height}",
                "-i",
                display,
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                "-q:v",
                str(max(2, min(31, round((100 - quality) / 3.2)))),
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            environment,
            timeout=10,
        )
    else:
        raise RuntimeError("Ukendt capture_backend")

    return {
        "encoding": "base64",
        "mime_type": "image/jpeg",
        "data": base64.b64encode(frame).decode("ascii"),
    }


def main() -> int:
    serve_forever(
        activated_socket(),
        _handle,
        name="clientflow.remote-desktop.capture",
        connection_timeout=15,
    )
    return 0
