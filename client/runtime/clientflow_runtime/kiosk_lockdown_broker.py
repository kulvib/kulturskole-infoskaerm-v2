"""Root-owned fixed-function broker for optional kiosk lockdown."""
from __future__ import annotations
from typing import Any
from . import kiosk_lockdown
from .server import serve_forever
from .socket_activation import activated_socket


def handle(request: dict[str, Any]) -> dict[str, Any]:
    if int(request.get("schema_version") or 0) != 1:
        raise ValueError("Kiosk-lockdown broker kræver schema_version=1")
    action = request.get("action")
    if action == "status_kiosk_lockdown":
        return kiosk_lockdown.status()
    if action != "set_kiosk_lockdown":
        raise ValueError("Kiosk-lockdown broker accepterer kun status/set_kiosk_lockdown")
    enabled = request.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled skal være boolean")
    return kiosk_lockdown.apply() if enabled else kiosk_lockdown.rollback()


def main() -> int:
    serve_forever(activated_socket(), handle, name="clientflow.kiosk-lockdown-broker")
    return 0
