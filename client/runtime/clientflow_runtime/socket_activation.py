"""systemd socket activation helpers."""
from __future__ import annotations

import os
import socket


class SocketActivationError(RuntimeError):
    pass


def activated_socket() -> socket.socket:
    listen_pid = int(os.getenv("LISTEN_PID", "0") or "0")
    listen_fds = int(os.getenv("LISTEN_FDS", "0") or "0")
    if listen_pid != os.getpid() or listen_fds != 1:
        raise SocketActivationError("Tjenesten kræver præcis én systemd-aktiveret socket")
    server = socket.socket(fileno=3)
    server.setblocking(True)
    return server
