from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

from service1.routers import calendar
from service1.season_service import (
    build_season_calendar,
    current_and_next_seasons,
    season_dates,
)


class _Result:
    def __init__(self, *, first=None, all_items=None):
        self._first = first
        self._all = list(all_items or [])

    def first(self):
        return self._first

    def all(self):
        return list(self._all)


class _Session:
    def __init__(self, *, organization, season_times, clients, calendars):
        self.organization = organization
        self.results = iter(
            [
                _Result(first=season_times),
                _Result(all_items=clients),
                _Result(all_items=calendars),
            ]
        )

    def get(self, model, object_id):
        del model, object_id
        return self.organization

    def exec(self, statement):
        del statement
        return next(self.results)


class SeasonReadinessRouteTests(unittest.TestCase):
    def test_route_is_registered(self) -> None:
        routes = {
            (getattr(route, "path", ""), frozenset(getattr(route, "methods", set()) or set()))
            for route in calendar.router.routes
        }
        self.assertIn(("/calendar/seasons/readiness", frozenset({"GET"})), routes)

    def test_complete_calendars_are_ready(self) -> None:
        season, _ = current_and_next_seasons()
        markings = build_season_calendar(
            season,
            {
                "monday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
                "tuesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
                "wednesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
                "thursday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
                "friday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
                "saturday": {"status": "off"},
                "sunday": {"status": "off"},
            },
        )
        session = _Session(
            organization=SimpleNamespace(id=7),
            season_times=SimpleNamespace(id=9),
            clients=[SimpleNamespace(id=101)],
            calendars=[SimpleNamespace(client_id=101, markings=markings)],
        )

        response = calendar.get_season_readiness(
            organization_id=7,
            season=season,
            session=session,
            admin=SimpleNamespace(is_superadmin=True, organization_id=None),
        )

        self.assertTrue(response.is_ready)
        self.assertEqual(response.complete_calendars, 1)
        self.assertEqual(response.missing_calendars, 0)
        self.assertEqual(response.missing_days, 0)

    def test_missing_calendar_is_reported_without_mutation(self) -> None:
        season, _ = current_and_next_seasons()
        session = _Session(
            organization=SimpleNamespace(id=7),
            season_times=SimpleNamespace(id=9),
            clients=[SimpleNamespace(id=101), SimpleNamespace(id=102)],
            calendars=[SimpleNamespace(client_id=101, markings={})],
        )

        response = calendar.get_season_readiness(
            organization_id=7,
            season=season,
            session=session,
            admin=SimpleNamespace(is_superadmin=True, organization_id=None),
        )

        self.assertFalse(response.is_ready)
        self.assertEqual(response.missing_calendars, 1)
        self.assertEqual(response.incomplete_calendars, 1)
        self.assertEqual(response.missing_days, len(season_dates(season)) * 2)

    def test_admin_cannot_read_other_organization(self) -> None:
        season, _ = current_and_next_seasons()
        with self.assertRaises(HTTPException) as raised:
            calendar.get_season_readiness(
                organization_id=7,
                season=season,
                session=SimpleNamespace(),
                admin=SimpleNamespace(is_superadmin=False, organization_id=8),
            )
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
