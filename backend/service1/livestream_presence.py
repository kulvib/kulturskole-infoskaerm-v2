"""Process-local Livestream viewer presence for steady-state heartbeats.

Viewer rows remain durable audit/lifecycle boundaries, but repeated last_seen
heartbeats stay in memory on the current single-worker topology.  A future
multi-worker deployment must replace this store with shared ephemeral state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading

_LOCK = threading.Lock()
_VIEWERS: dict[tuple[int, str, str], datetime] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def touch(client_id: int, viewer_id: str, principal_key: str, *, at: datetime | None = None) -> datetime:
    observed = at or utcnow()
    key = (int(client_id), str(viewer_id), str(principal_key))
    with _LOCK:
        _VIEWERS[key] = observed
    return observed


def leave(client_id: int, viewer_id: str, principal_key: str) -> None:
    with _LOCK:
        _VIEWERS.pop((int(client_id), str(viewer_id), str(principal_key)), None)


def active_keys(client_id: int, *, lease_seconds: int, now: datetime | None = None) -> set[tuple[str, str]]:
    current = now or utcnow()
    cutoff = current - timedelta(seconds=max(1, int(lease_seconds)))
    result: set[tuple[str, str]] = set()
    stale: list[tuple[int, str, str]] = []
    with _LOCK:
        for key, seen in _VIEWERS.items():
            cid, viewer_id, principal_key = key
            if seen < cutoff:
                stale.append(key)
                continue
            if cid == int(client_id):
                result.add((viewer_id, principal_key))
        for key in stale:
            _VIEWERS.pop(key, None)
    return result


def active_client_ids(*, lease_seconds: int, now: datetime | None = None) -> set[int]:
    current = now or utcnow()
    cutoff = current - timedelta(seconds=max(1, int(lease_seconds)))
    active: set[int] = set()
    stale: list[tuple[int, str, str]] = []
    with _LOCK:
        for key, seen in _VIEWERS.items():
            if seen < cutoff:
                stale.append(key)
            else:
                active.add(int(key[0]))
        for key in stale:
            _VIEWERS.pop(key, None)
    return active
