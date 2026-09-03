"""Root-owned fixed-function broker for privileged system operations."""
from __future__ import annotations

import base64
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import stat
import time
import subprocess
import uuid
from typing import Any

from .atomic import atomic_write_json
from .config import ConfigurationError, load_secure_json
from .server import serve_forever
from .socket_activation import activated_socket

_HOSTNAME_RE = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_FIXED_BINARIES = {
    "systemctl": Path("/usr/bin/systemctl"),
    "hostnamectl": Path("/usr/bin/hostnamectl"),
    "chpasswd": Path("/usr/sbin/chpasswd"),
    "openssl": Path("/usr/bin/openssl"),
}
STATE_DIR = Path(os.getenv("CLIENTFLOW_SYSTEM_BROKER_STATE_DIR", "/var/lib/clientflow/system-broker"))
JOURNAL_PATH = STATE_DIR / "command-journal.json"
JOURNAL_LOCK_PATH = STATE_DIR / "command-journal.lock"
JOURNAL_RETENTION_SECONDS = 90 * 24 * 60 * 60
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
BOOT_BOUNDARY_ACTIONS = frozenset({"reboot", "shutdown"})

ALLOWED_ACTIONS = frozenset({
    "update_os",
    "reboot",
    "shutdown",
    "change_hostname",
    "change_password",
})


def _credential_path(name: str) -> Path:
    directory = os.getenv("CREDENTIALS_DIRECTORY")
    if not directory:
        raise RuntimeError("CREDENTIALS_DIRECTORY mangler")
    return Path(directory) / name


def _run(command: list[str], *, timeout: float, input_bytes: bytes | None = None) -> dict[str, Any]:
    run_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "timeout": timeout,
        "check": False,
        "env": {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    }
    if input_bytes is None:
        run_kwargs["stdin"] = subprocess.DEVNULL
    else:
        run_kwargs["input"] = input_bytes
    completed = subprocess.run(command, **run_kwargs)
    output = completed.stdout.decode("utf-8", errors="replace")[:4000]
    if completed.returncode != 0:
        raise RuntimeError(f"Systemhelper fejlede med kode {completed.returncode}: {output}")
    return {"exit_code": completed.returncode, "output": output}


def _fixed_binary(name: str) -> str:
    path = _FIXED_BINARIES.get(name)
    if path is None or not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"Påkrævet fast systembinary blev ikke fundet: {name}")
    return str(path)


def _decrypt_password(
    payload: dict[str, Any],
    *,
    client_id: int,
    command_id: str,
) -> tuple[str, str]:
    target_user = str(payload.get("target_user") or "")
    try:
        pwd.getpwnam(target_user)
    except KeyError as exc:
        raise ValueError("Målbrugeren findes ikke") from exc
    envelope = payload.get("encrypted_payload")
    if not isinstance(envelope, dict) or envelope.get("algorithm") != "RSA-OAEP-SHA256":
        raise ValueError("Passwordpayload bruger ikke RSA-OAEP-SHA256")
    try:
        ciphertext = base64.b64decode(str(envelope["ciphertext_b64"]), validate=True)
    except (KeyError, ValueError) as exc:
        raise ValueError("Passwordciphertext er ugyldig") from exc
    if not 64 <= len(ciphertext) <= 8192:
        raise ValueError("Passwordciphertext har ugyldig størrelse")
    private_key = _credential_path("system-private-key.pem")
    openssl = _fixed_binary("openssl")
    completed = subprocess.run(
        [
            openssl,
            "pkeyutl",
            "-decrypt",
            "-inkey",
            str(private_key),
            "-pkeyopt",
            "rsa_padding_mode:oaep",
            "-pkeyopt",
            "rsa_oaep_md:sha256",
            "-pkeyopt",
            "rsa_mgf1_md:sha256",
        ],
        input=ciphertext,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if completed.returncode != 0:
        raise RuntimeError("Passwordpayload kunne ikke dekrypteres")
    try:
        decrypted = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Dekrypteret passwordpayload er ugyldig") from exc
    if (
        not isinstance(decrypted, dict)
        or decrypted.get("target_user") != target_user
        or int(decrypted.get("client_id", 0)) != client_id
        or str(decrypted.get("command_id") or "") != command_id
    ):
        raise RuntimeError("Passwordpayload er bundet til en anden klient, kommando eller bruger")
    password = str(decrypted.get("new_password") or "")
    if not 12 <= len(password) <= 256 or "\n" in password or "\x00" in password:
        raise ValueError("Den nye adgangskode opfylder ikke længdekravet")
    return target_user, password


class SystemCommandInDoubt(RuntimeError):
    pass


def _load_journal() -> dict[str, dict[str, Any]]:
    try:
        metadata = JOURNAL_PATH.lstat()
    except FileNotFoundError:
        return {}
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode & 0o077
    ):
        raise SystemCommandInDoubt("system_command_journal_permissions_invalid")
    try:
        value = load_secure_json(
            JOURNAL_PATH,
            max_bytes=8 * 1024 * 1024,
            forbidden_mode_bits=0o077,
        )
    except ConfigurationError as exc:
        raise SystemCommandInDoubt("system_command_journal_corrupt") from exc
    if any(not isinstance(item, dict) for item in value.values()):
        raise SystemCommandInDoubt("system_command_journal_corrupt")
    return value


def _journal_key(client_id: int, command_id: str) -> str:
    return f"{client_id}:{command_id}"


def _journal_timestamp(value: dict[str, Any], *, default: float) -> float:
    try:
        timestamp = float(value.get("updated_at", default))
    except (TypeError, ValueError) as exc:
        raise SystemCommandInDoubt("system_command_journal_corrupt") from exc
    if timestamp < 0:
        raise SystemCommandInDoubt("system_command_journal_corrupt")
    return timestamp


def _prune_journal(journal: dict[str, dict[str, Any]], now: float) -> dict[str, dict[str, Any]]:
    retained = {
        key: value
        for key, value in journal.items()
        if value.get("state") != "completed"
        or now - _journal_timestamp(value, default=now) <= JOURNAL_RETENTION_SECONDS
    }
    if len(retained) <= 5000:
        return retained
    completed = sorted(
        ((key, value) for key, value in retained.items() if value.get("state") == "completed"),
        key=lambda item: _journal_timestamp(item[1], default=0),
    )
    for key, _ in completed[: max(0, len(retained) - 5000)]:
        retained.pop(key, None)
    return retained


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = STATE_DIR.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SystemCommandInDoubt("system_command_state_directory_invalid")
    os.chmod(STATE_DIR, 0o700)


def _current_boot_id() -> str:
    try:
        raw = BOOT_ID_PATH.read_text(encoding="ascii").strip()
        return str(uuid.UUID(raw))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemCommandInDoubt("system_boot_id_unavailable") from exc


def _journal_begin(client_id: int, command_id: str, action: str) -> tuple[int, dict[str, Any] | None]:
    _ensure_state_dir()
    lock_fd = os.open(JOURNAL_LOCK_PATH, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        now = time.time()
        journal = _prune_journal(_load_journal(), now)
        key = _journal_key(client_id, command_id)
        existing = journal.get(key)
        if existing is not None:
            if existing.get("action") != action:
                raise SystemCommandInDoubt("system_command_binding_mismatch")
            if existing.get("state") == "completed" and isinstance(existing.get("result"), dict):
                return lock_fd, dict(existing["result"])
            if existing.get("state") == "started" and action in BOOT_BOUNDARY_ACTIONS:
                previous_boot_id = str(existing.get("boot_id") or "")
                current_boot_id = _current_boot_id()
                if previous_boot_id and previous_boot_id != current_boot_id:
                    result = {
                        "exit_code": 0,
                        "recovered_after_boot_change": True,
                        "previous_boot_id": previous_boot_id,
                        "observed_boot_id": current_boot_id,
                    }
                    existing.update(
                        {
                            "state": "completed",
                            "result": result,
                            "updated_at": now,
                        }
                    )
                    journal[key] = existing
                    atomic_write_json(JOURNAL_PATH, journal, mode=0o600)
                    return lock_fd, dict(result)
            raise SystemCommandInDoubt("system_command_in_doubt")
        journal[key] = {
            "client_id": client_id,
            "command_id": command_id,
            "action": action,
            "state": "started",
            "updated_at": now,
            **({"boot_id": _current_boot_id()} if action in BOOT_BOUNDARY_ACTIONS else {}),
        }
        atomic_write_json(JOURNAL_PATH, journal, mode=0o600)
        return lock_fd, None
    except Exception:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        raise


def _journal_finish(
    lock_fd: int,
    *,
    client_id: int,
    command_id: str,
    action: str,
    result: dict[str, Any] | None,
    error: Exception | None,
) -> None:
    try:
        now = time.time()
        journal = _prune_journal(_load_journal(), now)
        key = _journal_key(client_id, command_id)
        entry = journal.get(key)
        if entry is None or entry.get("action") != action:
            raise SystemCommandInDoubt("system_command_journal_binding_lost")
        if error is None and result is not None:
            entry.update({"state": "completed", "result": result, "updated_at": now})
        else:
            entry.update({"state": "in_doubt", "error_type": type(error).__name__, "updated_at": now})
        journal[key] = entry
        atomic_write_json(JOURNAL_PATH, journal, mode=0o600)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _prepare(action: str, payload: dict[str, Any], *, client_id: int, command_id: str) -> dict[str, Any]:
    if action == "reboot":
        return {"command": [_fixed_binary("systemctl"), "--no-block", "reboot"], "timeout": 10}
    if action == "shutdown":
        return {"command": [_fixed_binary("systemctl"), "--no-block", "poweroff"], "timeout": 10}
    if action == "change_hostname":
        hostname = str(payload.get("hostname") or "").strip().lower()
        if not _HOSTNAME_RE.fullmatch(hostname):
            raise ValueError("Hostname er ugyldigt")
        return {"command": [_fixed_binary("hostnamectl"), "set-hostname", hostname], "timeout": 30}
    if action == "change_password":
        target_user, password = _decrypt_password(payload, client_id=client_id, command_id=command_id)
        return {
            "command": [_fixed_binary("chpasswd")],
            "timeout": 15,
            "input_bytes": f"{target_user}:{password}\n".encode("utf-8"),
            "target_user": target_user,
        }
    if action == "update_os":
        helper = Path("/opt/clientflow/active/client-runtime/libexec/update-os")
        if not helper.is_file() or helper.is_symlink():
            raise RuntimeError("OS-updatehelper er ikke installeret")
        return {"command": [str(helper)], "timeout": 7200}
    raise ValueError("Systemhandlingen er ikke implementeret")


def _execute(prepared: dict[str, Any]) -> dict[str, Any]:
    result = _run(
        list(prepared["command"]),
        timeout=float(prepared["timeout"]),
        input_bytes=prepared.get("input_bytes"),
    )
    target_user = prepared.get("target_user")
    if target_user:
        return {"exit_code": result["exit_code"], "target_user": str(target_user)}
    return result


def handle(request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("action") or "")
    payload = request.get("payload") or {}
    client_id = int(request.get("client_id") or 0)
    command_id = str(request.get("command_id") or "")
    schema_version = int(request.get("schema_version") or 0)
    try:
        uuid.UUID(command_id)
    except ValueError as exc:
        raise ValueError("Systembroker modtog ugyldigt command_id") from exc
    if action not in ALLOWED_ACTIONS or not isinstance(payload, dict) or client_id <= 0 or schema_version != 1:
        raise ValueError("Systembroker afviste handlingen")

    prepared = _prepare(action, payload, client_id=client_id, command_id=command_id)
    lock_fd, completed = _journal_begin(client_id, command_id, action)
    if completed is not None:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        return completed
    try:
        result = _execute(prepared)
    except Exception as exc:
        _journal_finish(
            lock_fd,
            client_id=client_id,
            command_id=command_id,
            action=action,
            result=None,
            error=exc,
        )
        raise SystemCommandInDoubt("system_command_in_doubt") from exc
    _journal_finish(
        lock_fd,
        client_id=client_id,
        command_id=command_id,
        action=action,
        result=result,
        error=None,
    )
    return result


def main() -> int:
    serve_forever(activated_socket(), handle, name="clientflow.system.broker", connection_timeout=7300)
    return 0
