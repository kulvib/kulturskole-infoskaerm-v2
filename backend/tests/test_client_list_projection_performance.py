from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import (
    ClientCommand,
    ClientDomainCredential,
    ClientDomainStatus,
    DisplayDesiredConfiguration,
)
from service1.models import Client, utcnow
from service1.routers import clients as clients_router


PROJECTION_FIELDS = (
    "kiosk_url",
    "browser_refresh_interval_sec",
    "chrome_status",
    "chrome_color",
    "chrome_last_updated",
    "chrome_running",
    "browser_requested",
    "chrome_step",
    "display_power",
    "service_calendar_status",
    "pending_chrome_action",
    "pending_chrome_action_source",
    "pending_reboot",
    "pending_shutdown",
    "state",
    "last_power_event",
    "last_power_event_at",
    "last_power_event_source",
    "last_reboot_started_at",
    "last_shutdown_started_at",
    "pending_os_update",
    "ubuntu_update_status",
    "ubuntu_update_step",
    "ubuntu_update_message",
    "ubuntu_update_error",
    "ubuntu_update_started_at",
    "ubuntu_update_updated_at",
    "ubuntu_update_finished_at",
    "ubuntu_update_progress",
    "ubuntu_update_package_count",
    "ubuntu_update_reboot_required",
    "local_management_action",
    "local_management_request_id",
    "local_management_desired_hostname",
    "local_management_status",
    "local_management_message",
    "local_management_requested_at",
    "local_management_started_at",
    "local_management_finished_at",
    "local_management_error",
)


def _command(
    *,
    client_id: int,
    domain: str,
    command_type: str,
    requested_at,
    status: str,
    payload: dict | None = None,
    result: dict | None = None,
    command_id: str | None = None,
) -> ClientCommand:
    completed_at = requested_at + timedelta(seconds=5) if status in {"succeeded", "failed", "expired", "cancelled"} else None
    claimed_at = requested_at + timedelta(seconds=1) if status in {"claimed", "succeeded", "failed"} else None
    return ClientCommand(
        id=command_id or str(uuid.uuid4()),
        client_id=client_id,
        domain=domain,
        command_type=command_type,
        payload=dict(payload or {}),
        idempotency_key=f"test:{uuid.uuid4()}",
        requested_at=requested_at,
        available_at=requested_at,
        expires_at=requested_at + timedelta(hours=1),
        status=status,
        claimed_at=claimed_at,
        completed_at=completed_at,
        result=result,
    )


def _seed(engine, count: int) -> None:
    now = utcnow()
    with Session(engine) as session:
        for index in range(count):
            client = Client(name=f"perf-{index:03d}", status="approved", sort_order=index)
            session.add(client)
            session.flush()
            client_id = int(client.id)

            for domain in ("status", "display", "system"):
                credential_id = str(uuid.uuid4())
                session.add(
                    ClientDomainCredential(
                        id=credential_id,
                        client_id=client_id,
                        domain=domain,
                        secret_hash="hash",
                        created_at=now,
                    )
                )
                payload: dict = {}
                boot_id = None
                if domain == "status":
                    boot_id = f"boot-{index}"
                    payload = {
                        "system_timezone": "Europe/Copenhagen",
                        "ntp_enabled": True,
                        "ntp_synchronized": True,
                    }
                elif domain == "display":
                    payload = {
                        "runtime": {
                            "state": "running",
                            "browser_requested": True,
                            "updated_at": now.timestamp(),
                        },
                        "display_power": {"state": "on", "updated_at": now.timestamp()},
                        "calendar": {"state": "running", "updated_at": now.timestamp()},
                    }
                session.add(
                    ClientDomainStatus(
                        id=str(uuid.uuid4()),
                        client_id=client_id,
                        domain=domain,
                        schema_version=1,
                        observed_state="online",
                        status_payload=payload,
                        agent_version="1.3.21",
                        boot_id=boot_id,
                        credential_id=credential_id,
                        reported_at=now,
                    )
                )

            session.add(
                DisplayDesiredConfiguration(
                    client_id=client_id,
                    revision=3,
                    kiosk_url=f"https://example.invalid/{index}",
                    browser_refresh_interval_sec=900,
                    updated_at=now,
                )
            )
            session.add(
                _command(
                    client_id=client_id,
                    domain="display",
                    command_type="start_browser",
                    requested_at=now - timedelta(seconds=10),
                    status="queued",
                )
            )

            # Older rows prove that the batch loader selects the same latest
            # command as the original per-client ORDER BY ... DESC path.
            session.add(
                _command(
                    client_id=client_id,
                    domain="system",
                    command_type="shutdown",
                    requested_at=now - timedelta(minutes=10),
                    status="succeeded",
                    payload={"requested_boot_id": f"boot-old-{index}", "source": "system_command"},
                )
            )
            session.add(
                _command(
                    client_id=client_id,
                    domain="system",
                    command_type="reboot",
                    requested_at=now - timedelta(minutes=3),
                    status="claimed",
                    payload={"requested_boot_id": f"boot-{index}", "source": "system_command"},
                )
            )
            session.add(
                _command(
                    client_id=client_id,
                    domain="system",
                    command_type="update_os",
                    requested_at=now - timedelta(minutes=8),
                    status="failed",
                )
            )
            session.add(
                _command(
                    client_id=client_id,
                    domain="system",
                    command_type="update_os",
                    requested_at=now - timedelta(minutes=2),
                    status="succeeded",
                    result={"output": "CLIENTFLOW_REBOOT_REQUIRED=1"},
                )
            )
            session.add(
                _command(
                    client_id=client_id,
                    domain="system",
                    command_type="change_password",
                    requested_at=now - timedelta(minutes=9),
                    status="succeeded",
                )
            )
            session.add(
                _command(
                    client_id=client_id,
                    domain="system",
                    command_type="change_hostname",
                    requested_at=now - timedelta(minutes=1),
                    status="queued",
                    payload={"hostname": f"host-{index}", "client_name": f"perf-{index:03d}"},
                )
            )
        session.commit()


def _snapshot(client: Client) -> dict:
    return {field: getattr(client, field, None) for field in PROJECTION_FIELDS}


@pytest.mark.parametrize("client_count", [1, 10, 50, 100])
def test_clients_list_projection_query_count_is_constant(client_count: int) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    _seed(engine, client_count)

    select_count = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        with Session(engine) as session:
            result = clients_router.get_clients(
                session=session,
                user=SimpleNamespace(is_superadmin=True),
            )
            assert len(result) == client_count
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    # 1 client-list query + 1 joined presence/credential query +
    # 2 Display batch queries + 1 latest-System-command window query.
    # This must not grow with N.
    assert select_count == 5


def test_batched_client_list_projection_matches_single_client_projection() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    _seed(engine, 4)

    with Session(engine) as session:
        batched = session.exec(select(Client).order_by(Client.id)).all()
        clients_router._prepare_clients_read(session, batched)
        batched_snapshot = {int(client.id): _snapshot(client) for client in batched}

    with Session(engine) as session:
        singles = session.exec(select(Client).order_by(Client.id)).all()
        single_snapshot = {}
        for client in singles:
            clients_router._prepare_full_client_read(session, client)
            single_snapshot[int(client.id)] = _snapshot(client)

    assert batched_snapshot == single_snapshot


@pytest.mark.parametrize("seed_count", [1, 10, 50, 100])
def test_chrome_status_projection_query_count_is_constant(seed_count: int) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    _seed(engine, seed_count)

    select_count = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        with Session(engine) as session:
            payload = clients_router.get_chrome_status(
                1,
                session=session,
                user=SimpleNamespace(is_superadmin=True),
            )
            assert payload["client_id"] == 1
            assert payload["presence"]["status"]["domain"] == "status"
            assert payload["browser_requested"] is True
            assert payload["pending_reboot"] is True
            assert payload["pending_os_update"] is False
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    # 1 Client lookup + 1 joined presence/credential query +
    # 2 Display batch queries + 1 latest-System-command window query. The
    # 1-second detail poll must not grow with the number of clients present in
    # the database.
    assert select_count == 5
