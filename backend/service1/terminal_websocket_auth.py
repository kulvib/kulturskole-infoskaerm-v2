"""Terminal-owned browser WebSocket authentication.

Terminal browser sockets use a short-lived one-time ticket carried in the
WebSocket subprotocol offer. Ticket state is deliberately owned by Terminal so
Terminal cannot consume Remote Desktop's bounded browser-ticket capacity (or
vice versa).

The browser socket itself is ticket-only. Platform login is consulted only when
the HTTP ticket endpoint issues a Terminal ticket; the WebSocket route cannot
fall back to the platform access cookie.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
import secrets
import threading
import time
from typing import Optional

from fastapi import WebSocket
from sqlmodel import Session

from .auth import validate_browser_auth_session_binding
from .models import User

TERMINAL_BROWSER_WS_SUBPROTOCOL = "planiq-ws-ticket"
TERMINAL_BROWSER_WS_CAPABILITIES = frozenset({"terminal_user", "terminal_admin"})
_TERMINAL_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} skal være et heltal") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} skal være mellem {minimum} og {maximum}")
    return value


TERMINAL_BROWSER_WS_TICKET_TTL_SECONDS = _env_int(
    "TERMINAL_BROWSER_WS_TICKET_TTL_SECONDS",
    30,
    minimum=10,
    maximum=120,
)
TERMINAL_BROWSER_WS_TICKET_MAX_PENDING = _env_int(
    "TERMINAL_BROWSER_WS_TICKET_MAX_PENDING",
    2048,
    minimum=100,
    maximum=10000,
)


@dataclass(frozen=True)
class TerminalBrowserWsTicketRecord:
    user_id: int
    user_token_version: int
    client_id: int
    capability: str
    auth_session_binding: Optional[str]
    expires_at_monotonic: float
    expires_at_utc: datetime


@dataclass(frozen=True)
class IssuedTerminalBrowserWsTicket:
    ticket: str
    expires_at: datetime
    subprotocol: str = TERMINAL_BROWSER_WS_SUBPROTOCOL


class TerminalBrowserWsTicketStoreFull(RuntimeError):
    """Raised when the bounded Terminal ticket store cannot accept more."""


_TERMINAL_TICKET_LOCK = threading.Lock()
_TERMINAL_BROWSER_WS_TICKETS: dict[str, TerminalBrowserWsTicketRecord] = {}


def _token_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _prune_expired_tickets_locked(now_monotonic: float) -> None:
    expired = [
        token_hash
        for token_hash, record in _TERMINAL_BROWSER_WS_TICKETS.items()
        if record.expires_at_monotonic <= now_monotonic
    ]
    for token_hash in expired:
        _TERMINAL_BROWSER_WS_TICKETS.pop(token_hash, None)


def issue_terminal_browser_ws_ticket(
    *,
    user: User,
    client_id: int,
    capability: str,
    auth_session_binding: Optional[str] = None,
) -> IssuedTerminalBrowserWsTicket:
    """Issue an opaque, bounded, short-lived Terminal browser ticket."""
    if user.id is None:
        raise ValueError("Brugeren skal have et database-id")
    if int(client_id) < 1:
        raise ValueError("client_id skal være positiv")
    if capability not in TERMINAL_BROWSER_WS_CAPABILITIES:
        raise ValueError("Ukendt Terminal WebSocket-capability")

    now_monotonic = time.monotonic()
    expires_at_utc = datetime.now(timezone.utc) + timedelta(
        seconds=TERMINAL_BROWSER_WS_TICKET_TTL_SECONDS
    )
    raw_ticket = secrets.token_urlsafe(32)
    record = TerminalBrowserWsTicketRecord(
        user_id=int(user.id),
        user_token_version=int(user.token_version or 0),
        client_id=int(client_id),
        capability=capability,
        auth_session_binding=(str(auth_session_binding) if auth_session_binding else None),
        expires_at_monotonic=now_monotonic + TERMINAL_BROWSER_WS_TICKET_TTL_SECONDS,
        expires_at_utc=expires_at_utc,
    )

    with _TERMINAL_TICKET_LOCK:
        _prune_expired_tickets_locked(now_monotonic)
        if len(_TERMINAL_BROWSER_WS_TICKETS) >= TERMINAL_BROWSER_WS_TICKET_MAX_PENDING:
            raise TerminalBrowserWsTicketStoreFull(
                "Terminal WebSocket-ticketlageret er midlertidigt fuldt"
            )
        _TERMINAL_BROWSER_WS_TICKETS[_token_hash(raw_ticket)] = record

    return IssuedTerminalBrowserWsTicket(ticket=raw_ticket, expires_at=expires_at_utc)


def extract_terminal_browser_ws_ticket(websocket: WebSocket) -> Optional[str]:
    """Read the opaque Terminal ticket from the WebSocket subprotocol offer."""
    raw = websocket.headers.get("sec-websocket-protocol") or ""
    protocols = [item.strip() for item in raw.split(",") if item.strip()]
    try:
        marker_index = protocols.index(TERMINAL_BROWSER_WS_SUBPROTOCOL)
    except ValueError:
        return None

    ticket_index = marker_index + 1
    if ticket_index >= len(protocols):
        return None
    candidate = protocols[ticket_index]
    return candidate if _TERMINAL_TICKET_RE.fullmatch(candidate) else None


def _consume_terminal_browser_ws_ticket_with_binding(
    ticket: str,
    *,
    client_id: int,
    capability: str,
    session: Session,
) -> tuple[Optional[User], Optional[str]]:
    """Atomically consume one Terminal ticket and return user + login binding."""
    if not _TERMINAL_TICKET_RE.fullmatch(str(ticket or "")):
        return None, None

    now_monotonic = time.monotonic()
    with _TERMINAL_TICKET_LOCK:
        _prune_expired_tickets_locked(now_monotonic)
        record = _TERMINAL_BROWSER_WS_TICKETS.pop(_token_hash(ticket), None)

    # Consume before validation so a ticket presented to the wrong Terminal
    # client/mode can never be replayed against its intended route afterwards.
    if record is None or record.expires_at_monotonic <= now_monotonic:
        return None, None
    if record.client_id != int(client_id) or record.capability != capability:
        return None, None

    user = session.get(User, record.user_id)
    if not user or not user.is_active:
        return None, None
    if int(user.token_version or 0) != record.user_token_version:
        return None, None
    return user, record.auth_session_binding


def consume_terminal_browser_ws_ticket(
    ticket: str,
    *,
    client_id: int,
    capability: str,
    session: Session,
) -> Optional[User]:
    """Atomically consume one Terminal ticket and resolve its current user."""
    user, _ = _consume_terminal_browser_ws_ticket_with_binding(
        ticket,
        client_id=client_id,
        capability=capability,
        session=session,
    )
    return user


def authenticate_terminal_browser_websocket_with_context(
    websocket: WebSocket,
    *,
    client_id: int,
    capability: str,
    session: Session,
) -> tuple[Optional[User], Optional[str], Optional[str]]:
    """Authenticate a Terminal browser socket exclusively with a one-time ticket."""
    ticket = extract_terminal_browser_ws_ticket(websocket)
    if not ticket:
        return None, None, None
    user, binding = _consume_terminal_browser_ws_ticket_with_binding(
        ticket,
        client_id=client_id,
        capability=capability,
        session=session,
    )
    if not user or not binding or user.id is None:
        return None, None, None
    active_user = validate_browser_auth_session_binding(
        session,
        user_id=int(user.id),
        user_token_version=int(user.token_version or 0),
        auth_session_binding=binding,
    )
    if active_user is None:
        return None, None, None
    return (
        active_user,
        TERMINAL_BROWSER_WS_SUBPROTOCOL,
        binding,
    )


def _clear_terminal_browser_ws_ticket_store_for_tests() -> None:
    with _TERMINAL_TICKET_LOCK:
        _TERMINAL_BROWSER_WS_TICKETS.clear()
