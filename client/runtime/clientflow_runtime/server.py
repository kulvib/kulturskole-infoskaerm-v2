"""Small bounded local broker server."""
from __future__ import annotations

from collections.abc import Callable
import socket
from typing import Any

from .logging_utils import configure_logging
from .unix_rpc import RpcError, encode_message, read_message


def serve_forever(
    server: socket.socket,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    name: str,
    connection_timeout: float = 60.0,
) -> None:
    logger = configure_logging(name)
    while True:
        connection, _ = server.accept()
        with connection:
            connection.settimeout(connection_timeout)
            try:
                request = read_message(connection)
                result = handler(request)
                connection.sendall(encode_message({"ok": True, "result": result}))
            except (RpcError, ValueError, RuntimeError, OSError) as exc:
                logger.warning("broker_request_rejected", extra={"event": type(exc).__name__})
                try:
                    connection.sendall(encode_message({"ok": False, "error": str(exc)[:1000]}))
                except OSError:
                    pass
            except Exception:
                logger.exception("broker_internal_error")
                try:
                    connection.sendall(encode_message({"ok": False, "error": "internal_error"}))
                except OSError:
                    pass
