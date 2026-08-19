"""Remote Desktop v2 broker for the isolated seq-1200 agent contract.

Browser-facing routes intentionally retain the existing frontend contract.
Agent-facing authentication, status, control and file channels are owned by the
Remote Desktop domain and do not use the shared client-token verifier.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import time
from typing import Any, Optional
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from ..auth import validate_browser_auth_session_binding, verify_ws_token
from ..client_activity import end_activity_lease, maintain_activity_lease
from ..db import engine
from ..models import Client, User
from ..remote_desktop_v2 import (
    authorize_remote_desktop_session,
    bearer_token,
    close_remote_desktop_session,
    record_remote_desktop_event,
    update_remote_desktop_agent_status,
    verify_remote_desktop_agent_token,
)
from ..remote_desktop_v2_models import RemoteDesktopAgentStatus, RemoteDesktopClient, RemoteDesktopCredential
from ..remote_desktop_session_models import RemoteDesktopSession, RemoteDesktopSessionEvent
from ..websocket_auth import authenticate_browser_websocket_with_context
from ..websocket_protocol import ProtocolError, decode_json_message

router = APIRouter(tags=["remote-desktop-v2"])
logger = logging.getLogger(__name__)

MAX_BROWSER_MESSAGE_CHARS = 2_100_000
MAX_AGENT_CONTROL_CHARS = 20_000_000
MAX_AGENT_FILE_CHARS = 4_500_000
MAX_TRANSFER_BYTES = min(
    max(1, int(os.getenv("CLIENTFLOW_REMOTE_DESKTOP_MAX_TRANSFER_BYTES", str(100 * 1024 * 1024)))),
    100 * 1024 * 1024,
)
TRANSFER_TTL_SECONDS = min(
    max(60, int(os.getenv("CLIENTFLOW_REMOTE_DESKTOP_TRANSFER_TTL_SECONDS", str(30 * 60)))),
    4 * 3600,
)
TRANSFER_DIR = Path(os.getenv("CLIENTFLOW_REMOTE_DESKTOP_TRANSFER_DIR", "/tmp/clientflow_remote_desktop_transfers_v2"))
REMOTE_DESKTOP_BROWSER_AUTH_RECHECK_SECONDS = 15.0
REMOTE_DESKTOP_AGENT_AUTH_RECHECK_SECONDS = 15.0
UPLOAD_CHUNK_BYTES = 512 * 1024
ALLOWED_WS_ORIGINS = [
    item.strip().rstrip("/")
    for item in (os.getenv("CORS_ALLOW_ORIGINS") or os.getenv("FRONTEND_URL") or "").split(",")
    if item.strip()
]
IS_PRODUCTION = os.getenv("ENVIRONMENT", "production") == "production"
_SAFE_NAME = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,255}$")

BROWSER_MESSAGE_TYPES = {
    "start_stream", "stop_stream", "mouse", "key", "text", "shout",
    "request_frame", "file_list_request", "file_download_request",
    "file_multi_download_request", "file_delete_request",
    "file_rename_request", "file_mkdir_request", "file_move_request",
}


@dataclass
class AgentChannel:
    client_id: int
    credential_id: str
    token_version: int
    websocket: WebSocket
    connected_at: float = field(default_factory=time.time)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class BrowserSession:
    session_id: str
    client_id: int
    websocket: WebSocket
    user_id: int
    username: str
    user_token_version: int
    auth_session_binding: str
    expires_at: datetime
    connected_at: float = field(default_factory=time.time)
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None


@dataclass
class DownloadTransfer:
    transfer_id: str
    client_id: int
    session_id: str
    filename: str
    path: Path
    size_bytes: int
    sha256: str
    owner_user_id: int
    created_at: float = field(default_factory=time.time)


@dataclass
class DownloadState:
    transfer_id: str
    client_id: int
    session_id: str
    path: Path
    relative_path: str = ""
    filename: str = "download.bin"
    expected_size: Optional[int] = None
    received: int = 0
    digest: Any = field(default_factory=hashlib.sha256)


@dataclass
class OperationExpectation:
    frontend_type: str
    batch_id: Optional[str] = None
    show_hidden: bool = False


@dataclass
class OperationBatch:
    frontend_type: str
    total: int
    done: int = 0
    errors: list[str] = field(default_factory=list)


CONTROL_AGENTS: dict[int, AgentChannel] = {}
FILE_AGENTS: dict[int, AgentChannel] = {}
BROWSERS: dict[str, BrowserSession] = {}
DOWNLOADS: dict[str, DownloadState] = {}
TRANSFERS: dict[str, DownloadTransfer] = {}
UPLOAD_ACKS: dict[tuple[str, str], asyncio.Queue[dict[str, Any]]] = {}
DIRECT_OPERATION_ACKS: dict[str, asyncio.Queue[dict[str, Any]]] = {}
OPERATION_EXPECTATIONS: dict[str, deque[OperationExpectation]] = defaultdict(deque)
OPERATION_BATCHES: dict[str, OperationBatch] = {}
LOCK = asyncio.Lock()


class AgentStatusBody(BaseModel):
    schema_version: int = Field(ge=1)
    observed_state: str = Field(min_length=1, max_length=80)
    status_payload: dict[str, Any] = Field(default_factory=dict)
    agent_version: Optional[str] = Field(default=None, max_length=80)
    boot_id: Optional[str] = Field(default=None, max_length=128)


class AgentEventBody(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    details: dict[str, Any] = Field(default_factory=dict)


def _ws_origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return not IS_PRODUCTION
    return origin.rstrip("/") in ALLOWED_WS_ORIGINS


async def _close_with_reason(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason[:120])
    except Exception:
        pass


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


async def _send_agent(channel: AgentChannel, payload: dict[str, Any]) -> None:
    async with channel.send_lock:
        await _send_json(channel.websocket, payload)


def _extract_agent_bearer(websocket: WebSocket) -> str:
    header = websocket.headers.get("authorization") or ""
    return bearer_token(header)


def _extract_http_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("access_token") or None


def _get_http_user(request: Request) -> Optional[User | Client]:
    token = _extract_http_token(request)
    if not token:
        return None
    with Session(engine) as session:
        return verify_ws_token(token, session)


def _require_superadmin(principal: User | Client | None) -> User:
    if not isinstance(principal, User):
        raise HTTPException(status_code=401, detail="Ikke logget ind")
    if not getattr(principal, "is_superadmin", False) or not getattr(principal, "is_active", False):
        raise HTTPException(status_code=403, detail="Kun superadmin må bruge Remote Desktop")
    if principal.id is None:
        raise HTTPException(status_code=401, detail="Bruger mangler database-id")
    return principal


def _platform_client_accessible(client_id: int, user: User) -> bool:
    with Session(engine) as session:
        client = session.get(Client, client_id)
        return bool(client and getattr(user, "is_superadmin", False))


def _configured_resolution(client_id: int) -> tuple[Optional[int], Optional[int]]:
    try:
        with Session(engine) as session:
            client = session.get(Client, client_id)
            if not client:
                return None, None
            for w_name, h_name in (
                ("display_resolution_current_width", "display_resolution_current_height"),
                ("display_resolution_width", "display_resolution_height"),
            ):
                try:
                    width = int(getattr(client, w_name, 0) or 0)
                    height = int(getattr(client, h_name, 0) or 0)
                except (TypeError, ValueError):
                    continue
                if width > 0 and height > 0:
                    return width, height
    except Exception:
        pass
    return None, None


def _agent_ready(client_id: int) -> bool:
    return client_id in CONTROL_AGENTS and client_id in FILE_AGENTS


def _remote_desktop_browser_auth_state(browser: BrowserSession) -> tuple[Optional[User], str]:
    """Revalidate login-session, superadmin role and persisted RD session lifetime."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        user = validate_browser_auth_session_binding(
            session,
            user_id=browser.user_id,
            user_token_version=browser.user_token_version,
            auth_session_binding=browser.auth_session_binding,
        )
        row = session.get(RemoteDesktopSession, browser.session_id)
        rd_client = session.get(RemoteDesktopClient, browser.client_id)
        if user is None or not getattr(user, "is_superadmin", False):
            return None, "login_session_invalid"
        if rd_client is None or rd_client.status != "approved":
            return None, "remote_desktop_client_disabled"
        if row is None or row.client_id != browser.client_id:
            return None, "remote_desktop_session_missing"
        if row.status in {"revoked", "expired", "failed"}:
            return None, row.status
        if row.expires_at <= now:
            row.status = "expired"
            row.disconnected_at = row.disconnected_at or now
            row.last_activity_at = now
            row.close_reason = "session_expired"
            session.add(row)
            session.add(RemoteDesktopSessionEvent(
                id=str(uuid.uuid4()),
                remote_desktop_session_id=row.id,
                event_type="expired",
                actor_user_id=browser.user_id,
                created_at=now,
                details={"reason": "session_expired"},
            ))
            session.commit()
            return None, "expired"
        return user, "ok"


def _remote_desktop_agent_channel_valid(channel: AgentChannel) -> bool:
    """Bounded revalidation for an established RD agent channel."""
    with Session(engine) as session:
        client = session.get(RemoteDesktopClient, channel.client_id)
        credential = session.get(RemoteDesktopCredential, channel.credential_id)
    return bool(
        client is not None
        and client.status == "approved"
        and credential is not None
        and credential.client_id == channel.client_id
        and credential.revoked_at is None
        and int(credential.token_version) == int(channel.token_version)
    )


async def _browser_for_session(session_id: str, client_id: int) -> Optional[BrowserSession]:
    async with LOCK:
        browser = BROWSERS.get(session_id)
    return browser if browser and browser.client_id == client_id else None


async def _send_browser(session_id: str, client_id: int, payload: dict[str, Any]) -> None:
    browser = await _browser_for_session(session_id, client_id)
    if browser:
        try:
            await _send_json(browser.websocket, payload)
        except Exception:
            pass


async def _broadcast_agent_status(client_id: int) -> None:
    async with LOCK:
        browsers = [item for item in BROWSERS.values() if item.client_id == client_id]
        ready = _agent_ready(client_id)
    width, height = _configured_resolution(client_id)
    payload = {
        "type": "agent_status",
        "agent_connected": ready,
        "control_connected": client_id in CONTROL_AGENTS,
        "files_connected": client_id in FILE_AGENTS,
        "width": width,
        "height": height,
    }
    for browser in browsers:
        try:
            await _send_json(browser.websocket, payload)
        except Exception:
            pass


def _cleanup_transfers() -> None:
    now = time.time()
    for transfer_id, item in list(TRANSFERS.items()):
        if now - item.created_at <= TRANSFER_TTL_SECONDS:
            continue
        TRANSFERS.pop(transfer_id, None)
        try:
            item.path.unlink(missing_ok=True)
        except OSError:
            pass


def _release_transfer(transfer_id: str) -> None:
    transfer = TRANSFERS.pop(transfer_id, None)
    if transfer is None:
        return
    try:
        transfer.path.unlink(missing_ok=True)
    except OSError:
        pass


def _safe_filename(value: object) -> str:
    raw = str(value or "upload.bin").replace("\\", "/")
    name = raw.rsplit("/", 1)[-1]
    if not _SAFE_NAME.fullmatch(name) or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Remote Desktop-filnavnet er ugyldigt")
    return name


def _safe_relative_path(value: object) -> str:
    raw = str(value or "").replace("\\", "/")
    if raw.startswith("/"):
        raise HTTPException(status_code=400, detail="Remote Desktop-filstien er ugyldig")
    raw = raw.rstrip("/")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        if raw:
            raise HTTPException(status_code=400, detail="Remote Desktop-filstien er ugyldig")
        return ""
    return path.as_posix() if path.parts else ""


def _join_relative(parent: object, name: object) -> str:
    parent_path = _safe_relative_path(parent)
    child = str(name or "").strip()
    if not _SAFE_NAME.fullmatch(child) or child in {".", ".."}:
        raise HTTPException(status_code=400, detail="Remote Desktop-filnavnet er ugyldigt")
    return f"{parent_path}/{child}" if parent_path else child


def _parse_upload_conflict_strategies(raw: str, count: int) -> list[str]:
    if not raw:
        return ["keep_both"] * count
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Uploadens konfliktstrategier er ugyldige") from exc
    if not isinstance(parsed, list) or len(parsed) != count:
        raise HTTPException(status_code=400, detail="Uploadens konfliktstrategier matcher ikke filerne")
    strategies = [str(item or "keep_both") for item in parsed]
    if any(item != "keep_both" for item in strategies):
        raise HTTPException(
            status_code=400,
            detail="Remote Desktop v2 understøtter kun 'Behold begge' for filer, der sendes til backend",
        )
    return strategies


def _map_file_entries(entries: object, *, show_hidden: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return result
    for item in entries:
        if not isinstance(item, dict):
            continue
        relative = str(item.get("path") or "")
        name = str(item.get("name") or Path(relative).name)
        hidden = name.startswith(".")
        if hidden and not show_hidden:
            continue
        result.append({
            "name": name,
            "relative_path": relative,
            "is_dir": item.get("type") == "directory",
            "size_bytes": item.get("size_bytes"),
            "modified_at": item.get("modified_at"),
            "hidden": hidden,
        })
        if len(result) >= 500:
            break
    return result


def _parent_path(path: str) -> str:
    pure = PurePosixPath(path)
    if not pure.parts or len(pure.parts) == 1:
        return ""
    return PurePosixPath(*pure.parts[:-1]).as_posix()


def _input_key_sequence(raw: object) -> list[dict[str, Any]]:
    key_map = {
        "return": "Enter", "enter": "Enter", "escape": "Escape", "backspace": "Backspace",
        "delete": "Delete", "tab": "Tab", "up": "ArrowUp", "down": "ArrowDown",
        "left": "ArrowLeft", "right": "ArrowRight", "home": "Home", "end": "End",
        "page_up": "PageUp", "pageup": "PageUp", "page_down": "PageDown", "pagedown": "PageDown",
        "space": " ", "ctrl": "Control", "control": "Control", "alt": "Alt",
        "shift": "Shift", "super": "Meta", "meta": "Meta",
    }
    parts = [part for part in str(raw or "").split("+") if part]
    if not parts:
        return []
    normalized = [key_map.get(part.lower(), part if len(part) == 1 else key_map.get(part, part)) for part in parts]
    if len(normalized) == 1:
        return [{"type": "key", "key": normalized[0], "event": "press"}]
    modifiers = normalized[:-1]
    main = normalized[-1]
    sequence: list[dict[str, Any]] = []
    for modifier in modifiers:
        sequence.append({"type": "key", "key": modifier, "event": "down"})
    sequence.append({"type": "key", "key": main, "event": "press"})
    for modifier in reversed(modifiers):
        sequence.append({"type": "key", "key": modifier, "event": "up"})
    return sequence


def _mouse_sequence(
    message: dict[str, Any],
    screen_width: Optional[int],
    screen_height: Optional[int],
) -> list[dict[str, Any]]:
    action = str(message.get("action") or message.get("event") or "move")
    width, height = screen_width, screen_height
    moves: list[dict[str, Any]] = []
    if width and height and message.get("x") is not None and message.get("y") is not None:
        try:
            x = min(1.0, max(0.0, float(message["x"]) / float(width)))
            y = min(1.0, max(0.0, float(message["y"]) / float(height)))
            moves.append({"type": "mouse", "event": "move", "x": x, "y": y})
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    button = int(message.get("button", 1) or 1)
    if action == "move":
        return moves or [{"type": "mouse", "event": "move", "x": 0.0, "y": 0.0}]
    if action == "scroll":
        return moves + [{"type": "mouse", "event": "scroll", "delta": int(message.get("delta", 0) or 0)}]
    if action in {"down", "up"}:
        return moves + [{"type": "mouse", "event": action, "button": button}]
    if action in {"click", "right_click"}:
        return moves + [{"type": "mouse", "event": "click", "button": 3 if action == "right_click" else button}]
    if action == "double_click":
        return moves + [
            {"type": "mouse", "event": "click", "button": button},
            {"type": "mouse", "event": "click", "button": button},
        ]
    return moves + [{"type": "mouse", "event": "click", "button": button}]


async def _open_session_on_available_channels(browser: BrowserSession) -> None:
    control = CONTROL_AGENTS.get(browser.client_id)
    files = FILE_AGENTS.get(browser.client_id)
    payload = {"type": "session_open", "session_id": browser.session_id}
    if control:
        await _send_agent(control, payload)
    if files:
        await _send_agent(files, payload)


async def _close_session_on_available_channels(browser: BrowserSession) -> None:
    payload = {"type": "session_close", "session_id": browser.session_id}
    control = CONTROL_AGENTS.get(browser.client_id)
    files = FILE_AGENTS.get(browser.client_id)
    if control:
        try:
            await _send_agent(control, payload)
        except Exception:
            pass
    if files:
        try:
            await _send_agent(files, payload)
        except Exception:
            pass


@router.put("/remote-desktop-agent/clients/{client_id}/status")
def remote_desktop_agent_status(client_id: int, body: AgentStatusBody, request: Request):
    token = bearer_token(request.headers.get("authorization"))
    with Session(engine) as session:
        credential = verify_remote_desktop_agent_token(session, token, client_id=client_id)
        row = update_remote_desktop_agent_status(
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
            "ok": True,
            "client_id": row.client_id,
            "credential_id": row.credential_id,
            "observed_state": row.observed_state,
            "reported_at": row.reported_at,
        }


@router.post("/remote-desktop-agent/clients/{client_id}/sessions/{session_id}/events")
def remote_desktop_agent_event(client_id: int, session_id: str, body: AgentEventBody, request: Request):
    token = bearer_token(request.headers.get("authorization"))
    with Session(engine) as session:
        credential = verify_remote_desktop_agent_token(session, token, client_id=client_id)
        event = record_remote_desktop_event(
            session,
            client_id=client_id,
            session_id=session_id,
            event_type=body.event_type,
            details=body.details,
            credential=credential,
        )
        session.commit()
        return {"ok": True, "event_id": event.id}


async def _authenticate_agent_websocket(websocket: WebSocket, client_id: int):
    try:
        token = _extract_agent_bearer(websocket)
        with Session(engine) as session:
            return verify_remote_desktop_agent_token(session, token, client_id=client_id)
    except HTTPException as exc:
        await _close_with_reason(websocket, 4401 if exc.status_code == 401 else 4403, str(exc.detail))
        return None


def _pop_session_operation_state(session_id: str) -> tuple[list[OperationExpectation], set[str]]:
    expectations = list(OPERATION_EXPECTATIONS.pop(session_id, deque()))
    batch_ids = {item.batch_id for item in expectations if item.batch_id}
    for batch_id in batch_ids:
        OPERATION_BATCHES.pop(batch_id, None)
    DIRECT_OPERATION_ACKS.pop(session_id, None)
    return expectations, batch_ids


async def _fail_file_channel_state(client_id: int, reason: str) -> None:
    async with LOCK:
        session_ids = [item.session_id for item in BROWSERS.values() if item.client_id == client_id]

    for session_id in session_ids:
        expectations, _ = _pop_session_operation_state(session_id)
        notified_batches: set[str] = set()
        for expected in expectations:
            if expected.batch_id:
                if expected.batch_id in notified_batches:
                    continue
                notified_batches.add(expected.batch_id)
            payload: dict[str, Any] = {
                "type": expected.frontend_type,
                "ok": False,
                "message": reason,
            }
            if expected.frontend_type == "file_list_result":
                payload["entries"] = []
                payload["show_hidden"] = expected.show_hidden
            await _send_browser(session_id, client_id, payload)

        for (upload_session_id, transfer_id), queue in list(UPLOAD_ACKS.items()):
            if upload_session_id != session_id:
                continue
            await queue.put({
                "type": "file_error",
                "session_id": session_id,
                "transfer_id": transfer_id,
                "error": reason,
            })

    for transfer_id, state in list(DOWNLOADS.items()):
        if state.client_id != client_id:
            continue
        DOWNLOADS.pop(transfer_id, None)
        state.path.unlink(missing_ok=True)
        await _send_browser(state.session_id, client_id, {
            "type": "file_download_result",
            "ok": False,
            "message": reason,
        })


async def _register_agent_channel(client_id: int, channel_name: str, channel: AgentChannel) -> None:
    registry = CONTROL_AGENTS if channel_name == "control" else FILE_AGENTS
    async with LOCK:
        old = registry.get(client_id)
        registry[client_id] = channel
        browsers = [item for item in BROWSERS.values() if item.client_id == client_id]
    if channel_name == "files" and old and old.websocket is not channel.websocket:
        await _fail_file_channel_state(
            client_id,
            "Remote Desktop-filkanalen blev genetableret. Prøv filoperationen igen.",
        )
    if old and old.websocket is not channel.websocket:
        try:
            await old.websocket.close(code=4400, reason="Ny Remote Desktop-agentkanal forbandt")
        except Exception:
            pass
    for browser in browsers:
        try:
            await _send_agent(channel, {"type": "session_open", "session_id": browser.session_id})
        except Exception:
            break
    await _broadcast_agent_status(client_id)


async def _unregister_agent_channel(client_id: int, channel_name: str, websocket: WebSocket) -> None:
    registry = CONTROL_AGENTS if channel_name == "control" else FILE_AGENTS
    removed_current = False
    async with LOCK:
        current = registry.get(client_id)
        if current and current.websocket is websocket:
            registry.pop(client_id, None)
            removed_current = True
    if channel_name == "files" and removed_current:
        await _fail_file_channel_state(
            client_id,
            "Remote Desktop-filkanalen blev afbrudt. Prøv filoperationen igen, når forbindelsen er genetableret.",
        )
    await _broadcast_agent_status(client_id)


async def _handle_control_agent_message(client_id: int, credential_id: str, message: dict[str, Any]) -> None:
    session_id = str(message.get("session_id") or "")
    if not session_id:
        return
    browser = await _browser_for_session(session_id, client_id)
    if not browser:
        return
    message_type = str(message.get("type") or "")
    if message_type == "agent_ready":
        with Session(engine) as session:
            try:
                from ..remote_desktop_v2_models import RemoteDesktopCredential
                credential = session.get(RemoteDesktopCredential, credential_id)
                if credential:
                    record_remote_desktop_event(
                        session,
                        client_id=client_id,
                        session_id=session_id,
                        event_type="agent_ready",
                        details={},
                        credential=credential,
                    )
                    session.commit()
            except Exception:
                session.rollback()
        return
    if message_type == "input_result":
        if message.get("ok") is False:
            await _send_browser(session_id, client_id, {"type": "error", "message": str(message.get("error") or "Input fejlede")})
        return
    if message_type == "shout_result":
        await _send_browser(session_id, client_id, {
            "type": "shout_result",
            "ok": bool(message.get("ok")),
            "message": str(message.get("message") or ("Shout out vist på klientskærmen" if message.get("ok") else "Shout out fejlede")),
        })
        return
    if message_type == "error":
        await _send_browser(session_id, client_id, {"type": "error", "message": str(message.get("error") or "Remote Desktop-agentfejl")})
        return
    if message_type in {"frame", "stream_started", "stream_stopped"}:
        payload = dict(message)
        width, height = _configured_resolution(client_id)
        if message_type in {"frame", "stream_started"}:
            try:
                live_width = int(payload.get("screen_width") or payload.get("width") or 0)
                live_height = int(payload.get("screen_height") or payload.get("height") or 0)
            except (TypeError, ValueError):
                live_width = live_height = 0
            if live_width > 0 and live_height > 0:
                browser.screen_width = live_width
                browser.screen_height = live_height
        if message_type == "frame":
            payload.setdefault("screen_width", browser.screen_width or width)
            payload.setdefault("screen_height", browser.screen_height or height)
        await _send_browser(session_id, client_id, payload)


async def _finalize_download(client_id: int, message: dict[str, Any]) -> None:
    transfer_id = str(message.get("transfer_id") or "")
    state = DOWNLOADS.pop(transfer_id, None)
    if state is None:
        return
    try:
        expected_size = int(message.get("size_bytes", -1))
        expected_sha = str(message.get("sha256") or "")
        if (
            state.expected_size is None
            or state.expected_size != expected_size
            or state.received != expected_size
            or state.digest.hexdigest() != expected_sha
        ):
            raise ValueError("Downloadens størrelse eller SHA-256 matcher ikke")
        browser = await _browser_for_session(state.session_id, client_id)
        if browser is None:
            state.path.unlink(missing_ok=True)
            return
        transfer = DownloadTransfer(
            transfer_id=transfer_id,
            client_id=client_id,
            session_id=state.session_id,
            filename=state.filename,
            path=state.path,
            size_bytes=state.received,
            sha256=expected_sha,
            owner_user_id=browser.user_id,
        )
        TRANSFERS[transfer_id] = transfer
        await _send_browser(state.session_id, client_id, {
            "type": "file_download_ready",
            "transfer_id": transfer_id,
            "filename": state.filename,
            "size_bytes": state.received,
            "sha256": expected_sha,
        })
    except Exception as exc:
        state.path.unlink(missing_ok=True)
        await _send_browser(state.session_id, client_id, {
            "type": "file_download_result", "ok": False, "message": str(exc)[:500]
        })


async def _handle_operation_result(client_id: int, session_id: str, message: dict[str, Any]) -> None:
    direct = DIRECT_OPERATION_ACKS.get(session_id)
    if direct is not None:
        await direct.put(message)
        return
    queue = OPERATION_EXPECTATIONS.get(session_id)
    if not queue:
        return
    expected = queue.popleft()
    error = str(message.get("error") or "") if message.get("type") == "file_error" else ""
    if expected.batch_id:
        batch = OPERATION_BATCHES.get(expected.batch_id)
        if batch is None:
            return
        batch.done += 1
        if error:
            batch.errors.append(error)
        if batch.done >= batch.total:
            OPERATION_BATCHES.pop(expected.batch_id, None)
            await _send_browser(session_id, client_id, {
                "type": batch.frontend_type,
                "ok": not batch.errors,
                "message": batch.errors[0] if batch.errors else None,
            })
        return
    await _send_browser(session_id, client_id, {
        "type": expected.frontend_type,
        "ok": not bool(error),
        "message": error or None,
        "path": message.get("path"),
    })


async def _handle_file_agent_message(client_id: int, message: dict[str, Any]) -> None:
    message_type = str(message.get("type") or "")
    session_id = str(message.get("session_id") or "")
    transfer_id = str(message.get("transfer_id") or "")

    if transfer_id and (session_id, transfer_id) in UPLOAD_ACKS and message_type in {"file_upload_result", "file_error"}:
        await UPLOAD_ACKS[(session_id, transfer_id)].put(message)
        return

    if message_type == "file_list_result":
        queue = OPERATION_EXPECTATIONS.get(session_id)
        show_hidden = False
        if queue and queue[0].frontend_type == "file_list_result":
            show_hidden = queue.popleft().show_hidden
        path = str(message.get("path") or "")
        if path == ".":
            path = ""
        await _send_browser(session_id, client_id, {
            "type": "file_list_result",
            "ok": True,
            "path": path,
            "display_path": f"Remote Desktop / {path}" if path else "Remote Desktop",
            "parent_path": _parent_path(path),
            "shortcuts": [],
            "entries": _map_file_entries(message.get("entries"), show_hidden=show_hidden),
            "show_hidden": show_hidden,
            "truncated": bool(message.get("truncated")),
        })
        return

    if message_type == "file_download_offer":
        state = DOWNLOADS.get(transfer_id)
        if state is None:
            return
        state.relative_path = str(message.get("path") or "")
        state.filename = Path(state.relative_path).name or "download.bin"
        state.expected_size = int(message.get("size_bytes", 0) or 0)
        if state.expected_size < 0 or state.expected_size > MAX_TRANSFER_BYTES:
            DOWNLOADS.pop(transfer_id, None)
            state.path.unlink(missing_ok=True)
            await _send_browser(session_id, client_id, {"type": "file_download_result", "ok": False, "message": "Filen er for stor"})
            return
        await _send_browser(session_id, client_id, {
            "type": "file_download_result", "ok": True, "status": "uploading",
            "message": "Klient-agenten sender filen til backend...",
        })
        return

    if message_type == "file_download_chunk":
        state = DOWNLOADS.get(transfer_id)
        if state is None:
            return
        try:
            offset = int(message.get("offset", -1))
            if offset != state.received:
                raise ValueError("Downloadchunk har forkert offset")
            payload = base64.b64decode(str(message.get("data") or ""), validate=True)
            if (
                not payload
                or state.received + len(payload) > MAX_TRANSFER_BYTES
                or (state.expected_size is not None and state.received + len(payload) > state.expected_size)
            ):
                raise ValueError("Downloadchunk er ugyldig")
            with state.path.open("ab") as handle:
                handle.write(payload)
            state.digest.update(payload)
            state.received += len(payload)
        except (ValueError, binascii.Error, OSError) as exc:
            DOWNLOADS.pop(transfer_id, None)
            state.path.unlink(missing_ok=True)
            await _send_browser(session_id, client_id, {"type": "file_download_result", "ok": False, "message": str(exc)[:500]})
        return

    if message_type == "file_download_complete":
        await _finalize_download(client_id, message)
        return

    if message_type in {"file_operation_result", "file_error"}:
        if message_type == "file_error" and transfer_id:
            # A transfer error not consumed by an upload waiter belongs to a download.
            state = DOWNLOADS.pop(transfer_id, None)
            if state:
                state.path.unlink(missing_ok=True)
                await _send_browser(session_id, client_id, {
                    "type": "file_download_result", "ok": False,
                    "message": str(message.get("error") or "Filoverførsel fejlede"),
                })
                return
        queue = OPERATION_EXPECTATIONS.get(session_id)
        if message_type == "file_error" and queue and queue[0].frontend_type == "file_list_result":
            expected = queue.popleft()
            await _send_browser(session_id, client_id, {
                "type": "file_list_result",
                "ok": False,
                "message": str(message.get("error") or "Kunne ikke læse Remote Desktop-filområdet"),
                "entries": [],
                "show_hidden": expected.show_hidden,
            })
            return
        await _handle_operation_result(client_id, session_id, message)


@router.websocket("/remote-desktop-agent/clients/{client_id}/control/ws")
async def remote_desktop_agent_control_ws(websocket: WebSocket, client_id: int):
    await websocket.accept()
    credential = await _authenticate_agent_websocket(websocket, client_id)
    if credential is None:
        return
    channel = AgentChannel(client_id=client_id, credential_id=credential.id, token_version=int(credential.token_version), websocket=websocket)
    await _register_agent_channel(client_id, "control", channel)
    receive_task = None
    next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_AGENT_AUTH_RECHECK_SECONDS
    try:
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            timeout = max(0.0, next_auth_recheck - time.monotonic())
            done, _ = await asyncio.wait({receive_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if receive_task not in done:
                if not _remote_desktop_agent_channel_valid(channel):
                    await _close_with_reason(websocket, 4401, "Remote Desktop credential er ikke længere gyldigt")
                    return
                next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_AGENT_AUTH_RECHECK_SECONDS
                continue
            raw = receive_task.result()
            receive_task = asyncio.create_task(websocket.receive_text())
            if time.monotonic() >= next_auth_recheck:
                if not _remote_desktop_agent_channel_valid(channel):
                    await _close_with_reason(websocket, 4401, "Remote Desktop credential er ikke længere gyldigt")
                    return
                next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_AGENT_AUTH_RECHECK_SECONDS
            try:
                decoded = decode_json_message(raw, max_chars=MAX_AGENT_CONTROL_CHARS)
            except ProtocolError as exc:
                if exc.close_code:
                    await _close_with_reason(websocket, exc.close_code, exc.message)
                    return
                continue
            await _handle_control_agent_message(client_id, credential.id, decoded.payload)
    except WebSocketDisconnect:
        pass
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
        await _unregister_agent_channel(client_id, "control", websocket)


@router.websocket("/remote-desktop-agent/clients/{client_id}/files/ws")
async def remote_desktop_agent_files_ws(websocket: WebSocket, client_id: int):
    await websocket.accept()
    credential = await _authenticate_agent_websocket(websocket, client_id)
    if credential is None:
        return
    channel = AgentChannel(client_id=client_id, credential_id=credential.id, token_version=int(credential.token_version), websocket=websocket)
    await _register_agent_channel(client_id, "files", channel)
    receive_task = None
    next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_AGENT_AUTH_RECHECK_SECONDS
    try:
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            timeout = max(0.0, next_auth_recheck - time.monotonic())
            done, _ = await asyncio.wait({receive_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if receive_task not in done:
                if not _remote_desktop_agent_channel_valid(channel):
                    await _close_with_reason(websocket, 4401, "Remote Desktop credential er ikke længere gyldigt")
                    return
                next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_AGENT_AUTH_RECHECK_SECONDS
                continue
            raw = receive_task.result()
            receive_task = asyncio.create_task(websocket.receive_text())
            if time.monotonic() >= next_auth_recheck:
                if not _remote_desktop_agent_channel_valid(channel):
                    await _close_with_reason(websocket, 4401, "Remote Desktop credential er ikke længere gyldigt")
                    return
                next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_AGENT_AUTH_RECHECK_SECONDS
            try:
                decoded = decode_json_message(raw, max_chars=MAX_AGENT_FILE_CHARS)
            except ProtocolError as exc:
                if exc.close_code:
                    await _close_with_reason(websocket, exc.close_code, exc.message)
                    return
                continue
            await _handle_file_agent_message(client_id, decoded.payload)
    except WebSocketDisconnect:
        pass
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
        await _unregister_agent_channel(client_id, "files", websocket)


async def _browser_file_operation(client_id: int, session_id: str, message: dict[str, Any]) -> None:
    file_agent = FILE_AGENTS.get(client_id)
    if not file_agent:
        await _send_browser(session_id, client_id, {"type": "error", "message": "Remote Desktop-filkanalen er ikke forbundet"})
        return
    message_type = str(message.get("type") or "")
    if message_type == "file_list_request":
        show_hidden = bool(message.get("show_hidden"))
        OPERATION_EXPECTATIONS[session_id].append(OperationExpectation("file_list_result", show_hidden=show_hidden))
        await _send_agent(file_agent, {"type": "file_list_request", "session_id": session_id, "path": _safe_relative_path(message.get("path"))})
        return
    if message_type == "file_download_request":
        transfer_id = uuid.uuid4().hex
        TRANSFER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = TRANSFER_DIR / f"download-{transfer_id}.part"
        path.touch(mode=0o600, exist_ok=False)
        DOWNLOADS[transfer_id] = DownloadState(transfer_id=transfer_id, client_id=client_id, session_id=session_id, path=path)
        await _send_agent(file_agent, {
            "type": "file_download_request", "session_id": session_id,
            "transfer_id": transfer_id, "path": _safe_relative_path(message.get("path")),
        })
        return
    if message_type == "file_multi_download_request":
        await _send_browser(session_id, client_id, {
            "type": "file_download_result", "ok": False,
            "message": "Multi-download er ikke understøttet af Remote Desktop v2-agenten endnu.",
        })
        return
    if message_type == "file_delete_request":
        OPERATION_EXPECTATIONS[session_id].append(OperationExpectation("file_delete_result"))
        await _send_agent(file_agent, {"type": "file_delete_request", "session_id": session_id, "path": _safe_relative_path(message.get("path"))})
        return
    if message_type == "file_mkdir_request":
        path = _join_relative(message.get("path"), message.get("name"))
        OPERATION_EXPECTATIONS[session_id].append(OperationExpectation("file_mkdir_result"))
        await _send_agent(file_agent, {"type": "file_mkdir_request", "session_id": session_id, "path": path})
        return
    if message_type == "file_rename_request":
        source = _safe_relative_path(message.get("path"))
        destination = _join_relative(_parent_path(source), message.get("new_name"))
        OPERATION_EXPECTATIONS[session_id].append(OperationExpectation("file_rename_result"))
        await _send_agent(file_agent, {
            "type": "file_rename_request", "session_id": session_id,
            "path": source, "new_path": destination,
        })
        return
    if message_type == "file_move_request":
        paths = [_safe_relative_path(item) for item in (message.get("paths") or []) if str(item or "")]
        destination_dir = _safe_relative_path(message.get("destination_path"))
        if not paths:
            await _send_browser(session_id, client_id, {"type": "file_move_result", "ok": False, "message": "Ingen filer valgt"})
            return
        batch_id = uuid.uuid4().hex
        OPERATION_BATCHES[batch_id] = OperationBatch(frontend_type="file_move_result", total=len(paths))
        for source in paths:
            destination = _join_relative(destination_dir, PurePosixPath(source).name)
            OPERATION_EXPECTATIONS[session_id].append(OperationExpectation("file_move_result", batch_id=batch_id))
            await _send_agent(file_agent, {
                "type": "file_move_request", "session_id": session_id,
                "path": source, "destination": destination,
            })
        return


async def _browser_control_message(client_id: int, session_id: str, message: dict[str, Any]) -> None:
    control = CONTROL_AGENTS.get(client_id)
    if not control:
        await _send_browser(session_id, client_id, {"type": "error", "message": "Remote Desktop-controlkanalen er ikke forbundet"})
        return
    message_type = str(message.get("type") or "")
    if message_type in {"start_stream", "stop_stream", "request_frame"}:
        payload = dict(message)
        payload["session_id"] = session_id
        if not bool(payload.get("native", False)):
            width, height = _configured_resolution(client_id)
            payload.setdefault("screen_width", width)
            payload.setdefault("screen_height", height)
        await _send_agent(control, payload)
        return
    if message_type == "mouse":
        browser = await _browser_for_session(session_id, client_id)
        width = browser.screen_width if browser else None
        height = browser.screen_height if browser else None
        if not width or not height:
            width, height = _configured_resolution(client_id)
        for payload in _mouse_sequence(message, width, height):
            payload["session_id"] = session_id
            await _send_agent(control, payload)
        return
    if message_type == "key":
        sequence = _input_key_sequence(message.get("key"))
        if not sequence:
            await _send_browser(session_id, client_id, {"type": "error", "message": "Tasten kunne ikke oversættes sikkert"})
            return
        for payload in sequence:
            payload["session_id"] = session_id
            await _send_agent(control, payload)
        return
    if message_type == "text":
        await _send_agent(control, {"type": "text", "session_id": session_id, "text": str(message.get("text") or "")[:1000]})
        return
    if message_type == "shout":
        text = str(message.get("text") or "").strip()[:120]
        if not text:
            await _send_browser(session_id, client_id, {"type": "shout_result", "ok": False, "message": "Shout out-beskeden er tom"})
            return
        try:
            duration = max(3, min(30, int(message.get("duration") or 8)))
        except (TypeError, ValueError):
            duration = 8
        await _send_agent(control, {
            "type": "shout", "session_id": session_id, "text": text, "duration": duration,
        })
        return


@router.websocket("/remote-desktop/browser/{client_id}/ws")
async def remote_desktop_browser_ws(websocket: WebSocket, client_id: int):
    if not _ws_origin_allowed(websocket):
        await _close_with_reason(websocket, 4403, "Ugyldig WebSocket Origin")
        return
    with Session(engine) as session:
        user, selected_subprotocol, auth_session_binding = authenticate_browser_websocket_with_context(
            websocket, client_id=client_id, capability="remote_desktop", session=session
        )
    if not user:
        await _close_with_reason(websocket, 4401, "Ikke logget ind")
        return
    if not getattr(user, "is_superadmin", False):
        await _close_with_reason(websocket, 4403, "Kun superadmin må åbne fjernskrivebord")
        return
    if not _platform_client_accessible(client_id, user):
        await _close_with_reason(websocket, 4404, "Klient ikke fundet eller ingen adgang")
        return
    if user.id is None:
        await _close_with_reason(websocket, 4401, "Bruger mangler database-id")
        return
    if not auth_session_binding:
        await _close_with_reason(websocket, 4401, "Remote Desktop kræver en aktiv login-session")
        return

    await websocket.accept(subprotocol=selected_subprotocol)
    session_id = str(uuid.uuid4())
    try:
        with Session(engine) as db:
            rd_session = authorize_remote_desktop_session(
                db,
                session_id=session_id,
                client_id=client_id,
                user=user,
                source_ip=(websocket.client.host if websocket.client else None),
                user_agent=websocket.headers.get("user-agent"),
            )
            db.commit()
            db.refresh(rd_session)
    except HTTPException as exc:
        await _close_with_reason(websocket, 4404 if exc.status_code == 404 else 4400, str(exc.detail))
        return

    browser = BrowserSession(
        session_id=session_id,
        client_id=client_id,
        websocket=websocket,
        user_id=int(user.id),
        username=user.username,
        user_token_version=int(getattr(user, "token_version", 0) or 0),
        auth_session_binding=auth_session_binding,
        expires_at=rd_session.expires_at,
    )
    async with LOCK:
        BROWSERS[session_id] = browser
    await _open_session_on_available_channels(browser)
    width, height = _configured_resolution(client_id)
    await _send_json(websocket, {
        "type": "hello",
        "role": "browser",
        "session_id": session_id,
        "client_id": client_id,
        "agent_connected": _agent_ready(client_id),
        "width": width,
        "height": height,
    })
    if not _agent_ready(client_id):
        await _send_json(websocket, {"type": "status", "level": "warning", "message": "Venter på Remote Desktop-agentens control- og file-kanaler."})

    activity_lease_task = asyncio.create_task(
        maintain_activity_lease(
            engine,
            client_id=client_id,
            domain="remote_desktop",
            session_id=session_id,
        )
    )
    receive_task = None
    close_reason = "browser_disconnected"
    next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_BROWSER_AUTH_RECHECK_SECONDS
    try:
        receive_task = asyncio.create_task(websocket.receive_text())
        while True:
            timeout = max(0.0, next_auth_recheck - time.monotonic())
            done, _ = await asyncio.wait(
                {receive_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if receive_task not in done:
                current_user, state = _remote_desktop_browser_auth_state(browser)
                if current_user is None:
                    close_reason = state
                    await _close_with_reason(websocket, 4401 if state == "login_session_invalid" else 4403, "Remote Desktop-sessionen er ikke længere gyldig")
                    return
                user = current_user
                next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_BROWSER_AUTH_RECHECK_SECONDS
                continue

            raw = receive_task.result()
            receive_task = asyncio.create_task(websocket.receive_text())
            if time.monotonic() >= next_auth_recheck:
                current_user, state = _remote_desktop_browser_auth_state(browser)
                if current_user is None:
                    close_reason = state
                    await _close_with_reason(websocket, 4401 if state == "login_session_invalid" else 4403, "Remote Desktop-sessionen er ikke længere gyldig")
                    return
                user = current_user
                next_auth_recheck = time.monotonic() + REMOTE_DESKTOP_BROWSER_AUTH_RECHECK_SECONDS
            try:
                decoded = decode_json_message(
                    raw,
                    allowed_types=BROWSER_MESSAGE_TYPES | {"ping"},
                    max_chars=MAX_BROWSER_MESSAGE_CHARS,
                )
            except ProtocolError as exc:
                if exc.close_code:
                    await _close_with_reason(websocket, exc.close_code, exc.message)
                    return
                await _send_json(websocket, {"type": "error", "message": exc.message})
                continue
            if decoded.type == "ping":
                await _send_json(websocket, {"type": "pong", "ts": time.time()})
                continue
            message = dict(decoded.payload)
            message["session_id"] = session_id
            try:
                if decoded.type.startswith("file_"):
                    await _browser_file_operation(client_id, session_id, message)
                else:
                    await _browser_control_message(client_id, session_id, message)
            except HTTPException as exc:
                await _send_json(websocket, {"type": "error", "message": str(exc.detail)[:500]})
    except WebSocketDisconnect:
        pass
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
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
                    domain="remote_desktop",
                    session_id=session_id,
                    reason=close_reason,
                )
                activity_session.commit()
        except Exception:
            # Activity leases are auxiliary shared infrastructure; RD cleanup
            # must continue even if presence persistence is temporarily down.
            logger.warning(
                "remote_desktop_activity_lease_close_failed client_id=%s session_id=%s",
                client_id, session_id, exc_info=True,
            )
        async with LOCK:
            BROWSERS.pop(session_id, None)
        _pop_session_operation_state(session_id)
        for transfer_id, state in list(DOWNLOADS.items()):
            if state.session_id == session_id:
                DOWNLOADS.pop(transfer_id, None)
                state.path.unlink(missing_ok=True)
        for transfer_id, transfer in list(TRANSFERS.items()):
            if transfer.session_id == session_id:
                _release_transfer(transfer_id)
        await _close_session_on_available_channels(browser)
        with Session(engine) as db:
            close_remote_desktop_session(
                db,
                client_id=client_id,
                session_id=session_id,
                actor_user_id=browser.user_id,
                reason=close_reason,
            )
            db.commit()


async def _wait_upload_ack(session_id: str, transfer_id: str, *, timeout: float = 20.0) -> dict[str, Any]:
    queue = UPLOAD_ACKS[(session_id, transfer_id)]
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Remote Desktop-agenten kvitterede ikke for filoverførslen") from exc


async def _send_upload_file(
    file_agent: AgentChannel,
    *,
    browser: BrowserSession,
    source: Path,
    filename: str,
    destination_path: str,
    sha256: str,
    size_bytes: int,
) -> str:
    target = _join_relative(destination_path, filename)
    transfer_id = uuid.uuid4().hex
    key = (browser.session_id, transfer_id)
    UPLOAD_ACKS[key] = asyncio.Queue()
    try:
        # keep_both is the safe v2 default. Retry deterministic suffixed names
        # if the isolated file area already contains the target.
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        for attempt in range(0, 101):
            candidate = target if attempt == 0 else _join_relative(destination_path, f"{stem} ({attempt}){suffix}")
            await _send_agent(file_agent, {
                "type": "file_upload_offer",
                "session_id": browser.session_id,
                "transfer_id": transfer_id,
                "path": candidate,
                "size_bytes": size_bytes,
                "sha256": sha256,
            })
            ack = await _wait_upload_ack(browser.session_id, transfer_id)
            if ack.get("type") == "file_upload_result" and ack.get("accepted"):
                target = candidate
                break
            error = str(ack.get("error") or "Remote Desktop-agenten afviste uploaden")
            if "findes allerede" not in error or attempt >= 100:
                raise HTTPException(status_code=409, detail=error)
        offset = 0
        with source.open("rb") as handle:
            while chunk := handle.read(UPLOAD_CHUNK_BYTES):
                await _send_agent(file_agent, {
                    "type": "file_upload_chunk",
                    "session_id": browser.session_id,
                    "transfer_id": transfer_id,
                    "offset": offset,
                    "data": base64.b64encode(chunk).decode("ascii"),
                })
                ack = await _wait_upload_ack(browser.session_id, transfer_id)
                if ack.get("type") != "file_upload_result" or not ack.get("accepted"):
                    raise HTTPException(status_code=502, detail=str(ack.get("error") or "Uploadchunk blev afvist"))
                offset += len(chunk)
        await _send_agent(file_agent, {
            "type": "file_upload_complete",
            "session_id": browser.session_id,
            "transfer_id": transfer_id,
        })
        ack = await _wait_upload_ack(browser.session_id, transfer_id)
        if ack.get("type") != "file_upload_result" or not ack.get("accepted"):
            raise HTTPException(status_code=502, detail=str(ack.get("error") or "Upload kunne ikke afsluttes"))
        return target
    finally:
        UPLOAD_ACKS.pop(key, None)


async def _stage_upload(upload: UploadFile, client_id: int) -> tuple[Path, int, str, str]:
    TRANSFER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = _safe_filename(upload.filename or "upload.bin")
    path = TRANSFER_DIR / f"upload-{client_id}-{uuid.uuid4().hex}.part"
    size = 0
    digest = hashlib.sha256()
    try:
        with path.open("xb") as handle:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_TRANSFER_BYTES:
                    raise HTTPException(status_code=413, detail="Upload er for stor. Maksimum er 100 MB pr. fil")
                handle.write(chunk)
                digest.update(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return path, size, digest.hexdigest(), filename


@router.post("/remote-desktop/clients/{client_id}/files/upload-multiple")
async def remote_desktop_upload_multiple_files(
    client_id: int,
    request: Request,
    session_id: str = Form(...),
    destination_path: str = Form(""),
    conflict_strategies_json: str = Form(""),
    files: list[UploadFile] = File(...),
):
    user = _require_superadmin(_get_http_user(request))
    browser = await _browser_for_session(session_id, client_id)
    if browser is None or browser.user_id != int(user.id):
        raise HTTPException(status_code=400, detail="Remote Desktop-sessionen er ikke aktiv")
    file_agent = FILE_AGENTS.get(client_id)
    if not file_agent:
        raise HTTPException(status_code=409, detail="Remote Desktop-filkanalen er ikke forbundet")
    destination_path = _safe_relative_path(destination_path)
    _parse_upload_conflict_strategies(conflict_strategies_json, len(files))

    staged: list[tuple[Path, int, str, str]] = []
    total_batch = 0
    try:
        for upload in files:
            item = await _stage_upload(upload, client_id)
            staged.append(item)
            total_batch += item[1]
            if total_batch > MAX_TRANSFER_BYTES:
                raise HTTPException(status_code=413, detail="Samlet upload er for stor. Maksimum er 100 MB i alt")
    except Exception:
        for path, *_ in staged:
            path.unlink(missing_ok=True)
        raise

    completed = 0
    uploaded_paths: list[str] = []
    try:
        for path, size, sha256, filename in staged:
            target = await _send_upload_file(
                file_agent,
                browser=browser,
                source=path,
                filename=filename,
                destination_path=destination_path,
                sha256=sha256,
                size_bytes=size,
            )
            completed += 1
            uploaded_paths.append(target)
    finally:
        for path, *_ in staged:
            path.unlink(missing_ok=True)
    return {
        "ok": True,
        "count": completed,
        "total_size_bytes": total_batch,
        "destination_path": destination_path,
        "paths": uploaded_paths,
        "message": f"{completed} fil(er) uploadet og kvitteret af Remote Desktop-agenten.",
    }


@router.post("/remote-desktop/clients/{client_id}/files/upload")
async def remote_desktop_upload_file(
    client_id: int,
    request: Request,
    session_id: str = Form(...),
    destination_path: str = Form(""),
    conflict_strategy: str = Form("keep_both"),
    file: UploadFile = File(...),
):
    result = await remote_desktop_upload_multiple_files(
        client_id=client_id,
        request=request,
        session_id=session_id,
        destination_path=destination_path,
        conflict_strategies_json=json.dumps([conflict_strategy]),
        files=[file],
    )
    return result


@router.get("/remote-desktop/clients/{client_id}/files/browser-download/{transfer_id}")
def remote_desktop_browser_download(client_id: int, transfer_id: str, request: Request):
    user = _require_superadmin(_get_http_user(request))
    _cleanup_transfers()
    transfer = TRANSFERS.get(transfer_id)
    if transfer is None or transfer.client_id != client_id:
        raise HTTPException(status_code=404, detail="Download-transfer ikke fundet")
    if transfer.owner_user_id != int(user.id):
        raise HTTPException(status_code=403, detail="Download-transfer tilhører en anden session")
    if not transfer.path.exists():
        TRANSFERS.pop(transfer_id, None)
        raise HTTPException(status_code=404, detail="Download-filen findes ikke længere")
    response = FileResponse(
        str(transfer.path),
        media_type="application/octet-stream",
        filename=transfer.filename,
        background=BackgroundTask(_release_transfer, transfer_id),
    )
    response.headers["X-ClientFlow-File-SHA256"] = transfer.sha256
    response.headers["X-ClientFlow-File-Size"] = str(transfer.size_bytes)
    return response


@router.get("/remote-desktop/clients/{client_id}/status")
def remote_desktop_status(client_id: int, request: Request):
    user = _require_superadmin(_get_http_user(request))
    if not _platform_client_accessible(client_id, user):
        raise HTTPException(status_code=404, detail="Klient ikke fundet")
    width, height = _configured_resolution(client_id)
    with Session(engine) as session:
        status_row = session.exec(
            select(RemoteDesktopAgentStatus).where(RemoteDesktopAgentStatus.client_id == client_id)
        ).first()
    return {
        "client_id": client_id,
        "agent_connected": _agent_ready(client_id),
        "control_connected": client_id in CONTROL_AGENTS,
        "files_connected": client_id in FILE_AGENTS,
        "width": width,
        "height": height,
        "observed_state": status_row.observed_state if status_row else None,
        "agent_version": status_row.agent_version if status_row else None,
        "reported_at": status_row.reported_at if status_row else None,
        "status_payload": status_row.status_payload if status_row else {},
    }
