"""Bounded newline-delimited JSON RPC over local Unix sockets."""
from __future__ import annotations

import json
import socket
from typing import Any

from .constants import MAX_JSON_BYTES


class RpcError(RuntimeError):
    pass


def encode_message(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(raw) > MAX_JSON_BYTES:
        raise RpcError("RPC-meddelelse er for stor")
    return raw


def read_message(connection: socket.socket, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    chunks = bytearray()
    while True:
        chunk = connection.recv(min(65536, max_bytes + 1 - len(chunks)))
        if not chunk:
            raise RpcError("RPC-forbindelsen blev lukket")
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise RpcError("RPC-meddelelse er for stor")
        newline = chunks.find(b"\n")
        if newline >= 0:
            raw = bytes(chunks[:newline])
            break
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RpcError("RPC-meddelelse er ugyldig JSON") from exc
    if not isinstance(payload, dict):
        raise RpcError("RPC-meddelelse skal være et objekt")
    return payload


def call(path: str, payload: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(path)
        connection.sendall(encode_message(payload))
        response = read_message(connection)
    if response.get("ok") is not True:
        raise RpcError(str(response.get("error") or "Lokal broker afviste anmodningen"))
    result = response.get("result")
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise RpcError("Lokal broker returnerede ugyldigt resultat")
    return result


class SocketJsonReader:
    """Buffered reader for multiple NDJSON messages on one socket."""

    def __init__(self, connection: socket.socket, *, max_bytes: int = MAX_JSON_BYTES) -> None:
        self.connection = connection
        self.max_bytes = max_bytes
        self.buffer = bytearray()

    def read(self) -> dict[str, Any]:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RpcError("RPC-meddelelse er ugyldig JSON") from exc
                if not isinstance(payload, dict):
                    raise RpcError("RPC-meddelelse skal være et objekt")
                return payload
            chunk = self.connection.recv(min(65536, self.max_bytes + 1 - len(self.buffer)))
            if not chunk:
                raise RpcError("RPC-forbindelsen blev lukket")
            self.buffer.extend(chunk)
            if len(self.buffer) > self.max_bytes:
                raise RpcError("RPC-meddelelse er for stor")
