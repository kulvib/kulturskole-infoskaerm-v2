"""Bounded in-process HTTPS relay adapter for WebSocket-only handlers.

This module intentionally contains no application authority and no database
state.  It presents a tiny WebSocket-compatible surface to existing handlers so
Terminal and Remote Desktop can fall back to ordinary HTTPS long-polling on
networks that block WebSocket upgrades.  Authentication, authorization,
revocation checks, audit and protocol validation remain owned by the existing
handlers.

The relay is deliberately process-local because production is currently one
Render instance / one Uvicorn worker.  Horizontal scaling requires replacing
this adapter with shared ephemeral infrastructure before adding workers.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from fastapi import HTTPException, WebSocketDisconnect

MAX_RELAYS = 512
QUEUE_DEPTH = 64
MAX_QUEUE_BYTES = 48 * 1024 * 1024
RELAY_TTL_SECONDS = 15 * 60
MAX_POLL_SECONDS = 30


@dataclass
class HttpWebSocketRelay:
    relay_id: str
    headers: dict[str, str]
    query_params: dict[str, str]
    cookies: dict[str, str]
    client_host: str | None
    scope: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    last_activity_at: float = field(default_factory=time.monotonic)
    accepted: bool = False
    closed: bool = False
    close_code: int | None = None
    close_reason: str = ""
    incoming: asyncio.Queue[tuple[str, int]] = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_DEPTH))
    outgoing: asyncio.Queue[tuple[str, int]] = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_DEPTH))
    incoming_bytes: int = 0
    outgoing_bytes: int = 0
    task: asyncio.Task[Any] | None = None

    @property
    def client(self):
        return SimpleNamespace(host=self.client_host) if self.client_host else None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted = True
        self.last_activity_at = time.monotonic()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        self.close_code = int(code)
        self.close_reason = str(reason or "")[:120]
        self.last_activity_at = time.monotonic()
        try:
            self._put_outgoing(
                _json_dumps({"type": "relay_closed", "code": self.close_code, "reason": self.close_reason})
            )
        except RuntimeError:
            # closed=true is also returned by the HTTP poll response. A saturated
            # live-media queue must not prevent deterministic relay shutdown.
            pass

    async def send_text(self, payload: str) -> None:
        if self.closed:
            raise RuntimeError("HTTPS relay er lukket")
        self.last_activity_at = time.monotonic()
        self._put_outgoing(str(payload))

    async def receive_text(self) -> str:
        while True:
            if self.closed and self.incoming.empty():
                raise WebSocketDisconnect(code=self.close_code or 1000, reason=self.close_reason)
            try:
                payload, size = await asyncio.wait_for(self.incoming.get(), timeout=5.0)
                self.incoming_bytes = max(0, self.incoming_bytes - size)
                self.last_activity_at = time.monotonic()
                return payload
            except asyncio.TimeoutError:
                if self.closed:
                    raise WebSocketDisconnect(code=self.close_code or 1000, reason=self.close_reason)

    async def push_from_http(self, payload: str) -> None:
        if self.closed:
            raise HTTPException(status_code=410, detail="HTTPS relay er lukket")
        self.last_activity_at = time.monotonic()
        self._put_incoming(str(payload))

    @staticmethod
    def _payload_size(payload: str) -> int:
        return len(payload.encode("utf-8", errors="replace"))

    def _put_incoming(self, payload: str) -> None:
        size = self._payload_size(payload)
        if self.incoming_bytes + size > MAX_QUEUE_BYTES:
            raise RuntimeError("HTTPS relay incoming byte-backpressure er nået")
        try:
            self.incoming.put_nowait((payload, size))
        except asyncio.QueueFull as exc:
            raise RuntimeError("HTTPS relay incoming queue-depth er nået") from exc
        self.incoming_bytes += size

    def _put_outgoing(self, payload: str) -> None:
        size = self._payload_size(payload)
        if self.outgoing_bytes + size > MAX_QUEUE_BYTES:
            raise RuntimeError("HTTPS relay outgoing byte-backpressure er nået")
        try:
            self.outgoing.put_nowait((payload, size))
        except asyncio.QueueFull as exc:
            raise RuntimeError("HTTPS relay outgoing queue-depth er nået") from exc
        self.outgoing_bytes += size

    async def poll_to_http(self, timeout_seconds: int = 25) -> list[str]:
        timeout = min(MAX_POLL_SECONDS, max(1, int(timeout_seconds)))
        self.last_activity_at = time.monotonic()
        items: list[str] = []
        try:
            first, size = await asyncio.wait_for(self.outgoing.get(), timeout=float(timeout))
            self.outgoing_bytes = max(0, self.outgoing_bytes - size)
            items.append(first)
        except asyncio.TimeoutError:
            return items
        while len(items) < 64:
            try:
                payload, size = self.outgoing.get_nowait()
                self.outgoing_bytes = max(0, self.outgoing_bytes - size)
                items.append(payload)
            except asyncio.QueueEmpty:
                break
        return items


_RELAYS: dict[str, HttpWebSocketRelay] = {}
_LOCK = asyncio.Lock()


def _json_dumps(value: dict[str, Any]) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _prune_locked() -> None:
    now = time.monotonic()
    stale = [
        relay_id
        for relay_id, relay in _RELAYS.items()
        if relay.closed or now - relay.last_activity_at > RELAY_TTL_SECONDS
    ]
    for relay_id in stale:
        relay = _RELAYS.pop(relay_id, None)
        if relay and relay.task and not relay.task.done():
            relay.task.cancel()


async def create_relay(
    handler: Callable[[HttpWebSocketRelay], Awaitable[Any]],
    *,
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    client_host: str | None = None,
    scope: dict[str, Any] | None = None,
) -> HttpWebSocketRelay:
    relay = HttpWebSocketRelay(
        relay_id=uuid.uuid4().hex,
        headers={str(k).lower(): str(v) for k, v in (headers or {}).items()},
        query_params=dict(query_params or {}),
        cookies=dict(cookies or {}),
        client_host=client_host,
        scope=dict(scope or {}),
    )
    async with _LOCK:
        await _prune_locked()
        if len(_RELAYS) >= MAX_RELAYS:
            raise HTTPException(status_code=503, detail="HTTPS relay-kapaciteten er midlertidigt opbrugt")
        _RELAYS[relay.relay_id] = relay

    async def runner() -> None:
        try:
            await handler(relay)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not relay.closed:
                await relay.close(1011, "Relay-handler fejlede")
        finally:
            if not relay.closed:
                await relay.close(1000, "Relay-handler afsluttet")

    relay.task = asyncio.create_task(runner(), name=f"https-relay-{relay.relay_id[:10]}")
    return relay


async def get_relay(relay_id: str) -> HttpWebSocketRelay:
    async with _LOCK:
        await _prune_locked()
        relay = _RELAYS.get(str(relay_id))
    if relay is None:
        raise HTTPException(status_code=404, detail="HTTPS relay findes ikke eller er udløbet")
    return relay


async def close_relay(relay_id: str, *, reason: str = "http_client_closed") -> None:
    async with _LOCK:
        relay = _RELAYS.pop(str(relay_id), None)
    if relay is None:
        return
    await relay.close(1000, reason)
    if relay.task and not relay.task.done():
        relay.task.cancel()


def require_relay_scope(relay: HttpWebSocketRelay, **expected: Any) -> None:
    for key, value in expected.items():
        if relay.scope.get(key) != value:
            raise HTTPException(status_code=404, detail="HTTPS relay findes ikke")
