"""Process-local shared-domain liveness between durable status checkpoints."""
from __future__ import annotations

from datetime import datetime, timezone
import threading

_LOCK = threading.Lock()
_LAST_SEEN: dict[tuple[str, int], datetime] = {}
_ALLOWED = frozenset({"status", "display", "system"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def touch_presence(domain: str, client_id: int, *, at: datetime | None = None) -> datetime:
    normalized = str(domain or "").strip().lower()
    if normalized not in _ALLOWED:
        raise ValueError("Ukendt ephemeral presence-domæne")
    cid = int(client_id)
    if cid < 1:
        raise ValueError("client_id skal være positiv")
    observed = at or utcnow()
    with _LOCK:
        _LAST_SEEN[(normalized, cid)] = observed
    return observed


def last_seen(domain: str, client_id: int) -> datetime | None:
    with _LOCK:
        return _LAST_SEEN.get((str(domain or "").strip().lower(), int(client_id)))
