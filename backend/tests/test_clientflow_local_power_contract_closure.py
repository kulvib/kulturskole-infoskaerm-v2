from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

from service1.system_control import apply_status_power_observation


class FakeSession:
    def __init__(self, client):
        self.client = client
        self.added = []

    def get(self, model, client_id):
        return self.client if int(client_id) == int(self.client.id) else None

    def add(self, value):
        self.added.append(value)


def _event(action: str, previous_boot: str, observed_boot: str, started_at: str):
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "event": "reboot_completed" if action == "reboot" else "boot_after_shutdown",
        "action": action,
        "source": "local",
        "started_at": started_at,
        "previous_boot_id": previous_boot,
        "observed_boot_id": observed_boot,
    }


def test_local_status_power_event_persists_without_creating_system_command():
    previous = str(uuid.uuid4())
    current = str(uuid.uuid4())
    client = SimpleNamespace(
        id=42,
        last_boot_id=previous,
        last_boot_at=None,
        last_power_event=None,
        last_power_event_at=None,
        last_power_event_source=None,
        last_reboot_started_at=None,
        last_shutdown_started_at=None,
    )
    session = FakeSession(client)
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    apply_status_power_observation(
        session,
        client_id=42,
        status_payload={"local_power_event": _event("reboot", previous, current, started)},
        boot_id=current,
    )

    assert client.last_boot_id == current
    assert client.last_boot_at is not None
    assert client.last_power_event == "reboot_completed"
    assert client.last_power_event_source == "local"
    assert client.last_reboot_started_at is not None
    assert client.last_shutdown_started_at is None
    assert session.added == [client]


def test_status_power_event_rejects_boot_binding_mismatch():
    previous = str(uuid.uuid4())
    current = str(uuid.uuid4())
    wrong = str(uuid.uuid4())
    client = SimpleNamespace(
        id=7,
        last_boot_id=previous,
        last_boot_at=None,
        last_power_event=None,
        last_power_event_at=None,
        last_power_event_source=None,
        last_reboot_started_at=None,
        last_shutdown_started_at=None,
    )
    session = FakeSession(client)
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    apply_status_power_observation(
        session,
        client_id=7,
        status_payload={"local_power_event": _event("shutdown", previous, wrong, started)},
        boot_id=current,
    )

    assert client.last_boot_id == current
    assert client.last_power_event is None
    assert client.last_shutdown_started_at is None
