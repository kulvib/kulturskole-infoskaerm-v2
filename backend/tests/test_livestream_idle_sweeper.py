"""Regression contract for the idle, event-driven Livestream sweeper.

The physical 5-second active lifecycle and the 30-second stop grace remain
unchanged; only empty/stopping background scans may sleep longer than 5 min.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

from service1 import client_activity, livestream_presence, livestream_v2
from service1.livestream_sweep_signal import (
    current_revision,
    notify_lifecycle_change,
    wait_for_lifecycle_change,
)


class _StopLoop(Exception):
    pass


class _NoSqlSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        pass


class IdleLivestreamSweeperTests(unittest.TestCase):
    def test_revision_wakeup_is_not_lost_and_is_not_repeated(self) -> None:
        seen = current_revision()
        notify_lifecycle_change()
        updated, changed = wait_for_lifecycle_change(seen, timeout=0)
        self.assertTrue(changed)
        self.assertGreater(updated, seen)
        self.assertEqual(wait_for_lifecycle_change(updated, timeout=0), (updated, False))

    def test_viewer_open_and_close_wake_idle_sweeper_but_renewal_does_not(self) -> None:
        before = current_revision()
        livestream_presence.touch(91280, "viewer-idle-cost", "admin:127")
        opened = current_revision()
        self.assertGreater(opened, before)
        try:
            livestream_presence.touch(91280, "viewer-idle-cost", "admin:127")
            self.assertEqual(current_revision(), opened)
        finally:
            livestream_presence.leave(91280, "viewer-idle-cost", "admin:127")
        self.assertGreater(current_revision(), opened)

    def test_terminal_and_rd_session_boundaries_wake_idle_sweeper(self) -> None:
        for domain in ("terminal", "remote_desktop"):
            with self.subTest(domain=domain):
                previous = current_revision()
                client_activity._presence_add(91281, domain, "cost-signal")
                opened = current_revision()
                self.assertGreater(opened, previous)
                try:
                    client_activity._presence_add(91281, domain, "cost-signal")
                    self.assertEqual(current_revision(), opened)
                finally:
                    client_activity._presence_remove(91281, domain, "cost-signal")
                self.assertGreater(current_revision(), opened)

    def test_idle_scan_waits_longer_than_neon_scale_to_zero_then_resumes_fast(self) -> None:
        expected = [
            livestream_v2.VIEWER_SWEEP_SECONDS,
            livestream_v2.VIEWER_IDLE_SWEEP_SECONDS,
            livestream_v2.VIEWER_SWEEP_SECONDS,
            livestream_v2.VIEWER_IDLE_SWEEP_SECONDS,
        ]
        self.assertGreaterEqual(livestream_v2.VIEWER_IDLE_SWEEP_SECONDS, 600)
        observed_waits = []
        states = iter((False, True, False, False))

        def wait(_revision, interval):
            observed_waits.append(interval)
            if len(observed_waits) > len(expected):
                raise _StopLoop()
            return _revision, False

        def sweep(_session, *, sweep_activity):
            sweep_activity.needs_fast_scan = next(states)
            return []

        with (
            patch.object(livestream_v2, "Session", return_value=_NoSqlSession()),
            patch.object(livestream_v2, "wait_for_lifecycle_change", side_effect=wait),
            patch.object(livestream_v2, "reconcile_all_viewer_lifecycles", side_effect=sweep),
        ):
            with self.assertRaises(_StopLoop):
                livestream_v2._sweeper_loop()
        self.assertEqual(observed_waits[:4], expected)

    def test_database_failure_keeps_fast_retry_not_idle(self) -> None:
        intervals = []

        def wait(revision, seconds):
            intervals.append(seconds)
            if len(intervals) == 3:
                raise _StopLoop()
            return revision, False

        def broken_sweep(_session, *, sweep_activity):
            raise RuntimeError("temporary database failure")

        with (
            patch.object(livestream_v2, "Session", return_value=_NoSqlSession()),
            patch.object(livestream_v2, "wait_for_lifecycle_change", side_effect=wait),
            patch.object(livestream_v2, "reconcile_all_viewer_lifecycles", side_effect=broken_sweep),
        ):
            with self.assertRaises(_StopLoop):
                livestream_v2._sweeper_loop()
        self.assertEqual(intervals, [livestream_v2.VIEWER_SWEEP_SECONDS] * 3)

    def test_signal_during_database_sweep_is_seen_on_next_wait(self) -> None:
        # New lifecycle changes arriving during a database transaction must not
        # be consumed as part of the preceding wait and forgotten.
        current = current_revision()
        notify_lifecycle_change()
        updated, changed = wait_for_lifecycle_change(current, timeout=0)
        self.assertTrue(changed)
        notify_lifecycle_change()
        again, changed = wait_for_lifecycle_change(updated, timeout=0)
        self.assertTrue(changed)
        self.assertGreater(again, updated)


if __name__ == "__main__":
    unittest.main()
