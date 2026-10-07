from __future__ import annotations

from datetime import timedelta
import unittest

from service1.models import Client, ClientCreate, ClientRead, ClientUpdate, utcnow
from service1.client_presence import ClientPresence, DomainPresence
from service1.routers.clients import _apply_status_runtime_snapshot, _apply_time_integrity_report


RAW_TIME_FIELDS = {
    "system_timezone",
    "ntp_enabled",
    "ntp_synchronized",
    "client_time_utc",
}
COMPUTED_TIME_FIELDS = {
    "clock_drift_seconds",
    "time_sync_status",
    "time_sync_message",
}


class ClientTimeIntegrityTests(unittest.TestCase):
    def test_raw_fields_are_reportable_but_computed_fields_are_read_only(self) -> None:
        self.assertTrue((RAW_TIME_FIELDS | COMPUTED_TIME_FIELDS).issubset(Client.model_fields))
        self.assertTrue((RAW_TIME_FIELDS | COMPUTED_TIME_FIELDS).issubset(ClientRead.model_fields))
        for writable_model in (ClientCreate, ClientUpdate):
            self.assertTrue(RAW_TIME_FIELDS.issubset(writable_model.model_fields))
            self.assertTrue(COMPUTED_TIME_FIELDS.isdisjoint(writable_model.model_fields))

    def test_healthy_report_is_computed_by_backend(self) -> None:
        client = Client(
            name="Test",
            system_timezone="Europe/Copenhagen",
            ntp_enabled=True,
            ntp_synchronized=True,
            client_time_utc=utcnow(),
            time_sync_status="critical",
            clock_drift_seconds=9999,
        )
        _apply_time_integrity_report(
            client,
            {"system_timezone", "ntp_enabled", "ntp_synchronized", "client_time_utc"},
        )
        self.assertEqual(client.time_sync_status, "ok")
        self.assertIsNotNone(client.clock_drift_seconds)
        self.assertLessEqual(float(client.clock_drift_seconds), 1.0)
        self.assertIn("korrekte", client.time_sync_message or "")

    def test_iso_utc_string_is_normalized_for_heartbeat_payloads(self) -> None:
        client = Client(
            name="ISO",
            system_timezone="Europe/Copenhagen",
            ntp_enabled=True,
            ntp_synchronized=True,
            client_time_utc="2026-07-14T22:00:00Z",  # raw heartbeat body bypasses Pydantic
        )
        _apply_time_integrity_report(
            client,
            {"system_timezone", "ntp_enabled", "ntp_synchronized", "client_time_utc"},
        )
        self.assertIsInstance(client.client_time_utc, type(utcnow()))
        self.assertIsNotNone(client.clock_drift_seconds)

    def test_runtime_snapshot_compares_client_clock_to_report_receipt_not_read_time(self) -> None:
        reported_at = utcnow() - timedelta(seconds=45)
        client_time = reported_at - timedelta(milliseconds=350)
        status = DomainPresence(
            domain="status",
            is_online=True,
            reason="fresh_online_status",
            reported_at=reported_at,
            status_payload={
                "system_timezone": "Europe/Copenhagen",
                "ntp_enabled": True,
                "ntp_synchronized": True,
                "client_time_utc": client_time,
            },
        )
        empty_display = DomainPresence(domain="display", is_online=False, reason="missing_status")
        empty_system = DomainPresence(domain="system", is_online=False, reason="missing_status")
        client = Client(name="Snapshot")

        _apply_status_runtime_snapshot(
            client,
            ClientPresence(status=status, display=empty_display, system=empty_system),
        )

        self.assertAlmostEqual(float(client.clock_drift_seconds or 0), 0.35, places=2)
        self.assertEqual(client.time_sync_status, "ok")
        self.assertNotIn("Ur-afvigelse", client.time_sync_message or "")

    def test_runtime_snapshot_ignores_newer_ephemeral_presence_for_clock_drift(self) -> None:
        durable_reported_at = utcnow() - timedelta(seconds=45)
        ephemeral_presence_at = durable_reported_at + timedelta(seconds=30)
        client_time = durable_reported_at - timedelta(milliseconds=275)
        status = DomainPresence(
            domain="status",
            is_online=True,
            reason="fresh_online_status",
            reported_at=ephemeral_presence_at,
            status_reported_at=durable_reported_at,
            status_payload={
                "system_timezone": "Europe/Copenhagen",
                "ntp_enabled": True,
                "ntp_synchronized": True,
                "client_time_utc": client_time,
            },
        )
        empty_display = DomainPresence(domain="display", is_online=False, reason="missing_status")
        empty_system = DomainPresence(domain="system", is_online=False, reason="missing_status")
        client = Client(name="Snapshot")

        _apply_status_runtime_snapshot(
            client,
            ClientPresence(status=status, display=empty_display, system=empty_system),
        )

        self.assertAlmostEqual(float(client.clock_drift_seconds or 0), 0.275, places=3)
        self.assertEqual(client.time_sync_status, "ok")
        self.assertNotIn("Ur-afvigelse", client.time_sync_message or "")

    def test_wrong_timezone_is_critical(self) -> None:
        client = Client(
            name="Test",
            system_timezone="UTC",
            ntp_enabled=True,
            ntp_synchronized=True,
            client_time_utc=utcnow(),
        )
        _apply_time_integrity_report(client, {"system_timezone", "ntp_enabled", "ntp_synchronized", "client_time_utc"})
        self.assertEqual(client.time_sync_status, "critical")
        self.assertIn("Europe/Copenhagen", client.time_sync_message or "")

    def test_clock_drift_thresholds(self) -> None:
        warning = Client(
            name="Warning", system_timezone="Europe/Copenhagen", ntp_enabled=True,
            ntp_synchronized=True, client_time_utc=utcnow() - timedelta(seconds=40),
        )
        _apply_time_integrity_report(warning, {"client_time_utc", "system_timezone", "ntp_enabled", "ntp_synchronized"})
        self.assertEqual(warning.time_sync_status, "warning")

        critical = Client(
            name="Critical", system_timezone="Europe/Copenhagen", ntp_enabled=True,
            ntp_synchronized=True, client_time_utc=utcnow() - timedelta(seconds=90),
        )
        _apply_time_integrity_report(critical, {"client_time_utc", "system_timezone", "ntp_enabled", "ntp_synchronized"})
        self.assertEqual(critical.time_sync_status, "critical")

    def test_missing_or_unsynchronised_ntp_is_not_healthy(self) -> None:
        client = Client(
            name="Test", system_timezone="Europe/Copenhagen", ntp_enabled=True,
            ntp_synchronized=False, client_time_utc=utcnow(),
        )
        _apply_time_integrity_report(client, {"client_time_utc", "system_timezone", "ntp_enabled", "ntp_synchronized"})
        self.assertEqual(client.time_sync_status, "critical")
        self.assertIn("ikke NTP-synkroniseret", client.time_sync_message or "")


if __name__ == "__main__":
    unittest.main()
