"""Livestream desired-state broker. It cannot control other services or domains."""
from __future__ import annotations

import json
import os
import selectors
import socket
import time
from typing import Any
import uuid

from .atomic import atomic_write_json
from .livestream_paths import BROKER_SOCKET, BROKER_STATUS_PATH, DESIRED_PATH, RUNTIME_DIR
from .logging_utils import configure_logging
from .unix_rpc import RpcError, encode_message, read_message


class LivestreamBroker:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.livestream.broker")

    def _load_desired(self) -> dict[str, Any]:
        try:
            payload = json.loads(DESIRED_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "desired": "stopped", "generation_id": None}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Livestream desired state er ugyldig") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Livestream desired state skal være et objekt")
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        atomic_write_json(DESIRED_PATH, payload, mode=0o640)
        atomic_write_json(
            BROKER_STATUS_PATH,
            {"schema_version": 1, "state": "ready", "desired": payload, "updated_at": time.time()},
            mode=0o640,
        )

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = str(request.get("action") or "")
        if action in {"start", "restart", "reset_generation"}:
            generation_id = str(request.get("generation_id") or "")
            try:
                uuid.UUID(generation_id)
            except ValueError as exc:
                raise ValueError("Livestreamgeneration er ugyldig") from exc
            payload = {
                "schema_version": 1,
                "desired": "running",
                "generation_id": generation_id,
                "requested_action": action,
                "updated_at": time.time(),
            }
            self._save(payload)
            return payload
        if action == "stop":
            current = self._load_desired()
            payload = {
                "schema_version": 1,
                "desired": "stopped",
                "generation_id": current.get("generation_id"),
                "requested_action": "stop",
                "updated_at": time.time(),
            }
            self._save(payload)
            return payload
        if action == "status":
            return self._load_desired()
        raise ValueError("Ukendt livestreambrokerhandling")

    def run(self) -> int:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        socket_path = os.fspath(BROKER_SOCKET)
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(socket_path)
        os.chmod(socket_path, 0o660)
        server.listen(8)
        server.setblocking(False)
        selector = selectors.DefaultSelector()
        selector.register(server, selectors.EVENT_READ)
        if not DESIRED_PATH.exists():
            self._save({"schema_version": 1, "desired": "stopped", "generation_id": None, "updated_at": time.time()})
        try:
            while True:
                for key, _ in selector.select(timeout=5):
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
            server.close()
            try:
                os.unlink(socket_path)
            except FileNotFoundError:
                pass


def main() -> int:
    return LivestreamBroker().run()
