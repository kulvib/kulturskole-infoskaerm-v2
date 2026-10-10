"""Wake up the local Livestream sweeper on authenticated lifecycle changes.

The production topology is one worker. A generation counter plus Condition avoids
losing a wakeup if presence changes while the sweeper is querying Postgres.
This module does not hold database sessions, query Neon, or add background jobs.
"""
from __future__ import annotations

import threading

_CHANGE = threading.Condition()
_REVISION = 0


def notify_lifecycle_change() -> None:
    global _REVISION
    with _CHANGE:
        _REVISION += 1
        _CHANGE.notify_all()


def current_revision() -> int:
    with _CHANGE:
        return _REVISION


def wait_for_lifecycle_change(revision: int, timeout: float) -> tuple[int, bool]:
    """Wait at most ``timeout`` seconds; return revision and whether it changed."""
    with _CHANGE:
        changed = _CHANGE.wait_for(lambda: _REVISION != revision, timeout=timeout)
        return _REVISION, changed
