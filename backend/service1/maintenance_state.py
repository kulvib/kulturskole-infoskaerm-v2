from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from time import monotonic
from typing import Any

from sqlmodel import Session


def _cache_ttl_seconds() -> int:
    raw = os.getenv("MAINTENANCE_CACHE_TTL_SECONDS", "15").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("MAINTENANCE_CACHE_TTL_SECONDS skal være et heltal") from exc
    if value < 5 or value > 60:
        raise RuntimeError("MAINTENANCE_CACHE_TTL_SECONDS skal være mellem 5 og 60")
    return value


MAINTENANCE_CACHE_TTL_SECONDS = _cache_ttl_seconds()
DEFAULT_MAINTENANCE_MESSAGE = "PlanIQ Display er midlertidigt utilgængelig på grund af vedligeholdelse."


@dataclass(frozen=True)
class MaintenanceSnapshot:
    enabled: bool
    message: str | None = None
    expected_end_at: datetime | None = None
    enabled_at: datetime | None = None


@dataclass(frozen=True)
class _CachedMaintenance:
    snapshot: MaintenanceSnapshot
    loaded_at: float


_cache: _CachedMaintenance | None = None
_cache_lock = RLock()


def snapshot_from_row(row: Any | None) -> MaintenanceSnapshot:
    if row is None:
        return MaintenanceSnapshot(enabled=False)
    return MaintenanceSnapshot(
        enabled=bool(row.enabled),
        message=row.message,
        expected_end_at=row.expected_end_at,
        enabled_at=row.enabled_at,
    )


def update_maintenance_cache(row: Any | None) -> MaintenanceSnapshot:
    global _cache
    snapshot = snapshot_from_row(row)
    with _cache_lock:
        _cache = _CachedMaintenance(snapshot=snapshot, loaded_at=monotonic())
    return snapshot


def invalidate_maintenance_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def _fresh_cached_snapshot() -> MaintenanceSnapshot | None:
    with _cache_lock:
        cached = _cache
        if cached is None:
            return None
        if monotonic() - cached.loaded_at >= MAINTENANCE_CACHE_TTL_SECONDS:
            return None
        return cached.snapshot


def get_maintenance_snapshot(session: Session, *, force_refresh: bool = False) -> MaintenanceSnapshot:
    """Read the singleton with a short process-local TTL.

    Human user requests use this cache, avoiding a Neon query per request. Client
    principals do not consult maintenance state at all. A stale/missing cache must
    reach the database; database errors propagate so callers can fail closed.
    """
    if not force_refresh:
        cached = _fresh_cached_snapshot()
        if cached is not None:
            return cached

    with _cache_lock:
        if not force_refresh:
            cached = _fresh_cached_snapshot()
            if cached is not None:
                return cached
        from .models import MaintenanceState

        row = session.get(MaintenanceState, 1)
        return update_maintenance_cache(row)
