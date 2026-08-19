"""Proxy-aware client-IP extraction for PlanIQ services.

Render documents that the first value in ``X-Forwarded-For`` is the original
client address. Values are validated before use so malformed headers never
become rate-limit or audit keys.
"""
from __future__ import annotations

from ipaddress import ip_address
from typing import Optional

from fastapi import Request


def _validated_ip(value: str | None) -> Optional[str]:
    candidate = (value or "").strip()
    if not candidate:
        return None
    # RFC 7239-style IPv6 brackets are not expected from Render, but accepting
    # them makes local proxy testing less surprising.
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def get_client_ip(request: Request | None) -> str:
    """Return the best validated client address, or ``unknown``.

    On Render, all public traffic traverses trusted edge/load-balancer layers,
    and the first ``X-Forwarded-For`` entry is the original client address.
    Local/test requests fall back to the ASGI socket peer.
    """
    if request is None:
        return "unknown"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0]
        validated = _validated_ip(first)
        if validated:
            return validated

    if request.client:
        validated = _validated_ip(request.client.host)
        if validated:
            return validated
        # Starlette TestClient commonly uses a symbolic host. Keep a bounded,
        # non-empty fallback so tests and non-IP internal clients remain stable.
        fallback = (request.client.host or "").strip()
        if fallback:
            return fallback[:120]

    return "unknown"
