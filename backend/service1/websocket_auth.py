"""WebSocket-authentication for Remote Desktop browser og shared client agents.

Remote Desktop-browseren bruger en kortlivet one-time ticket i WebSocket-
subprotocol-headeren, når frontenden forbinder direkte til backendens web
service. Den first-party HttpOnly access-cookie bevares som fallback til
lokal/same-origin brug. Installerede ClientFlow-agenter bevarer deres
eksisterende query-token-kontrakt. Terminal-browserens ticket-state ejes af
``terminal_websocket_auth`` og findes bevidst ikke i dette modul.
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

from .auth import (
    get_access_token_session_binding,
    validate_browser_auth_session_binding,
    verify_ws_token,
)
from .models import User

BROWSER_WS_SUBPROTOCOL = "planiq-ws-ticket"
BROWSER_WS_CAPABILITIES = frozenset({"remote_desktop"})
_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} skal være et heltal") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} skal være mellem {minimum} og {maximum}")
    return value


BROWSER_WS_TICKET_TTL_SECONDS = _env_int(
    "BROWSER_WS_TICKET_TTL_SECONDS",
    30,
    minimum=10,
    maximum=120,
)
BROWSER_WS_TICKET_MAX_PENDING = _env_int(
    "BROWSER_WS_TICKET_MAX_PENDING",
    2048,
    minimum=100,
    maximum=10000,
)


@dataclass(frozen=True)
class BrowserWsTicketRecord:
    user_id: int
    user_token_version: int
    client_id: int
    capability: str
    auth_session_binding: Optional[str]
    expires_at_monotonic: float
    expires_at_utc: datetime


@dataclass(frozen=True)
class IssuedBrowserWsTicket:
    ticket: str
    expires_at: datetime
    subprotocol: str = BROWSER_WS_SUBPROTOCOL


class BrowserWsTicketStoreFull(RuntimeError):
    """Raised when the bounded one-worker ticket store cannot accept more."""


_TICKET_LOCK = threading.Lock()
_BROWSER_WS_TICKETS: dict[str, BrowserWsTicketRecord] = {}


def _token_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _prune_expired_tickets_locked(now_monotonic: float) -> None:
    expired = [
        token_hash
        for token_hash, record in _BROWSER_WS_TICKETS.items()
        if record.expires_at_monotonic <= now_monotonic
    ]
    for token_hash in expired:
        _BROWSER_WS_TICKETS.pop(token_hash, None)


def issue_browser_ws_ticket(
    *,
    user: User,
    client_id: int,
    capability: str,
    auth_session_binding: Optional[str] = None,
) -> IssuedBrowserWsTicket:
    """Issue an opaque, bounded and short-lived browser WebSocket ticket."""
    if user.id is None:
        raise ValueError("Brugeren skal have et database-id")
    if int(client_id) < 1:
        raise ValueError("client_id skal være positiv")
    if capability not in BROWSER_WS_CAPABILITIES:
        raise ValueError("Ukendt WebSocket-capability")

    now_monotonic = time.monotonic()
    expires_at_utc = datetime.now(timezone.utc) + timedelta(seconds=BROWSER_WS_TICKET_TTL_SECONDS)
    raw_ticket = secrets.token_urlsafe(32)
    record = BrowserWsTicketRecord(
        user_id=int(user.id),
        user_token_version=int(user.token_version or 0),
        client_id=int(client_id),
        capability=capability,
        auth_session_binding=(str(auth_session_binding) if auth_session_binding else None),
        expires_at_monotonic=now_monotonic + BROWSER_WS_TICKET_TTL_SECONDS,
        expires_at_utc=expires_at_utc,
    )

    with _TICKET_LOCK:
        _prune_expired_tickets_locked(now_monotonic)
        if len(_BROWSER_WS_TICKETS) >= BROWSER_WS_TICKET_MAX_PENDING:
            raise BrowserWsTicketStoreFull("WebSocket-ticketlageret er midlertidigt fuldt")
        _BROWSER_WS_TICKETS[_token_hash(raw_ticket)] = record

    return IssuedBrowserWsTicket(ticket=raw_ticket, expires_at=expires_at_utc)


def extract_browser_ws_ticket(websocket: WebSocket) -> Optional[str]:
    """Read the opaque ticket from the negotiated subprotocol offer."""
    raw = websocket.headers.get("sec-websocket-protocol") or ""
    protocols = [item.strip() for item in raw.split(",") if item.strip()]
    try:
        marker_index = protocols.index(BROWSER_WS_SUBPROTOCOL)
    except ValueError:
        return None

    ticket_index = marker_index + 1
    if ticket_index >= len(protocols):
        return None
    candidate = protocols[ticket_index]
    return candidate if _TICKET_RE.fullmatch(candidate) else None


def _consume_browser_ws_ticket_with_binding(
    ticket: str,
    *,
    client_id: int,
    capability: str,
    session: Session,
) -> tuple[Optional[User], Optional[str]]:
    """Atomically consume one ticket and return user + login-session binding."""
    if not _TICKET_RE.fullmatch(str(ticket or "")):
        return None, None

    now_monotonic = time.monotonic()
    with _TICKET_LOCK:
        _prune_expired_tickets_locked(now_monotonic)
        record = _BROWSER_WS_TICKETS.pop(_token_hash(ticket), None)

    # Pop happens before all validation. A wrong route/scope also consumes the
    # ticket, so the same credential can never be replayed elsewhere.
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


def consume_browser_ws_ticket(
    ticket: str,
    *,
    client_id: int,
    capability: str,
    session: Session,
) -> Optional[User]:
    """Atomically consume one ticket and resolve its still-valid user."""
    user, _ = _consume_browser_ws_ticket_with_binding(
        ticket, client_id=client_id, capability=capability, session=session
    )
    return user


def extract_browser_ws_token(websocket: WebSocket) -> Optional[str]:
    """Same-origin fallback: use only the HttpOnly access-token cookie."""
    return websocket.cookies.get("access_token") or None


def authenticate_browser_websocket_with_context(
    websocket: WebSocket,
    *,
    client_id: int,
    capability: str,
    session: Session,
) -> tuple[Optional[User], Optional[str], Optional[str]]:
    """Authenticate a browser socket and retain its login-session binding."""
    ticket = extract_browser_ws_ticket(websocket)
    if ticket:
        user, binding = _consume_browser_ws_ticket_with_binding(
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
        return active_user, BROWSER_WS_SUBPROTOCOL, binding

    token = extract_browser_ws_token(websocket)
    principal = verify_ws_token(token, session) if token else None
    if not isinstance(principal, User):
        return None, None, None
    try:
        binding = get_access_token_session_binding(token, principal) if token else None
    except Exception:
        return None, None, None
    if not binding or principal.id is None:
        return None, None, None
    active_user = validate_browser_auth_session_binding(
        session,
        user_id=int(principal.id),
        user_token_version=int(principal.token_version or 0),
        auth_session_binding=binding,
    )
    if active_user is None:
        return None, None, None
    return active_user, None, binding


def authenticate_browser_websocket(
    websocket: WebSocket,
    *,
    client_id: int,
    capability: str,
    session: Session,
) -> tuple[Optional[User], Optional[str]]:
    """Backward-compatible wrapper that discards login-session context."""
    user, selected_subprotocol, _ = authenticate_browser_websocket_with_context(
        websocket,
        client_id=client_id,
        capability=capability,
        session=session,
    )
    return user, selected_subprotocol



def extract_agent_ws_token(websocket: WebSocket) -> Optional[str]:
    """Agent: query-token is the existing ClientFlow contract."""
    query_token = websocket.query_params.get("token")
    if query_token:
        return query_token

    auth_header = websocket.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:]

    # Cookie fallback keeps local agent tests possible, while installed agents
    # continue to prefer their existing query-token contract.
    return websocket.cookies.get("access_token") or None


def _clear_browser_ws_ticket_store_for_tests() -> None:
    with _TICKET_LOCK:
        _BROWSER_WS_TICKETS.clear()
