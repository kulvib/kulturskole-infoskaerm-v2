"""Generation-bound GNOME Mutter/PipeWire HLS producer.

The lifecycle watcher remains a hardened system service with no backend
credential. The actual desktop-capture child is dropped to the active local
Wayland user so it can use that GNOME session's Mutter ScreenCast D-Bus API and
PipeWire stream without an interactive XDG ScreenCast portal dialog.
"""
from __future__ import annotations

import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import time
from typing import Any
import uuid

from .atomic import atomic_write_json
from .livestream_paths import CONFIG_PATH, DESIRED_PATH, GENERATIONS_DIR, PRODUCER_STATUS_PATH, STATE_DIR
from .logging_utils import configure_logging

CONTROL_GROUP = "clientflow-livestream-control"
SETACL = Path("/usr/bin/setfacl")
SETPRIV = Path("/usr/bin/setpriv")
LOGINCTL = Path("/usr/bin/loginctl")
SYSTEM_PYTHON = Path("/usr/bin/python3")
CAPTURE_HELPER = Path(__file__).with_name("livestream_wayland_capture.py")


class Producer:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.livestream.producer")
        self.process: subprocess.Popen[bytes] | None = None
        self.generation_id: str | None = None
        self._last_start_attempt = 0.0

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ugyldig JSON: {path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"JSON skal være et objekt: {path}")
        return value

    def _status(self, state: str, **details: Any) -> None:
        atomic_write_json(
            PRODUCER_STATUS_PATH,
            {
                "schema_version": 1,
                "state": state,
                "generation_id": self.generation_id,
                "pid": self.process.pid if self.process and self.process.poll() is None else None,
                "capture_backend": "wayland_mutter_pipewire",
                "updated_at": time.time(),
                **details,
            },
            mode=0o640,
        )

    def _stop(self) -> None:
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
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
        self.generation_id = None

    def _session_properties(self, session_id: str) -> dict[str, str]:
        result = subprocess.run(
            [
                str(LOGINCTL),
                "show-session",
                session_id,
                "--no-pager",
                "-p", "Active",
                "-p", "Remote",
                "-p", "Type",
                "-p", "State",
                "-p", "Name",
                "-p", "Seat",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        return values

    def _resolve_wayland_user(self) -> tuple[str, int, int, str, Path]:
        if not LOGINCTL.is_file():
            raise RuntimeError("loginctl mangler")
        result = subprocess.run(
            [str(LOGINCTL), "list-sessions", "--no-legend", "--no-pager"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError("Kunne ikke læse grafiske login-sessioner")
        candidates: list[tuple[int, str, dict[str, str]]] = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if not fields:
                continue
            session_id = fields[0]
            properties = self._session_properties(session_id)
            if (
                properties.get("Active") != "yes"
                or properties.get("Remote") == "yes"
                or properties.get("Type") != "wayland"
                or properties.get("State") not in {"active", "online"}
            ):
                continue
            name = properties.get("Name") or ""
            if not name:
                continue
            priority = 0 if properties.get("Seat") == "seat0" else 1
            candidates.append((priority, session_id, properties))
        if not candidates:
            raise RuntimeError("Ingen aktiv lokal Wayland-session")
        candidates.sort(key=lambda item: (item[0], item[1]))
        properties = candidates[0][2]
        username = properties["Name"]
        try:
            account = pwd.getpwnam(username)
        except KeyError as exc:
            raise RuntimeError("Wayland-sessionens bruger findes ikke lokalt") from exc
        runtime_dir = Path(f"/run/user/{account.pw_uid}")
        if not (runtime_dir / "bus").exists():
            raise RuntimeError("Wayland-sessionens D-Bus er ikke klar")
        return username, account.pw_uid, account.pw_gid, account.pw_dir, runtime_dir

    def _control_gid(self) -> int:
        try:
            return grp.getgrnam(CONTROL_GROUP).gr_gid
        except KeyError as exc:
            raise RuntimeError(f"Gruppen {CONTROL_GROUP} mangler") from exc

    def _acl_traverse(self, username: str, path: Path) -> None:
        if not SETACL.is_file():
            raise RuntimeError("setfacl mangler")
        result = subprocess.run(
            [str(SETACL), "-m", f"u:{username}:--x", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Kunne ikke sætte afgrænset ACL på {path}: {result.stderr.strip()}")

    def _prepare_capture_state(self, username: str, uid: int) -> Path:
        """Create a private per-user cache area without granting home write access."""
        control_gid = self._control_gid()
        capture_root = STATE_DIR / "capture"
        user_root = capture_root / str(uid)
        capture_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(capture_root, 0, control_gid)
        os.chmod(capture_root, 0o750)
        self._acl_traverse(username, STATE_DIR)
        self._acl_traverse(username, capture_root)
        user_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(user_root, uid, control_gid)
        os.chmod(user_root, 0o700)
        cache_dir = user_root / "cache"
        cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(cache_dir, uid, control_gid)
        os.chmod(cache_dir, 0o700)
        return cache_dir

    def _prepare_output(self, generation_id: str, username: str, uid: int) -> Path:
        control_gid = self._control_gid()
        GENERATIONS_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(GENERATIONS_DIR, 0, control_gid)
        os.chmod(GENERATIONS_DIR, 0o750)
        self._acl_traverse(username, STATE_DIR)
        self._acl_traverse(username, GENERATIONS_DIR)

        generation = GENERATIONS_DIR / generation_id
        output = generation / "out"
        generation.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(generation, uid, control_gid)
        os.chmod(generation, 0o750)
        output.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(output, uid, control_gid)
        os.chmod(output, 0o2750)
        for child in output.iterdir():
            if child.is_symlink():
                child.unlink()
            elif child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
        return output

    def _configuration(self) -> tuple[int, int, str, int, int]:
        configuration = self._read_json(CONFIG_PATH)
        if configuration.get("schema_version") != 1:
            raise RuntimeError("Livestreamkonfiguration mangler schema_version 1")
        backend = str(configuration.get("capture_backend") or "wayland_mutter")
        if backend != "wayland_mutter":
            raise RuntimeError("capture_backend skal være wayland_mutter")
        fps = int(configuration.get("fps", 10))
        bitrate_kbit = int(configuration.get("bitrate_kbit", 12000))
        preset = str(configuration.get("preset") or "veryfast")
        segment_seconds = int(configuration.get("segment_seconds", 2))
        playlist_size = int(configuration.get("playlist_size", 8))
        if not 1 <= fps <= 30:
            raise RuntimeError("fps er ugyldig")
        if not 1000 <= bitrate_kbit <= 50000:
            raise RuntimeError("bitrate_kbit er ugyldig")
        if preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
            raise RuntimeError("preset er ugyldig")
        if not 1 <= segment_seconds <= 10:
            raise RuntimeError("segment_seconds er ugyldig")
        if not 3 <= playlist_size <= 30:
            raise RuntimeError("playlist_size er ugyldig")
        return fps, bitrate_kbit, preset, segment_seconds, playlist_size

    def _wait_ready(self, output: Path, timeout: float = 25.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process = self.process
            if process is None:
                raise RuntimeError("Wayland capture-processen forsvandt")
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"Wayland capture-processen stoppede med exit code {code}")
            playlist = output / "index.m3u8"
            if playlist.is_file() and any(output.glob("segment-*.ts")):
                return
            time.sleep(0.25)
        raise RuntimeError("Wayland capture blev ikke HLS-klar inden for 25 sekunder")

    def _start(self, generation_id: str) -> None:
        try:
            uuid.UUID(generation_id)
        except ValueError as exc:
            raise RuntimeError("Ugyldig livestreamgeneration") from exc
        for binary in (SETPRIV, SYSTEM_PYTHON, CAPTURE_HELPER):
            if binary.is_symlink() and binary != CAPTURE_HELPER:
                # System binaries may be usr-merged symlinks on some systems; regular existence is enough.
                pass
            if not binary.exists():
                raise RuntimeError(f"Påkrævet fil mangler: {binary}")

        fps, bitrate_kbit, preset, segment_seconds, playlist_size = self._configuration()
        username, uid, gid, home, runtime_dir = self._resolve_wayland_user()
        cache_dir = self._prepare_capture_state(username, uid)
        output = self._prepare_output(generation_id, username, uid)

        environment = {
            "HOME": home,
            "USER": username,
            "LOGNAME": username,
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "XDG_CACHE_HOME": str(cache_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
            "XDG_SESSION_TYPE": "wayland",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
        command = [
            str(SETPRIV),
            f"--reuid={uid}",
            f"--regid={gid}",
            "--init-groups",
            "--",
            str(SYSTEM_PYTHON),
            "-B",
            str(CAPTURE_HELPER),
            "--output", str(output),
            "--fps", str(fps),
            "--bitrate-kbit", str(bitrate_kbit),
            "--preset", preset,
            "--segment-seconds", str(segment_seconds),
            "--playlist-size", str(playlist_size),
        ]
        self.generation_id = generation_id
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            env=environment,
            cwd="/",
            start_new_session=True,
            close_fds=True,
        )
        self._status(
            "starting",
            graphical_user=username,
            fps=fps,
            bitrate_kbit=bitrate_kbit,
            preset=preset,
            segment_seconds=segment_seconds,
            playlist_size=playlist_size,
        )
        try:
            self._wait_ready(output)
        except Exception:
            self._stop()
            self.generation_id = generation_id
            raise
        self._status(
            "running",
            graphical_user=username,
            fps=fps,
            bitrate_kbit=bitrate_kbit,
            preset=preset,
            segment_seconds=segment_seconds,
            playlist_size=playlist_size,
        )

    def run(self) -> int:
        self._status("stopped")
        try:
            while True:
                desired = self._read_json(DESIRED_PATH)
                wanted = desired.get("desired")
                generation = str(desired.get("generation_id") or "")
                if wanted == "running" and generation:
                    if self.generation_id != generation or self.process is None or self.process.poll() is not None:
                        now = time.monotonic()
                        if now - self._last_start_attempt < 2.0:
                            time.sleep(0.25)
                            continue
                        self._last_start_attempt = now
                        self._stop()
                        try:
                            self._start(generation)
                        except Exception as exc:
                            self.logger.exception("producer_start_failed")
                            self.generation_id = generation
                            self._status("failed", error=str(exc)[:1000])
                else:
                    if self.process is not None or self.generation_id is not None:
                        self._stop()
                if self.process is not None and self.process.poll() is not None:
                    code = self.process.returncode
                    self.process = None
                    self._status("failed", exit_code=code)
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
        finally:
            self._stop()


def main() -> int:
    return Producer().run()
