"""Credential-free standard Terminal PTY broker running as its own Linux user."""
from __future__ import annotations

import base64
import fcntl
import os
from pathlib import Path
import pty
import signal
import socket
import struct
import subprocess
import termios
import threading
import time
import uuid
from typing import Any

from .logging_utils import configure_logging
from .socket_activation import activated_socket
from .transcript import OutputTranscript
from .unix_rpc import SocketJsonReader, encode_message

STATE_DIR = Path(os.getenv("CLIENTFLOW_STANDARD_TERMINAL_STATE_DIR", "/var/lib/clientflow/terminal-session"))
TRANSCRIPT_DIR = STATE_DIR / "transcripts"
MAX_STANDARD_SESSION_SECONDS = int(os.getenv("CLIENTFLOW_STANDARD_TERMINAL_MAX_SECONDS", "1800"))


def _resize(fd: int, cols: int, rows: int) -> None:
    if not 20 <= cols <= 500 or not 5 <= rows <= 200:
        raise ValueError("Terminalstørrelsen er ugyldig")
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _send(connection: socket.socket, lock: threading.Lock, payload: dict[str, Any]) -> None:
    with lock:
        connection.sendall(encode_message(payload))


def _handle_connection(connection: socket.socket) -> None:
    reader = SocketJsonReader(connection)
    request = reader.read()
    if request.get("action") != "open":
        raise RuntimeError("Standardbroker accepterer kun open")
    session_id = str(request.get("session_id") or "")
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise RuntimeError("Terminalsession-id er ugyldigt") from exc
    requested_timeout = int(request.get("timeout_seconds", MAX_STANDARD_SESSION_SECONDS))
    if requested_timeout <= 0:
        raise RuntimeError("Terminalsessionen er udløbet")
    timeout_seconds = min(requested_timeout, MAX_STANDARD_SESSION_SECONDS)
    cols = int(request.get("cols", 120))
    rows = int(request.get("rows", 32))
    transcript = OutputTranscript(TRANSCRIPT_DIR, session_id)
    master_fd, slave_fd = pty.openpty()
    _resize(master_fd, cols, rows)
    home = os.path.expanduser("~")
    environment = {
        "HOME": home,
        "USER": "clientflow-terminal-session",
        "LOGNAME": "clientflow-terminal-session",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TERM": "xterm-256color",
        "SHELL": "/bin/bash",
        "CLIENTFLOW_TERMINAL_SESSION_ID": session_id,
    }
    try:
        process = subprocess.Popen(
            ["/bin/bash", "--noprofile", "--norc"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=home,
            env=environment,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        os.close(slave_fd)
    send_lock = threading.Lock()
    _send(connection, send_lock, {"type": "accepted", "pid": process.pid})
    stop = threading.Event()

    def output_loop() -> None:
        try:
            while not stop.is_set():
                payload = os.read(master_fd, 65536)
                if not payload:
                    break
                transcript.append(payload)
                _send(
                    connection,
                    send_lock,
                    {"type": "output", "data_b64": base64.b64encode(payload).decode("ascii")},
                )
        except (OSError, BrokenPipeError):
            pass
        finally:
            stop.set()

    output_thread = threading.Thread(target=output_loop, daemon=True, name=f"standard-output-{session_id}")
    output_thread.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while not stop.is_set() and process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _send(connection, send_lock, {"type": "timeout"})
                break
            connection.settimeout(min(1.0, remaining))
            try:
                message = reader.read()
            except socket.timeout:
                continue
            action = str(message.get("action") or "")
            if action == "input":
                payload = base64.b64decode(str(message.get("data_b64") or ""), validate=True)
                if len(payload) > 1024 * 1024:
                    raise RuntimeError("Terminalinput er for stort")
                view = memoryview(payload)
                while view:
                    written = os.write(master_fd, view)
                    if written <= 0:
                        raise OSError("Terminalinput kunne ikke skrives")
                    view = view[written:]
            elif action == "resize":
                _resize(master_fd, int(message.get("cols", 120)), int(message.get("rows", 32)))
            elif action == "signal":
                signal_name = str(message.get("signal") or "")
                allowed = {
                    "SIGINT": signal.SIGINT,
                    "SIGTERM": signal.SIGTERM,
                    "SIGHUP": signal.SIGHUP,
                    "SIGWINCH": signal.SIGWINCH,
                }
                if signal_name not in allowed:
                    raise RuntimeError("Terminalsignalet er ikke tilladt")
                os.killpg(process.pid, allowed[signal_name])
            elif action == "close":
                break
            else:
                raise RuntimeError("Ukendt standardbrokerhandling")
    finally:
        stop.set()
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        try:
            os.close(master_fd)
        except OSError:
            pass
        output_thread.join(timeout=2)
        reference, digest = transcript.close()
        try:
            _send(
                connection,
                send_lock,
                {
                    "type": "exit",
                    "exit_code": process.returncode if process.returncode is not None else -1,
                    "transcript_reference": reference,
                    "transcript_sha256": digest,
                },
            )
        except OSError:
            pass


def main() -> int:
    logger = configure_logging("clientflow.standard-terminal.broker")
    server = activated_socket()
    while True:
        connection, _ = server.accept()

        def run(conn: socket.socket = connection) -> None:
            with conn:
                try:
                    _handle_connection(conn)
                except Exception:
                    logger.exception("standard_broker_session_rejected")
                    try:
                        conn.sendall(encode_message({"type": "rejected", "error": "standard_session_rejected"}))
                    except OSError:
                        pass

        threading.Thread(target=run, daemon=True).start()
