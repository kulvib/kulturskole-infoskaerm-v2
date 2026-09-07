"""
routers/terminal.py

Remote PTY terminal broker for ClientFlow.

Design:
- Klient-agenten opretter outbound WSS til backend.
- Browser/frontend opretter WSS til backend.
- Backend broker en rigtig interaktiv PTY-terminal mellem browser og klient.

Protokol browser -> backend -> klient-agent:
- open   {cols, rows}
- input  {data}
- resize {cols, rows}
- close
- stage_script {filename, content_b64}  # gem clipboard som fil og indsæt én bash-kommando

Protokol klient-agent -> backend -> browser:
- ready
- output {data}
- exit   {code}
- error  {message}

Der findes bevidst ingen gammel "run command"-vej i denne version.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..auth import (
    get_current_superadmin_user,
    oauth2_scheme,
    require_active_browser_auth_session_binding,
    validate_browser_auth_session_binding,
)
from ..client_activity import end_activity_lease, maintain_activity_lease
from ..db import engine, get_session
from ..models import User
from ..observability import log_safe_exception
from ..rate_limit import enforce_request_rate_limit
from ..terminal_websocket_auth import (
    TerminalBrowserWsTicketStoreFull,
    authenticate_terminal_browser_websocket_with_context,
    issue_terminal_browser_ws_ticket,
)
from ..websocket_protocol import ProtocolError, bounded_int, bounded_text, decode_json_message
from ..terminal_v2 import (
    bearer_token,
    create_browser_terminal_session,
    issue_root_terminal_grant,
    mark_browser_terminal_closed,
    mark_terminal_agent_disconnected,
    record_terminal_agent_event,
    terminal_session_start_message,
    update_terminal_domain_status,
    verify_admin_terminal_step_up,
    verify_admin_terminal_step_up_token,
    verify_terminal_agent_token,
)
from ..terminal_v2_models import TerminalClient, TerminalCredential

router = APIRouter(prefix="/terminal", tags=["terminal"])
agent_router = APIRouter(prefix="/terminal-agent", tags=["terminal-agent"])
logger = logging.getLogger(__name__)

VALID_TERMINAL_MODES = {"user", "admin"}
BROWSER_MESSAGE_TYPES = {"open", "input", "resize", "close", "stage_script"}
MAX_INPUT_CHARS = 200_000
MAX_STAGED_SCRIPT_B64_CHARS = 2_000_000
MAX_AGENT_MESSAGE_CHARS = 4 * 1024 * 1024
STAGED_INPUT_CHUNK_CHARS = 96_000
MIN_COLS = 20
MAX_COLS = 300
MIN_ROWS = 5
MAX_ROWS = 120
TERMINAL_BROWSER_AUTH_RECHECK_SECONDS = 15.0
TERMINAL_AGENT_AUTH_RECHECK_SECONDS = 15.0


class DomainStatusBody(BaseModel):
    schema_version: int = Field(ge=1)
    observed_state: str = Field(min_length=1, max_length=64)
    status_payload: dict[str, Any] = Field(default_factory=dict)
    agent_version: Optional[str] = Field(default=None, max_length=64)
    boot_id: Optional[str] = Field(default=None, max_length=128)


class TerminalAgentEventBody(BaseModel):
    event_type: str = Field(min_length=1, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)
    exit_code: Optional[int] = None
    transcript_reference: Optional[str] = Field(default=None, max_length=2000)
    transcript_sha256: Optional[str] = Field(default=None, max_length=128)


class TerminalBrowserMode(str, Enum):
    USER = "user"
    ADMIN = "admin"


class TerminalBrowserTicketRequest(BaseModel):
    client_id: int = Field(gt=0)
    mode: TerminalBrowserMode


class TerminalBrowserTicketResponse(BaseModel):
    ticket: str
    subprotocol: str
    expires_at: datetime


def _parse_allowed_ws_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS") or os.getenv("FRONTEND_URL") or ""
    origins: list[str] = []
    for item in raw.split(","):
        item = item.strip().rstrip("/")
        if item and item not in origins:
            origins.append(item)
    return origins


ALLOWED_WS_ORIGINS = _parse_allowed_ws_origins()
IS_PRODUCTION = os.getenv("ENVIRONMENT", "production") == "production"


def _ws_origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return not IS_PRODUCTION
    return origin in ALLOWED_WS_ORIGINS


@dataclass
class DomainClientConnection:
    connection_id: str
    client_id: int
    credential_id: str
    token_version: int
    websocket: WebSocket
    connected_at: float = field(default_factory=time.time)


@dataclass
class BrowserSession:
    session_id: str
    client_id: int
    mode: str
    websocket: WebSocket
    user_id: Optional[int]
    username: str
    user_token_version: int = 0
    connected_at: float = field(default_factory=time.time)
    protocol: str = "pending"
    agent_session_id: Optional[str] = None
    agent_close_sent: bool = False
    cols: int = 120
    rows: int = 32
    auth_session_binding: Optional[str] = None
    admin_step_up_failures: int = 0


# ClientFlow 1.2 has one Terminal-domain agent per client. There is no legacy
# generic client-token fallback: Terminal traffic is accepted only through the
# Terminal-owned credential/token boundary.
DOMAIN_CLIENTS: dict[int, DomainClientConnection] = {}
BROWSERS: dict[str, BrowserSession] = {}
V2_SESSIONS: dict[str, BrowserSession] = {}
LOCK = asyncio.Lock()


def _normalize_mode(mode: str | None) -> str:
    value = (mode or "user").strip().lower()
    if value not in VALID_TERMINAL_MODES:
        return "user"
    return value


def _terminal_size(msg: dict[str, Any]) -> tuple[int, int]:
    cols = bounded_int(msg.get("cols"), default=120, minimum=MIN_COLS, maximum=MAX_COLS)
    rows = bounded_int(msg.get("rows"), default=32, minimum=MIN_ROWS, maximum=MAX_ROWS)
    return cols, rows


def extract_terminal_agent_ws_token(websocket: WebSocket) -> Optional[str]:
    """Extract only Terminal-agent credentials; never fall back to browser cookies."""
    query_token = websocket.query_params.get("token")
    if query_token:
        return query_token
    auth_header = websocket.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        return token or None
    return None


def _current_terminal_superadmin(browser: BrowserSession) -> Optional[User]:
    """Resolve a Terminal principal whose originating login is still active."""
    if browser.user_id is None or not browser.auth_session_binding:
        return None
    with Session(engine) as auth_session:
        current_user = validate_browser_auth_session_binding(
            auth_session,
            user_id=int(browser.user_id),
            user_token_version=browser.user_token_version,
            auth_session_binding=browser.auth_session_binding,
        )
        terminal_client = auth_session.get(TerminalClient, browser.client_id)
    if (
        current_user is None
        or not getattr(current_user, "is_superadmin", False)
        or terminal_client is None
        or terminal_client.status != "approved"
    ):
        return None
    return current_user


def _terminal_agent_connection_valid(conn: DomainClientConnection) -> bool:
    """Bounded revalidation for an already-established Terminal agent socket."""
    with Session(engine) as session:
        client = session.get(TerminalClient, conn.client_id)
        credential = session.get(TerminalCredential, conn.credential_id)
    return bool(
        client is not None
        and client.status == "approved"
        and credential is not None
        and credential.client_id == conn.client_id
        and credential.revoked_at is None
        and int(credential.token_version) == int(conn.token_version)
    )


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


def _get_terminal_domain_credential_from_ws(websocket: WebSocket, *, client_id: int) -> TerminalCredential | None:
    token = extract_terminal_agent_ws_token(websocket)
    if not token:
        return None
    with Session(engine) as session:
        try:
            return verify_terminal_agent_token(session, token, client_id=client_id)
        except HTTPException:
            return None


async def _send_to_domain_agent(client_id: int, payload: dict[str, Any]) -> bool:
    async with LOCK:
        conn = DOMAIN_CLIENTS.get(client_id)
    if conn is None:
        return False
    try:
        await _send_json(conn.websocket, payload)
        return True
    except Exception as exc:
        log_safe_exception(
            logger, exc, event="terminal_v2_forward_failed", level=logging.WARNING,
            client_id=client_id, connection_id=conn.connection_id, connection_type="terminal_domain_agent"
        )
        return False


def _terminal_agent_token_from_header(authorization: Optional[str]) -> str:
    return bearer_token(authorization)


@agent_router.put("/clients/{client_id}/status")
def terminal_agent_status(
    client_id: int,
    body: DomainStatusBody,
    authorization: Optional[str] = Header(default=None),
):
    token = _terminal_agent_token_from_header(authorization)
    with Session(engine) as session:
        credential = verify_terminal_agent_token(session, token, client_id=client_id)
        row = update_terminal_domain_status(
            session,
            credential=credential,
            schema_version=body.schema_version,
            observed_state=body.observed_state,
            status_payload=body.status_payload,
            agent_version=body.agent_version,
            boot_id=body.boot_id,
        )
        session.commit()
        return {
            "client_id": row.client_id,
            "domain": "terminal",
            "schema_version": row.schema_version,
            "observed_state": row.observed_state,
            "credential_id": row.credential_id,
            "reported_at": row.reported_at,
        }


@agent_router.post("/clients/{client_id}/sessions/{session_id}/events")
def terminal_agent_event(
    client_id: int,
    session_id: str,
    body: TerminalAgentEventBody,
    authorization: Optional[str] = Header(default=None),
):
    token = _terminal_agent_token_from_header(authorization)
    with Session(engine) as session:
        credential = verify_terminal_agent_token(session, token, client_id=client_id)
        row = record_terminal_agent_event(
            session,
            credential=credential,
            session_id=session_id,
            event_type=body.event_type,
            details=body.details,
            exit_code=body.exit_code,
            transcript_reference=body.transcript_reference,
            transcript_sha256=body.transcript_sha256,
        )
        session.commit()
        return {"ok": True, "session_id": row.id, "status": row.status}


@agent_router.websocket("/clients/{client_id}/ws")
async def terminal_domain_agent_ws(websocket: WebSocket, client_id: int):
    """ClientFlow 1.2 Terminal agent. One isolated agent serves user+admin sessions."""
    await websocket.accept()
    credential = _get_terminal_domain_credential_from_ws(websocket, client_id=client_id)
    if credential is None:
        await _close_with_reason(websocket, 4401, "Ugyldigt Terminal-domænetoken")
        return

    connection_id = uuid.uuid4().hex
    async with LOCK:
        old = DOMAIN_CLIENTS.get(client_id)
        if old is not None:
            try:
                await old.websocket.close(code=4400, reason="Ny Terminal-agent forbandt")
            except Exception:
                pass
        DOMAIN_CLIENTS[client_id] = DomainClientConnection(
            connection_id=connection_id,
            client_id=client_id,
            credential_id=credential.id,
            token_version=int(credential.token_version),
            websocket=websocket,
        )

    logger.info(
        "terminal_v2_agent_connected client_id=%s credential_id=%s connection_id=%s",
        client_id, credential.id, connection_id,
    )
    await _broadcast_status(client_id, "user")
    await _broadcast_status(client_id, "admin")

    receive_task = None
    next_auth_recheck = time.monotonic() + TERMINAL_AGENT_AUTH_RECHECK_SECONDS
    try:
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            timeout = max(0.0, next_auth_recheck - time.monotonic())
            done, _ = await asyncio.wait(
                {receive_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if receive_task not in done:
                conn = DOMAIN_CLIENTS.get(client_id)
                if conn is None or conn.websocket is not websocket or not _terminal_agent_connection_valid(conn):
                    await _close_with_reason(websocket, 4401, "Terminal credential er ikke længere gyldigt")
                    return
                next_auth_recheck = time.monotonic() + TERMINAL_AGENT_AUTH_RECHECK_SECONDS
                continue

            raw = receive_task.result()
            receive_task = asyncio.create_task(websocket.receive_text())
            if time.monotonic() >= next_auth_recheck:
                conn = DOMAIN_CLIENTS.get(client_id)
                if conn is None or conn.websocket is not websocket or not _terminal_agent_connection_valid(conn):
                    await _close_with_reason(websocket, 4401, "Terminal credential er ikke længere gyldigt")
                    return
                next_auth_recheck = time.monotonic() + TERMINAL_AGENT_AUTH_RECHECK_SECONDS
            try:
                decoded = decode_json_message(raw, max_chars=MAX_AGENT_MESSAGE_CHARS)
            except ProtocolError as exc:
                if exc.close_code:
                    await _close_with_reason(websocket, exc.close_code, exc.message)
                    return
                continue
            msg = decoded.payload
            msg_type = decoded.type
            session_id = str(msg.get("session_id") or "")
            if msg_type == "pong":
                continue
            if not session_id:
                continue

            async with LOCK:
                browser = V2_SESSIONS.get(session_id)
            if browser is None or browser.client_id != client_id or browser.protocol != "v2":
                continue

            outgoing: dict[str, Any] | None = None
            if msg_type == "output":
                if str(msg.get("encoding") or "") != "base64":
                    outgoing = {"type": "error", "message": "Terminal-agent sendte ukendt outputencoding"}
                else:
                    try:
                        payload = base64.b64decode(str(msg.get("data") or ""), validate=True)
                        outgoing = {"type": "output", "data": payload.decode("utf-8", errors="replace")}
                    except (binascii.Error, ValueError):
                        outgoing = {"type": "error", "message": "Terminal-agent sendte ugyldigt base64-output"}
            elif msg_type == "ready":
                outgoing = {
                    "type": "ready",
                    "session_id": session_id,
                    "privilege_level": msg.get("privilege_level"),
                    "cols": browser.cols,
                    "rows": browser.rows,
                }
            elif msg_type == "exit":
                outgoing = {"type": "exit", "session_id": session_id, "code": int(msg.get("exit_code", -1))}
            elif msg_type == "error":
                outgoing = {
                    "type": "error",
                    "session_id": session_id,
                    "message": str(msg.get("error") or "Terminal-agenten rapporterede en fejl")[:500],
                }

            if outgoing is not None:
                try:
                    await _send_json(browser.websocket, outgoing)
                except Exception:
                    pass

            if msg_type == "exit":
                async with LOCK:
                    if V2_SESSIONS.get(session_id) is browser:
                        V2_SESSIONS.pop(session_id, None)
                    if browser.agent_session_id == session_id:
                        browser.agent_session_id = None

            if msg_type == "ready":
                # seq-1200 opens at 120x32. Apply the browser's negotiated size
                # only after the local broker has acknowledged the session.
                await _send_to_domain_agent(
                    client_id,
                    {"type": "resize", "session_id": session_id, "cols": browser.cols, "rows": browser.rows},
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log_safe_exception(
            logger, exc, event="terminal_v2_agent_ws_failed", level=logging.ERROR,
            client_id=client_id, connection_id=connection_id, connection_type="terminal_domain_agent"
        )
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
        async with LOCK:
            conn = DOMAIN_CLIENTS.get(client_id)
            if conn is not None and conn.websocket is websocket:
                DOMAIN_CLIENTS.pop(client_id, None)
        async with LOCK:
            orphaned = [
                (session_id, browser)
                for session_id, browser in V2_SESSIONS.items()
                if browser.client_id == client_id
            ]
            for session_id, browser in orphaned:
                V2_SESSIONS.pop(session_id, None)
                if browser.agent_session_id == session_id:
                    browser.agent_session_id = None
        for session_id, browser in orphaned:
            with Session(engine) as session:
                mark_terminal_agent_disconnected(
                    session,
                    session_id=session_id,
                    credential_id=credential.id,
                )
                session.commit()
            try:
                await _send_json(
                    browser.websocket,
                    {"type": "error", "session_id": session_id, "message": "Terminal-agenten blev afbrudt."},
                )
            except Exception:
                pass

        logger.info(
            "terminal_v2_agent_disconnected client_id=%s credential_id=%s connection_id=%s",
            client_id, credential.id, connection_id,
        )
        await _broadcast_status(client_id, "user")
        await _broadcast_status(client_id, "admin")


def _client_exists_and_accessible(client_id: int, principal: User) -> bool:
    if not getattr(principal, "is_superadmin", False) or not getattr(principal, "is_active", False):
        return False
    with Session(engine) as session:
        client = session.get(TerminalClient, client_id)
        return bool(client is not None and client.status == "approved")


async def _close_with_reason(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason[:120])
    except Exception:
        pass


async def _start_v2_browser_session(
    browser: BrowserSession,
    *,
    user: User,
    step_up_verified_at,
    cols: int,
    rows: int,
    source_ip: Optional[str],
    user_agent: Optional[str],
) -> bool:
    async with LOCK:
        conn = DOMAIN_CLIENTS.get(browser.client_id)
    if conn is None:
        return False
    if browser.agent_session_id:
        await _send_json(browser.websocket, {"type": "error", "message": "Terminalsessionen er allerede aktiv"})
        return True

    agent_session_id = str(uuid.uuid4())
    try:
        with Session(engine) as session:
            credential = session.get(TerminalCredential, conn.credential_id)
            if (
                credential is None
                or credential.revoked_at is not None
                or int(credential.token_version) != int(conn.token_version)
            ):
                raise HTTPException(status_code=401, detail="Terminal credential er ikke længere gyldigt")
            terminal_session = create_browser_terminal_session(
                session,
                session_id=agent_session_id,
                client_id=browser.client_id,
                user=user,
                mode=browser.mode,
                source_ip=source_ip,
                user_agent=user_agent,
            )
            root_grant = None
            if browser.mode == "admin":
                # Persist the parent TerminalSession before adding RootTerminalGrant.
                # These mappers have no ORM relationship, so relying on unit-of-work
                # ordering can insert the grant first and violate its session FK.
                session.flush([terminal_session])
                root_grant = issue_root_terminal_grant(
                    session,
                    terminal_session=terminal_session,
                    user=user,
                    credential=credential,
                    step_up_verified_at=step_up_verified_at,
                )
            payload = terminal_session_start_message(terminal_session, root_grant=root_grant)
            session.commit()
    except HTTPException as exc:
        await _send_json(browser.websocket, {"type": "error", "message": str(exc.detail)})
        return True
    except Exception as exc:
        log_safe_exception(
            logger, exc, event="terminal_v2_session_prepare_failed", level=logging.ERROR,
            client_id=browser.client_id, session_id=browser.session_id, user_id=browser.user_id, mode=browser.mode,
        )
        await _send_json(browser.websocket, {"type": "error", "message": "Terminalsessionen kunne ikke oprettes."})
        return True

    browser.protocol = "v2"
    browser.agent_session_id = agent_session_id
    browser.agent_close_sent = False
    browser.admin_step_up_failures = 0
    browser.cols = cols
    browser.rows = rows
    async with LOCK:
        V2_SESSIONS[agent_session_id] = browser
    if not await _send_to_domain_agent(browser.client_id, payload):
        async with LOCK:
            if V2_SESSIONS.get(agent_session_id) is browser:
                V2_SESSIONS.pop(agent_session_id, None)
        with Session(engine) as session:
            if browser.user_id is not None:
                mark_browser_terminal_closed(session, session_id=agent_session_id, user_id=browser.user_id)
                session.commit()
        browser.agent_session_id = None
        browser.protocol = "pending"
        await _send_json(browser.websocket, {"type": "error", "message": "Kunne ikke sende sessionen til Terminal-agenten."})
    return True


async def _stage_script_v2(browser: BrowserSession, *, filename: str, content_b64: str) -> bool:
    try:
        decoded = base64.b64decode(content_b64, validate=True)
    except (binascii.Error, ValueError):
        await _send_json(browser.websocket, {"type": "error", "message": "Clipboard/script er ikke gyldig base64"})
        return False
    if len(decoded) > 1_000_000:
        await _send_json(browser.websocket, {"type": "error", "message": "Clipboard/script er for stort til Terminal-agenten"})
        return False

    clean_name = "".join(ch for ch in filename if ch.isalnum() or ch in "._-").strip(".-")[:80] or "clipboard.sh"
    agent_session_id = browser.agent_session_id
    if not agent_session_id:
        await _send_json(browser.websocket, {"type": "error", "message": "Terminalsessionen er ikke aktiv"})
        return False
    remote_path = f"/tmp/clientflow-{agent_session_id[:12]}-{clean_name}"
    # Stage without executing the pasted script. Echo is disabled while the
    # base64 heredoc is transferred; the final `bash <file>` is inserted into
    # the prompt without Enter, preserving the current frontend behaviour.
    prefix = f"stty -echo; umask 077; base64 -d > '{remote_path}' <<'CLIENTFLOW_B64'\r"
    suffix = (
        f"\rCLIENTFLOW_B64\rchmod 700 '{remote_path}'; stty echo; printf '\\r\\n'\r"
        f"bash '{remote_path}'"
    )
    pieces = [prefix]
    pieces.extend(content_b64[i:i + STAGED_INPUT_CHUNK_CHARS] + "\r" for i in range(0, len(content_b64), STAGED_INPUT_CHUNK_CHARS))
    pieces.append(suffix)
    for piece in pieces:
        if not await _send_to_domain_agent(
            browser.client_id,
            {"type": "input", "session_id": agent_session_id, "data": piece, "encoding": "utf-8"},
        ):
            await _send_json(browser.websocket, {"type": "error", "message": "Scriptet kunne ikke stages på klienten."})
            return False
    return True


@router.post("/browser-ticket", response_model=TerminalBrowserTicketResponse)
def create_terminal_browser_ws_ticket(
    payload: TerminalBrowserTicketRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_superadmin_user),
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> TerminalBrowserTicketResponse:
    """Create one Terminal-owned ticket bound to user, client and terminal mode."""
    enforce_request_rate_limit(
        request,
        bucket="terminal-browser-ws-ticket",
        max_attempts=120,
        window_seconds=60,
        detail="For mange Terminal WebSocket-forbindelsesforsøg. Prøv igen om lidt.",
    )

    if not _client_exists_and_accessible(payload.client_id, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Terminal-klient ikke fundet",
        )

    auth_session_binding = require_active_browser_auth_session_binding(
        session,
        token=token,
        user=user,
    )

    capability = "terminal_admin" if payload.mode == TerminalBrowserMode.ADMIN else "terminal_user"
    try:
        issued = issue_terminal_browser_ws_ticket(
            user=user,
            client_id=payload.client_id,
            capability=capability,
            auth_session_binding=auth_session_binding,
        )
    except TerminalBrowserWsTicketStoreFull as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Terminal WebSocket-forbindelser er midlertidigt utilgængelige",
        ) from exc

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    logger.info(
        "terminal_browser_ws_ticket_issued client_id=%s user_id=%s mode=%s",
        payload.client_id,
        user.id,
        payload.mode.value,
    )
    return TerminalBrowserTicketResponse(
        ticket=issued.ticket,
        subprotocol=issued.subprotocol,
        expires_at=issued.expires_at,
    )


@router.websocket("/browser/{client_id}/ws")
async def terminal_browser_ws(
    websocket: WebSocket,
    client_id: int,
    mode: str = Query(default="user"),
):
    """Frontend/browserens terminal WebSocket."""
    mode = _normalize_mode(mode)

    if not _ws_origin_allowed(websocket):
        await _close_with_reason(websocket, 4403, "Ugyldig WebSocket Origin")
        return

    capability = "terminal_admin" if mode == "admin" else "terminal_user"
    with Session(engine) as session:
        user, selected_subprotocol, auth_session_binding = authenticate_terminal_browser_websocket_with_context(
            websocket,
            client_id=client_id,
            capability=capability,
            session=session,
        )
    if not user:
        await _close_with_reason(websocket, 4401, "Ikke logget ind")
        return

    # Remote terminal er bevidst superadmin-only.
    # mode=admin giver root/admin-terminal og må ikke åbnes af almindelige admins.
    if not getattr(user, "is_superadmin", False):
        await _close_with_reason(websocket, 4403, "Kun superadmin må åbne remote terminal")
        return
    if mode == "admin" and not auth_session_binding:
        await _close_with_reason(websocket, 4401, "Admin-terminal kræver en login-session med sikkerhedsbinding")
        return

    if not _client_exists_and_accessible(client_id, user):
        await _close_with_reason(websocket, 4404, "Klient ikke fundet eller ingen adgang")
        return

    await websocket.accept(subprotocol=selected_subprotocol)
    session_id = uuid.uuid4().hex
    browser = BrowserSession(
        session_id=session_id,
        client_id=client_id,
        mode=mode,
        websocket=websocket,
        user_id=user.id,
        username=user.username,
        user_token_version=int(getattr(user, "token_version", 0) or 0),
        auth_session_binding=auth_session_binding,
    )

    async with LOCK:
        BROWSERS[session_id] = browser
        domain_conn = DOMAIN_CLIENTS.get(client_id)
    agent_connected = bool(domain_conn)

    logger.info(
        "terminal_browser_connected client_id=%s session_id=%s connection_type=terminal_browser user_id=%s role=%s mode=%s agent_connected=%s protocol=%s",
        client_id, session_id, user.id,
        getattr(getattr(user, "role", None), "value", getattr(user, "role", None)),
        mode, agent_connected, "v2" if domain_conn else "none"
    )

    await _send_json(
        websocket,
        {
            "type": "hello",
            "role": "browser",
            "session_id": session_id,
            "client_id": client_id,
            "mode": mode,
            "client_connected": agent_connected,
            "agent_protocol": "v2" if domain_conn else None,
        },
    )

    if not agent_connected:
        label = "Admin-terminal-agenten" if mode == "admin" else "Bruger-terminal-agenten"
        await _send_json(
            websocket,
            {
                "type": "status",
                "level": "warning",
                "message": f"{label} er ikke forbundet på klienten endnu.",
            },
        )

    activity_lease_task = asyncio.create_task(
        maintain_activity_lease(
            engine,
            client_id=client_id,
            domain="terminal",
            session_id=session_id,
        )
    )
    receive_task = None
    next_auth_recheck = time.monotonic() + TERMINAL_BROWSER_AUTH_RECHECK_SECONDS
    try:
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            timeout = max(0.0, next_auth_recheck - time.monotonic())
            done, _ = await asyncio.wait(
                {receive_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receive_task not in done:
                current_user = _current_terminal_superadmin(browser)
                if current_user is None:
                    await _close_with_reason(websocket, 4403, "Superadministrator-sessionen er ikke længere gyldig")
                    return
                user = current_user
                next_auth_recheck = time.monotonic() + TERMINAL_BROWSER_AUTH_RECHECK_SECONDS
                continue

            raw = receive_task.result()
            receive_task = asyncio.create_task(websocket.receive_text())
            if time.monotonic() >= next_auth_recheck:
                current_user = _current_terminal_superadmin(browser)
                if current_user is None:
                    await _close_with_reason(websocket, 4403, "Superadministrator-sessionen er ikke længere gyldig")
                    return
                user = current_user
                next_auth_recheck = time.monotonic() + TERMINAL_BROWSER_AUTH_RECHECK_SECONDS
            try:
                decoded = decode_json_message(
                    raw,
                    allowed_types=BROWSER_MESSAGE_TYPES | {"ping"},
                    max_chars=MAX_STAGED_SCRIPT_B64_CHARS + 10_000,
                    unknown_type_prefix="Ukendt terminaltype",
                )
            except ProtocolError as exc:
                if exc.close_code:
                    await _close_with_reason(websocket, exc.close_code, exc.message)
                    return
                await _send_json(websocket, {"type": "error", "message": exc.message})
                continue
            msg = decoded.payload
            msg_type = decoded.type
            if msg_type == "ping":
                await _send_json(websocket, {"type": "pong", "ts": time.time()})
                continue

            if msg_type == "open":
                # Re-check immediately at every PTY open in addition to the bounded
                # periodic check that also revokes already-running sessions.
                current_user = _current_terminal_superadmin(browser)
                if current_user is None:
                    await _close_with_reason(websocket, 4403, "Superadministrator-sessionen er ikke længere gyldig")
                    return
                user = current_user
                next_auth_recheck = time.monotonic() + TERMINAL_BROWSER_AUTH_RECHECK_SECONDS

                cols, rows = _terminal_size(msg)
                step_up_verified_at = None
                if mode == "admin":
                    try:
                        step_up_token = bounded_text(
                            msg, "step_up_token", maximum=4096, required=False, strip=True,
                            too_long_message="Admin-terminal step-up token er for lang",
                        )
                        step_up_password = bounded_text(
                            msg, "password", maximum=512, required=False, strip=False,
                            too_long_message="Adgangskoden er for lang",
                        )
                        if step_up_token:
                            step_up_verified_at = verify_admin_terminal_step_up_token(
                                user,
                                step_up_token,
                                auth_session_binding=browser.auth_session_binding or "",
                            )
                        elif step_up_password:
                            step_up_verified_at, issued_step_up_token, step_up_expires_at = verify_admin_terminal_step_up(
                                user,
                                step_up_password,
                                auth_session_binding=browser.auth_session_binding or "",
                            )
                            await _send_json(
                                websocket,
                                {
                                    "type": "admin_step_up",
                                    "token": issued_step_up_token,
                                    "expires_at": step_up_expires_at.isoformat().replace("+00:00", "Z"),
                                },
                            )
                        else:
                            await _send_json(
                                websocket,
                                {
                                    "type": "error",
                                    "code": "admin_step_up_required",
                                    "message": "Admin-terminal kræver bekræftelse med din adgangskode",
                                },
                            )
                            continue
                    except ProtocolError as exc:
                        await _send_json(websocket, {"type": "error", "message": exc.message})
                        continue
                    except HTTPException as exc:
                        if step_up_password and exc.status_code == 401:
                            browser.admin_step_up_failures += 1
                        code = "admin_step_up_required" if exc.status_code == 401 else "admin_step_up_failed"
                        await _send_json(websocket, {"type": "error", "code": code, "message": str(exc.detail)})
                        if browser.admin_step_up_failures >= 5:
                            await _close_with_reason(websocket, 4403, "For mange fejlede Admin-terminal step-up forsøg")
                            return
                        continue

                if await _start_v2_browser_session(
                    browser,
                    user=user,
                    step_up_verified_at=step_up_verified_at,
                    cols=cols,
                    rows=rows,
                    source_ip=websocket.client.host if websocket.client else None,
                    user_agent=websocket.headers.get("user-agent"),
                ):
                    browser.admin_step_up_failures = 0
                    continue

                await _send_json(
                    websocket,
                    {"type": "error", "message": "Terminal-agenten er ikke forbundet."},
                )
                continue

            if msg_type == "stage_script":
                try:
                    content_b64 = bounded_text(
                        msg, "content_b64", maximum=MAX_STAGED_SCRIPT_B64_CHARS, required=True,
                        missing_message="Clipboard/script-indhold mangler",
                        too_long_message="Clipboard/script er for stort",
                    )
                    filename = bounded_text(msg, "filename", maximum=120, default="clipboard.sh")
                except ProtocolError as exc:
                    await _send_json(websocket, {"type": "error", "message": exc.message})
                    continue
                if browser.protocol == "v2":
                    await _stage_script_v2(browser, filename=filename, content_b64=content_b64)
                else:
                    await _send_json(websocket, {"type": "error", "message": "Terminalsessionen er ikke aktiv"})
                continue

            if msg_type == "input":
                try:
                    data = bounded_text(
                        msg, "data", maximum=MAX_INPUT_CHARS,
                        too_long_message="Terminal-input er for langt",
                    )
                except ProtocolError as exc:
                    await _send_json(websocket, {"type": "error", "message": exc.message})
                    continue
                if not data:
                    continue
                if browser.protocol == "v2" and browser.agent_session_id:
                    await _send_to_domain_agent(
                        client_id,
                        {"type": "input", "session_id": browser.agent_session_id, "data": data, "encoding": "utf-8"},
                    )
                else:
                    await _send_json(websocket, {"type": "error", "message": "Terminalsessionen er ikke aktiv"})
                continue

            if msg_type == "resize":
                cols, rows = _terminal_size(msg)
                browser.cols = cols
                browser.rows = rows
                if browser.protocol == "v2" and browser.agent_session_id:
                    await _send_to_domain_agent(
                        client_id,
                        {"type": "resize", "session_id": browser.agent_session_id, "cols": cols, "rows": rows},
                    )
                else:
                    await _send_json(websocket, {"type": "error", "message": "Terminalsessionen er ikke aktiv"})
                continue

            if msg_type == "close":
                if browser.protocol == "v2" and browser.agent_session_id and not browser.agent_close_sent:
                    browser.agent_close_sent = await _send_to_domain_agent(
                        client_id,
                        {"type": "close", "session_id": browser.agent_session_id},
                    )
                continue

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log_safe_exception(
            logger, exc, event="terminal_browser_ws_failed", level=logging.ERROR,
            client_id=client_id, session_id=session_id, connection_type="terminal_browser",
            user_id=user.id, mode=mode
        )
        try:
            await _send_json(websocket, {"type": "error", "message": "Terminalforbindelsen fejlede."})
        except Exception:
            pass
    finally:
        activity_lease_task.cancel()
        try:
            await activity_lease_task
        except asyncio.CancelledError:
            pass
        try:
            with Session(engine) as activity_session:
                end_activity_lease(
                    activity_session,
                    client_id=client_id,
                    domain="terminal",
                    session_id=session_id,
                    reason="browser_disconnected",
                )
                activity_session.commit()
        except Exception:
            logger.warning(
                "terminal_activity_lease_close_failed client_id=%s session_id=%s",
                client_id, session_id, exc_info=True,
            )
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
        async with LOCK:
            removed_browser = BROWSERS.pop(session_id, None)
            domain_conn = DOMAIN_CLIENTS.get(client_id)

        logger.info(
            "terminal_browser_disconnected client_id=%s session_id=%s connection_type=terminal_browser user_id=%s mode=%s protocol=%s",
            client_id, session_id, user.id, mode, removed_browser.protocol if removed_browser else "unknown"
        )

        if removed_browser and removed_browser.protocol == "v2" and removed_browser.agent_session_id:
            agent_session_id = removed_browser.agent_session_id
            async with LOCK:
                if V2_SESSIONS.get(agent_session_id) is removed_browser:
                    V2_SESSIONS.pop(agent_session_id, None)
            if domain_conn and not removed_browser.agent_close_sent:
                try:
                    await _send_json(domain_conn.websocket, {"type": "close", "session_id": agent_session_id})
                    removed_browser.agent_close_sent = True
                except Exception:
                    pass
            with Session(engine) as session:
                mark_browser_terminal_closed(session, session_id=agent_session_id, user_id=int(user.id))
                session.commit()
            removed_browser.agent_session_id = None


async def _broadcast_status(client_id: int, mode: str) -> None:
    async with LOCK:
        domain_conn = DOMAIN_CLIENTS.get(client_id)
        connected = bool(domain_conn)
        browsers = [b for b in BROWSERS.values() if b.client_id == client_id and b.mode == mode]

    for browser in browsers:
        try:
            await _send_json(
                browser.websocket,
                {
                    "type": "agent_status",
                    "client_connected": connected,
                    "mode": mode,
                    "hostname": None,
                    "euid": None,
                    "agent_protocol": "v2" if domain_conn else None,
                },
            )
        except Exception:
            pass


@router.get("/clients/{client_id}/status")
def terminal_status(
    client_id: int,
    mode: str = Query(default="user"),
    user: User = Depends(get_current_superadmin_user),
):
    """Letvægts-status endpoint til debugging. Kræver superadmin."""
    mode = _normalize_mode(mode)
    if not _client_exists_and_accessible(client_id, user):
        raise HTTPException(status_code=404, detail="Klient ikke fundet eller ingen adgang")
    domain_conn = DOMAIN_CLIENTS.get(client_id)
    return {
        "client_id": client_id,
        "mode": mode,
        "client_connected": bool(domain_conn),
        "agent_protocol": "v2" if domain_conn else None,
        "credential_id": domain_conn.credential_id if domain_conn else None,
        "hostname": None,
        "euid": None,
        "connected_modes": ["user", "admin"] if domain_conn else [],
    }
