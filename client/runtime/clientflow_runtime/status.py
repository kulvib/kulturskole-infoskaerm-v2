"""Domain-owned status reporting."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import AGENT_VERSION
from .net import DomainTransport


def boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def build_status_body(*, observed_state: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical shared-domain status body without sending it.

    Display/System command agents use the exact same payload when a due status
    report is piggybacked on their existing command-claim request.
    """
    return {
        "schema_version": 1,
        "observed_state": observed_state,
        "status_payload": payload,
        "agent_version": AGENT_VERSION,
        "boot_id": boot_id(),
    }


def report_status(
    transport: DomainTransport,
    *,
    observed_state: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    domain = transport.credential.domain.value
    client_id = transport.credential.client_id
    return transport.json_request(
        "PUT",
        f"/api/{domain.replace('_', '-')}-agent/clients/{client_id}/status",
        json_body=build_status_body(observed_state=observed_state, payload=payload),
    )
