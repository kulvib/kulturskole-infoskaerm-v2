"""Root-owned local broker for one-time, capability-bound root PTYs."""
from __future__ import annotations

import base64
import fcntl
import hashlib
import os
from pathlib import Path
import pty
import signal
import socket
import stat
import struct
import subprocess
import termios
import threading
import time
from typing import Any

import jwt

from .atomic import atomic_write_json
from .config import ClientIdentity, ConfigurationError, load_secure_json
from .logging_utils import configure_logging
from .socket_activation import activated_socket
from .transcript import OutputTranscript
from .unix_rpc import SocketJsonReader, encode_message

STATE_DIR = Path(os.getenv("CLIENTFLOW_ROOT_TERMINAL_STATE_DIR", "/var/lib/clientflow/root-terminal"))
REPLAY_PATH = STATE_DIR / "replay.json"
REPLAY_LOCK_PATH = STATE_DIR / "replay.lock"
TRANSCRIPT_DIR = STATE_DIR / "transcripts"
MAX_ROOT_SESSION_SECONDS = int(os.getenv("CLIENTFLOW_ROOT_TERMINAL_MAX_SECONDS", "600"))


def _credential_path(name: str) -> Path:
    directory = os.getenv("CREDENTIALS_DIRECTORY")
    if not directory:
        raise ConfigurationError("CREDENTIALS_DIRECTORY mangler")
    return Path(directory) / name


def _read_root_key() -> tuple[bytes, dict[str, str]]:
    try:
        payload = load_secure_json(_credential_path("root-grant.json"), forbidden_mode_bits=0o077)
        if payload.get("schema_version") != 1:
            raise ValueError("root-grant schema_version skal være 1")
        padding = "=" * (-len(str(payload["verification_key_b64"])) % 4)
        key = base64.urlsafe_b64decode(str(payload["verification_key_b64"]) + padding)
        contract = {
            "key_id": str(payload["key_id"]),
            "audience": str(payload["audience"]),
            "issuer": str(payload["issuer"]),
            "algorithm": str(payload["algorithm"]),
        }
    except (KeyError, TypeError, ValueError, ConfigurationError) as exc:
        raise ConfigurationError("root-grant.json er ugyldig") from exc
    if (
        contract["algorithm"] != "HS256"
        or not contract["key_id"]
        or len(contract["key_id"]) > 128
        or contract["audience"] != "clientflow-root-terminal-broker"
        or contract["issuer"] != "clientflow-backend"
        or len(key) != 32
    ):
        raise ConfigurationError("Root-grant kontrakt eller nøgle er ugyldig")
    return key, contract


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = STATE_DIR.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("Root-terminal state-katalog er ugyldigt")
    os.chmod(STATE_DIR, 0o700)


def _load_replay_state() -> dict[str, int]:
    try:
        metadata = REPLAY_PATH.lstat()
    except FileNotFoundError:
        return {}
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode & 0o077
    ):
        raise RuntimeError("Root-grant replay-state er beskadiget")
    try:
        raw = load_secure_json(REPLAY_PATH, max_bytes=2 * 1024 * 1024, forbidden_mode_bits=0o077)
    except ConfigurationError as exc:
        raise RuntimeError("Root-grant replay-state er beskadiget") from exc
    value: dict[str, int] = {}
    try:
        for key, expiry in raw.items():
            if not isinstance(key, str) or len(key) != 64:
                raise ValueError
            value[key] = int(expiry)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Root-grant replay-state er beskadiget") from exc
    return value


def _consume_replay(token: str, expires_at: int) -> None:
    _ensure_state_dir()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    lock_fd = os.open(REPLAY_LOCK_PATH, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        value = _load_replay_state()
        now = int(time.time())
        value = {key: expiry for key, expiry in value.items() if expiry > now}
        if token_hash in value:
            raise RuntimeError("Root-grant er allerede forbrugt")
        value[token_hash] = expires_at
        atomic_write_json(REPLAY_PATH, value, mode=0o600)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _verify_grant(token: str, session_id: str) -> dict[str, Any]:
    identity = ClientIdentity.load(_credential_path("identity.json"))
    key, contract = _read_root_key()
    header = jwt.get_unverified_header(token)
    if header.get("kid") != contract["key_id"] or header.get("alg") != "HS256":
        raise RuntimeError("Root-grant key ID eller algoritme er ugyldig")
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=contract["audience"],
            issuer=contract["issuer"],
            options={"require": ["exp", "iat", "nbf", "jti", "grant_id", "session_id", "client_id", "credential_id", "capability"]},
        )
    except jwt.PyJWTError as exc:
        raise RuntimeError("Root-grant signatur eller claims er ugyldige") from exc
    if (
        str(claims.get("session_id")) != session_id
        or int(claims.get("client_id", 0)) != identity.client_id
        or str(claims.get("credential_id")) != identity.terminal_credential_id
        or claims.get("capability") != "root_pty"
        or claims.get("sub") != f"root-terminal:{session_id}"
    ):
        raise RuntimeError("Root-grant er bundet til en anden klient eller session")
    _consume_replay(token, int(claims["exp"]))
    return claims


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
        raise RuntimeError("Rootbroker accepterer kun open")
    session_id = str(request.get("session_id") or "")
    token = str(request.get("root_grant") or "")
    claims = _verify_grant(token, session_id)
    requested_timeout = int(request.get("timeout_seconds", MAX_ROOT_SESSION_SECONDS))
    grant_remaining = int(claims["exp"]) - int(time.time())
    if requested_timeout <= 0 or grant_remaining <= 0:
        raise RuntimeError("Rootsessionen er udløbet")
    timeout_seconds = min(requested_timeout, MAX_ROOT_SESSION_SECONDS, grant_remaining)
    cols = int(request.get("cols", 120))
    rows = int(request.get("rows", 32))
    transcript = OutputTranscript(TRANSCRIPT_DIR, session_id)
    master_fd, slave_fd = pty.openpty()
    _resize(master_fd, cols, rows)
    environment = {
        "HOME": "/root",
        "USER": "root",
        "LOGNAME": "root",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "TERM": "xterm-256color",
        "SHELL": "/bin/bash",
        "CLIENTFLOW_ROOT_TERMINAL_SESSION_ID": session_id,
    }
    try:
        process = subprocess.Popen(
            ["/bin/bash", "--noprofile", "--norc"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd="/root",
            env=environment,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        os.close(slave_fd)
    send_lock = threading.Lock()
    _send(connection, send_lock, {"type": "accepted", "grant_id": claims["grant_id"], "pid": process.pid})
    stop = threading.Event()

    def output_loop() -> None:
        try:
            while not stop.is_set():
                payload = os.read(master_fd, 65536)
                if not payload:
                    break
                transcript.append(payload)
                _send(connection, send_lock, {"type": "output", "data_b64": base64.b64encode(payload).decode("ascii")})
        except (OSError, BrokenPipeError):
            pass
        finally:
            stop.set()

    output_thread = threading.Thread(target=output_loop, daemon=True, name=f"root-output-{session_id}")
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
                allowed = {"SIGINT": signal.SIGINT, "SIGTERM": signal.SIGTERM, "SIGHUP": signal.SIGHUP, "SIGWINCH": signal.SIGWINCH}
                if signal_name not in allowed:
                    raise RuntimeError("Terminalsignalet er ikke tilladt")
                os.killpg(process.pid, allowed[signal_name])
            elif action == "close":
                break
            else:
                raise RuntimeError("Ukendt rootbrokerhandling")
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
    logger = configure_logging("clientflow.root-terminal.broker")
    server = activated_socket()
    while True:
        connection, _ = server.accept()

        def run(conn: socket.socket = connection) -> None:
            with conn:
                try:
                    _handle_connection(conn)
                except Exception:
                    logger.exception("root_broker_session_rejected")
                    try:
                        conn.sendall(encode_message({"type": "rejected", "error": "root_grant_rejected"}))
                    except OSError:
                        pass

        threading.Thread(target=run, daemon=True).start()
