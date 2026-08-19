from __future__ import annotations

import unittest
from datetime import date, datetime

from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from service1.models import (
    AuditLog,
    CalendarMarking,
    Client,
    Organization,
    OrganizationSeasonTimes,
    OrganizationSeasonTimesReplace,
    OrganizationTimesUpdate,
    User,
)
from service1.routers.organizations import (
    apply_organization_season_times,
    replace_organization_season_calendars,
)
from service1.season_service import (
    SeasonValidationError,
    SYSTEM_DEFAULT_DAY_TIMES,
    apply_standard_times_to_existing_markings,
    build_season_calendar,
    current_and_next_seasons,
    current_season_payload,
    maintain_current_and_next_seasons,
    validate_and_normalize_markings,
    validate_season,
)


def _request(path: str) -> Request:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"user-agent", b"season-contract-ci")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }
    )
    request.state.request_id = "season-contract-ci"
    return request


class SeasonContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_season_boundary_uses_copenhagen_time(self) -> None:
        before = datetime.fromisoformat("2026-07-31T23:59:59+02:00")
        after = datetime.fromisoformat("2026-08-01T00:00:00+02:00")
        self.assertEqual(current_and_next_seasons(before), ("2025/2026", "2026/2027"))
        self.assertEqual(current_and_next_seasons(after), ("2026/2027", "2027/2028"))

        payload = current_season_payload(after)
        self.assertEqual(payload["season"], "2026/2027")
        self.assertEqual(payload["next_season"], "2027/2028")
        self.assertEqual(payload["timezone"], "Europe/Copenhagen")
        self.assertEqual(payload["next_switch_at"], "2027-08-01T00:00:00+02:00")

    def test_system_defaults_are_weekdays_nine_to_twenty_and_weekends_off(self) -> None:
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            self.assertEqual(
                SYSTEM_DEFAULT_DAY_TIMES[day],
                {"status": "on", "onTime": "09:00", "offTime": "20:00"},
            )
        self.assertEqual(SYSTEM_DEFAULT_DAY_TIMES["saturday"], {"status": "off"})
        self.assertEqual(SYSTEM_DEFAULT_DAY_TIMES["sunday"], {"status": "off"})

    def test_strict_season_and_date_validation(self) -> None:
        self.assertEqual(validate_season("2025/2026"), "2025/2026")
        for invalid in ("25/26", "2025-2026", "2025/2027", "abcd/efgh"):
            with self.assertRaises(SeasonValidationError):
                validate_season(invalid)

        calendar = build_season_calendar("2025/2026", SYSTEM_DEFAULT_DAY_TIMES)
        self.assertEqual(len(calendar), 365)
        self.assertEqual(calendar["2025-08-01"], {"status": "on", "onTime": "09:00", "offTime": "20:00"})
        self.assertEqual(calendar["2025-08-02"], {"status": "off"})
        self.assertEqual(calendar["2025-08-03"], {"status": "off"})

        with self.assertRaisesRegex(SeasonValidationError, "uden for sæsonen"):
            validate_and_normalize_markings(
                {"2027-08-01": {"status": "off"}},
                "2025/2026",
                require_complete=False,
            )

    def test_safe_standard_update_preserves_manual_deviations(self) -> None:
        old_times = {
            **SYSTEM_DEFAULT_DAY_TIMES,
            "monday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
        }
        new_times = {
            **SYSTEM_DEFAULT_DAY_TIMES,
            "monday": {"status": "on", "onTime": "08:00", "offTime": "19:00"},
        }
        markings = {
            "2025-08-04": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
            "2025-08-11": {"status": "on", "onTime": "12:00", "offTime": "18:00"},
            "2025-08-18": {"status": "off"},
        }
        updated, changed, preserved = apply_standard_times_to_existing_markings(
            markings,
            old_times=old_times,
            new_times=new_times,
            preserve_manual_times=True,
        )
        self.assertEqual(updated["2025-08-04"], {"status": "on", "onTime": "08:00", "offTime": "19:00"})
        self.assertEqual(updated["2025-08-11"], markings["2025-08-11"])
        self.assertEqual(updated["2025-08-18"], {"status": "off"})
        self.assertEqual(changed, 1)
        self.assertEqual(preserved, 2)

    def test_maintenance_creates_current_and_next_and_deletes_passed_season(self) -> None:
        with Session(self.engine) as session:
            organization = Organization(
                name="Testorganisation",
                day_times={
                    **SYSTEM_DEFAULT_DAY_TIMES,
                    "monday": {"status": "on", "onTime": "08:00", "offTime": "18:00"},
                },
            )
            session.add(organization)
            session.flush()
            client = Client(
                name="Skærm 1",
                status="approved",
                organization_id=organization.id,
            )
            session.add(client)
            session.flush()
            session.add(
                OrganizationSeasonTimes(
                    organization_id=organization.id,
                    season="2024/2025",
                    day_times=organization.day_times,
                )
            )
            session.add(
                CalendarMarking(
                    client_id=client.id,
                    season="2024/2025",
                    markings={"2024-08-01": {"status": "off"}},
                )
            )
            session.add(
                CalendarMarking(
                    client_id=client.id,
                    season="2025/2026",
                    markings={"2025-08-04": {"status": "on", "onTime": "12:00", "offTime": "18:00"}},
                )
            )
            session.commit()

            summary = maintain_current_and_next_seasons(session, date(2026, 7, 14))
            session.commit()

            self.assertEqual(summary["current_season"], "2025/2026")
            self.assertEqual(summary["next_season"], "2026/2027")
            self.assertEqual(summary["deleted_calendar_seasons"], ["2024/2025"])
            self.assertEqual(summary["deleted_organization_seasons"], ["2024/2025"])

            seasons = session.exec(
                select(OrganizationSeasonTimes.season).where(
                    OrganizationSeasonTimes.organization_id == organization.id
                )
            ).all()
            self.assertEqual(set(seasons), {"2025/2026", "2026/2027"})

            calendars = session.exec(
                select(CalendarMarking).where(CalendarMarking.client_id == client.id)
            ).all()
            self.assertEqual({row.season for row in calendars}, {"2025/2026", "2026/2027"})
            current_calendar = next(row for row in calendars if row.season == "2025/2026")
            next_calendar = next(row for row in calendars if row.season == "2026/2027")
            self.assertEqual(len(current_calendar.markings), 365)
            self.assertEqual(len(next_calendar.markings), 365)
            self.assertEqual(
                current_calendar.markings["2025-08-04"],
                {"status": "on", "onTime": "12:00", "offTime": "18:00"},
            )
            self.assertEqual(
                next_calendar.markings["2026-08-03"],
                {"status": "on", "onTime": "08:00", "offTime": "18:00"},
            )

    def test_safe_apply_saves_standard_and_preserves_manual_calendar_days(self) -> None:
        with Session(self.engine) as session:
            organization = Organization(name="Sikker anvendelse")
            admin = User(
                username="season-admin",
                email="season-admin@example.invalid",
                hashed_password="hashed",
                role="superadmin",
                is_active=True,
                must_change_password=False,
            )
            session.add(organization)
            session.add(admin)
            session.flush()
            old_times = dict(SYSTEM_DEFAULT_DAY_TIMES)
            session.add(
                OrganizationSeasonTimes(
                    organization_id=organization.id,
                    season="2025/2026",
                    day_times=old_times,
                )
            )
            client = Client(
                name="Sikker klient",
                status="approved",
                organization_id=organization.id,
            )
            session.add(client)
            session.flush()
            markings = build_season_calendar("2025/2026", old_times)
            markings["2025-08-04"] = {"status": "on", "onTime": "12:00", "offTime": "18:00"}
            markings["2025-08-05"] = {"status": "off"}
            session.add(
                CalendarMarking(
                    client_id=client.id,
                    season="2025/2026",
                    markings=markings,
                )
            )
            session.commit()

            new_times = {
                **SYSTEM_DEFAULT_DAY_TIMES,
                "monday": {"status": "on", "onTime": "08:00", "offTime": "19:00"},
                "tuesday": {"status": "on", "onTime": "08:30", "offTime": "19:30"},
            }
            result = apply_organization_season_times(
                _request(f"/api/organizations/{organization.id}/apply-season-times/2025/2026"),
                organization.id,
                "2025/2026",
                OrganizationTimesUpdate(day_times=new_times),
                session,
                admin,
            )

            stored_times = session.exec(
                select(OrganizationSeasonTimes).where(
                    OrganizationSeasonTimes.organization_id == organization.id,
                    OrganizationSeasonTimes.season == "2025/2026",
                )
            ).one()
            calendar = session.exec(
                select(CalendarMarking).where(
                    CalendarMarking.client_id == client.id,
                    CalendarMarking.season == "2025/2026",
                )
            ).one()
            audit = session.exec(
                select(AuditLog).where(
                    AuditLog.action == "organization_season_times_applied_safely"
                )
            ).one()

            self.assertEqual(stored_times.day_times["monday"], new_times["monday"])
            self.assertEqual(
                calendar.markings["2025-08-04"],
                {"status": "on", "onTime": "12:00", "offTime": "18:00"},
            )
            self.assertEqual(calendar.markings["2025-08-05"], {"status": "off"})
            self.assertEqual(
                calendar.markings["2025-08-11"],
                {"status": "on", "onTime": "08:00", "offTime": "19:00"},
            )
            self.assertEqual(result["updated_clients"], [client.id])
            self.assertGreaterEqual(result["preserved_manual_days"], 2)
            self.assertEqual(audit.details["season"], "2025/2026")

    def test_full_replace_requires_confirmation_and_overwrites_manual_days(self) -> None:
        with Session(self.engine) as session:
            organization = Organization(name="Fuld overskrivning")
            admin = User(
                username="replace-admin",
                email="replace-admin@example.invalid",
                hashed_password="hashed",
                role="superadmin",
                is_active=True,
                must_change_password=False,
            )
            session.add(organization)
            session.add(admin)
            session.flush()
            client = Client(
                name="Overskriv klient",
                status="approved",
                organization_id=organization.id,
            )
            session.add(client)
            session.flush()
            markings = build_season_calendar("2025/2026", SYSTEM_DEFAULT_DAY_TIMES)
            markings["2025-08-04"] = {"status": "off"}
            session.add(
                CalendarMarking(
                    client_id=client.id,
                    season="2025/2026",
                    markings=markings,
                )
            )
            session.commit()

            replacement_times = {
                **SYSTEM_DEFAULT_DAY_TIMES,
                "monday": {"status": "on", "onTime": "07:00", "offTime": "17:00"},
            }
            with self.assertRaises(HTTPException) as raised:
                replace_organization_season_calendars(
                    _request(f"/api/organizations/{organization.id}/replace-season-calendars/2025/2026"),
                    organization.id,
                    "2025/2026",
                    OrganizationSeasonTimesReplace(
                        day_times=replacement_times,
                        confirmation="forkert",
                    ),
                    session,
                    admin,
                )
            self.assertEqual(raised.exception.status_code, 400)

            result = replace_organization_season_calendars(
                _request(f"/api/organizations/{organization.id}/replace-season-calendars/2025/2026"),
                organization.id,
                "2025/2026",
                OrganizationSeasonTimesReplace(
                    day_times=replacement_times,
                    confirmation="OVERSKRIV",
                ),
                session,
                admin,
            )
            calendar = session.exec(
                select(CalendarMarking).where(
                    CalendarMarking.client_id == client.id,
                    CalendarMarking.season == "2025/2026",
                )
            ).one()
            audit = session.exec(
                select(AuditLog).where(
                    AuditLog.action == "organization_season_calendars_replaced"
                )
            ).one()

            self.assertEqual(
                calendar.markings["2025-08-04"],
                {"status": "on", "onTime": "07:00", "offTime": "17:00"},
            )
            self.assertEqual(result["replaced_calendars"], 1)
            self.assertTrue(audit.is_critical)
            self.assertEqual(audit.details["day_times"]["monday"], replacement_times["monday"])


if __name__ == "__main__":
    unittest.main()
