"""Single-worker realtime wake-up bus for ClientFlow durable command queues.

The bus deliberately carries *no command payload*.  Durable command authority
remains in Postgres; this process-local signal only tells an authenticated agent
that claiming the queue is worthwhile.  Render currently runs one instance and
one Uvicorn worker.  A future multi-worker deployment must replace this backend
behind the same API with shared ephemeral infrastructure (for example Valkey).
"""
from __future__ import annotations

from collections import defaultdict
import asyncio
import threading
import time
from typing import Final

_ALLOWED_DOMAINS: Final = frozenset({"display", "system", "livestream"})
_CONDITION = threading.Condition()
_GENERATIONS: dict[tuple[str, int], int] = defaultdict(int)
# Each async wake waiter belongs to its event loop. Registration and publication
# are guarded by the existing condition lock, so a wake cannot be lost between
# reading the generation and subscribing. No thread is parked per WebSocket or
# HTTP long-poll request.
_ASYNC_WAITERS: dict[
    tuple[str, int], set[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]]
] = defaultdict(set)


def _resolve_waiter(waiter: asyncio.Future[None]) -> None:
    # The receiver may have timed out or disconnected since publication.
    if not waiter.done():
        waiter.set_result(None)


def _key(domain: str, client_id: int) -> tuple[str, int]:
    normalized = str(domain or "").strip().lower()
    if normalized not in _ALLOWED_DOMAINS:
        raise ValueError("Ukendt command wake-up domæne")
    cid = int(client_id)
    if cid < 1:
        raise ValueError("client_id skal være positiv")
    return normalized, cid


def current_generation(domain: str, client_id: int) -> int:
    key = _key(domain, client_id)
    with _CONDITION:
        return int(_GENERATIONS[key])


def notify_command_available(domain: str, client_id: int) -> int:
    key = _key(domain, client_id)
    with _CONDITION:
        _GENERATIONS[key] += 1
        generation = int(_GENERATIONS[key])
        # Only this client's async subscriptions are scheduled; unrelated
        # clients never wake. Keep the condition for existing sync consumers.
        listeners = tuple(_ASYNC_WAITERS.pop(key, ()))
        _CONDITION.notify_all()
    for loop, waiter in listeners:
        try:
            loop.call_soon_threadsafe(_resolve_waiter, waiter)
        except RuntimeError:
            # The subscribed event loop was already closed. Durable queue
            # reconciliation still supplies the recovery path.
            pass
    return generation


def wait_for_change(domain: str, client_id: int, after: int, timeout: float) -> int:
    """Block without database work until generation advances or timeout expires."""
    key = _key(domain, client_id)
    deadline = time.monotonic() + min(max(float(timeout), 0.0), 55.0)
    with _CONDITION:
        while int(_GENERATIONS[key]) <= int(after):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _CONDITION.wait(timeout=remaining)
        return int(_GENERATIONS[key])


async def wait_for_change_async(domain: str, client_id: int, after: int, timeout: float) -> int:
    """Await one client's generation without occupying a worker thread.

    The waiter and generation snapshot are registered atomically; an event
    arriving just before or during subscription is never missed. Both timeout
    and cancellation release the subscription (including disconnects).
    """
    key = _key(domain, client_id)
    bounded_timeout = min(max(float(timeout), 0.0), 55.0)
    if bounded_timeout <= 0:
        return current_generation(domain, client_id)
    loop = asyncio.get_running_loop()
    waiter: asyncio.Future[None] = loop.create_future()
    subscription = (loop, waiter)
    with _CONDITION:
        if int(_GENERATIONS[key]) > int(after):
            return int(_GENERATIONS[key])
        _ASYNC_WAITERS[key].add(subscription)
    try:
        try:
            await asyncio.wait_for(waiter, timeout=bounded_timeout)
        except asyncio.TimeoutError:
            pass
    finally:
        with _CONDITION:
            subscribers = _ASYNC_WAITERS.get(key)
            if subscribers is not None:
                subscribers.discard(subscription)
                if not subscribers:
                    _ASYNC_WAITERS.pop(key, None)
    return current_generation(domain, client_id)


def queue_wakeup_after_commit(session, *, domain: str, client_id: int) -> None:
    """Record a wake target and publish only after the surrounding DB commit."""
    pending = session.info.setdefault("clientflow_command_wakeups", set())
    pending.add(_key(domain, client_id))


def publish_session_wakeups(session) -> None:
    pending = set(session.info.pop("clientflow_command_wakeups", set()))
    for domain, client_id in pending:
        notify_command_available(domain, client_id)


def discard_session_wakeups(session) -> None:
    session.info.pop("clientflow_command_wakeups", None)
