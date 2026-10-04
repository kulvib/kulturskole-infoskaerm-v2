"""Single-worker realtime wake-up bus for ClientFlow durable command queues.

The bus deliberately carries *no command payload*.  Durable command authority
remains in Postgres; this process-local signal only tells an authenticated agent
that claiming the queue is worthwhile.  Render currently runs one instance and
one Uvicorn worker.  A future multi-worker deployment must replace this backend
behind the same API with shared ephemeral infrastructure (for example Valkey).
"""
from __future__ import annotations

from collections import defaultdict
import threading
import time
from typing import Final

_ALLOWED_DOMAINS: Final = frozenset({"display", "system", "livestream"})
_CONDITION = threading.Condition()
_GENERATIONS: dict[tuple[str, int], int] = defaultdict(int)


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
        _CONDITION.notify_all()
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
