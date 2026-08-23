"""Canonical Display desired-state and command producer.

Display owns kiosk/browser desired state and browser/display-power commands.  The
legacy ``Client`` aggregate is deliberately not used as Display authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlmodel import Session, select

from .client_domain_models import ClientCommand, ClientDomainStatus, DisplayDesiredConfiguration
from .models import Client

DISPLAY_DOMAIN = "display"
DISPLAY_CONFIGURATION_SCHEMA = 1
DISPLAY_MIN_COMMAND_AGENT_VERSION = "1.3.5"
DISPLAY_CONTROL_COMMANDS = frozenset(
    {"start_browser", "stop_browser", "reset_browser", "set_display_power"}
)
DISPLAY_COMMAND_TO_LEGACY_ACTION = {
    "start_browser": "start",
    "stop_browser": "stop",
    "reset_browser": "reset_browser",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?\s*", str(value or ""))
    if not match:
        return None
    return tuple(int(match.group(index)) for index in (1, 2, 3))


def display_agent_supports_commands(agent_version: str | None) -> bool:
    actual = _version_tuple(agent_version)
    minimum = _version_tuple(DISPLAY_MIN_COMMAND_AGENT_VERSION)
    return bool(actual is not None and minimum is not None and actual >= minimum)


def normalize_kiosk_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) > 2048:
        raise HTTPException(status_code=400, detail="Kiosk URL er for lang")
    try:
        parsed = urlsplit(raw)
        # Accessing .port validates malformed/non-numeric ports.
        _ = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Kiosk URL er ugyldig") from exc
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(status_code=400, detail="Kiosk URL må ikke indeholde login-oplysninger")
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() == "https":
        if not host or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Kiosk URL skal have et gyldigt HTTPS-hostnavn")
        return raw
    if parsed.scheme.lower() == "http" and host in {"localhost", "127.0.0.1"}:
        return raw
    raise HTTPException(
        status_code=400,
        detail="Kiosk URL kræver HTTPS; HTTP er kun tilladt til localhost eller 127.0.0.1",
    )


def lock_display_client(session: Session, client_id: int) -> None:
    """Serialize Display desired-state/control producers per client."""
    row = session.exec(
        select(Client.id).where(Client.id == client_id).with_for_update()
    ).first()
    if row is None:
        raise ValueError("Display client findes ikke")


def get_display_desired_configuration(
    session: Session,
    client_id: int,
    *,
    for_update: bool = False,
) -> DisplayDesiredConfiguration | None:
    query = select(DisplayDesiredConfiguration).where(DisplayDesiredConfiguration.client_id == client_id)
    if for_update:
        query = query.with_for_update()
    return session.exec(query).first()


def set_display_desired_kiosk_url(
    session: Session,
    *,
    client_id: int,
    kiosk_url: Any,
    updated_by_user_id: int | None,
) -> DisplayDesiredConfiguration:
    normalized = normalize_kiosk_url(kiosk_url)
    lock_display_client(session, client_id)
    row = get_display_desired_configuration(session, client_id, for_update=True)
    now = utcnow()
    if row is None:
        row = DisplayDesiredConfiguration(
            client_id=client_id,
            schema_version=DISPLAY_CONFIGURATION_SCHEMA,
            revision=1,
            kiosk_url=normalized,
            updated_at=now,
            updated_by_user_id=updated_by_user_id,
        )
    elif row.kiosk_url != normalized:
        row.revision += 1
        row.kiosk_url = normalized
        row.updated_at = now
        row.updated_by_user_id = updated_by_user_id
    session.add(row)
    return row


def latest_display_status(session: Session, client_id: int) -> ClientDomainStatus | None:
    return session.exec(
        select(ClientDomainStatus).where(
            ClientDomainStatus.client_id == client_id,
            ClientDomainStatus.domain == DISPLAY_DOMAIN,
        )
    ).first()


def _active_display_commands(session: Session, client_id: int) -> list[ClientCommand]:
    return list(
        session.exec(
            select(ClientCommand)
            .where(
                ClientCommand.client_id == client_id,
                ClientCommand.domain == DISPLAY_DOMAIN,
                ClientCommand.status.in_(["queued", "claimed"]),
                ClientCommand.expires_at > utcnow(),
            )
            .order_by(ClientCommand.requested_at, ClientCommand.id)
        ).all()
    )


def active_display_control_command(session: Session, client_id: int) -> ClientCommand | None:
    for row in _active_display_commands(session, client_id):
        if row.command_type in DISPLAY_CONTROL_COMMANDS:
            return row
    return None


def display_command_legacy_action(row: ClientCommand | None) -> str:
    if row is None:
        return "none"
    if row.command_type == "set_display_power":
        state = str((row.payload or {}).get("state") or "")
        return "sleep" if state == "off" else "wakeup" if state == "on" else "none"
    return DISPLAY_COMMAND_TO_LEGACY_ACTION.get(row.command_type, "none")


def queue_display_command(
    session: Session,
    *,
    client_id: int,
    command_type: str,
    payload: dict[str, Any] | None,
    requested_by_user_id: int | None,
    ttl_seconds: int = 300,
    idempotency_prefix: str = "display",
) -> ClientCommand:
    if command_type not in DISPLAY_CONTROL_COMMANDS | {"apply_configuration"}:
        raise ValueError(f"Unsupported Display command type: {command_type}")
    now = utcnow()
    row = ClientCommand(
        id=str(uuid.uuid4()),
        client_id=client_id,
        domain=DISPLAY_DOMAIN,
        command_type=command_type,
        schema_version=1,
        payload=dict(payload or {}),
        idempotency_key=f"{idempotency_prefix}:{uuid.uuid4()}",
        requested_by_user_id=requested_by_user_id,
        requested_at=now,
        available_at=now,
        expires_at=now + timedelta(seconds=max(30, int(ttl_seconds))),
        status="queued",
        max_attempts=3,
    )
    session.add(row)
    return row


def _runtime_payload(status_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = status_payload if isinstance(status_payload, dict) else {}
    runtime = payload.get("runtime")
    return runtime if isinstance(runtime, dict) else {}


def reconcile_display_configuration(
    session: Session,
    *,
    client_id: int,
    agent_version: str | None,
    status_payload: dict[str, Any] | None,
) -> ClientCommand | None:
    """Ensure durable desired configuration eventually reaches a capable agent.

    The command is transport only.  If it expires/fails, the next status report
    queues another command until the observed revision matches the durable row.
    """
    if not display_agent_supports_commands(agent_version):
        return None
    desired = get_display_desired_configuration(session, client_id, for_update=True)
    if desired is None:
        return None
    runtime = _runtime_payload(status_payload)
    try:
        observed_revision = int(runtime.get("configuration_revision"))
    except (TypeError, ValueError):
        observed_revision = None

    active = _active_display_commands(session, client_id)
    if observed_revision == desired.revision:
        for row in active:
            if row.command_type == "apply_configuration" and row.status == "queued":
                row.status = "cancelled"
                row.completed_at = utcnow()
                row.error_code = "configuration_already_observed"
                row.error_message = "Display har allerede den ønskede konfigurationsrevision"
                session.add(row)
        return None

    for row in active:
        if row.command_type != "apply_configuration":
            continue
        try:
            queued_revision = int((row.payload or {}).get("revision"))
        except (TypeError, ValueError):
            queued_revision = None
        if queued_revision == desired.revision:
            return row
        if row.status == "queued":
            row.status = "cancelled"
            row.completed_at = utcnow()
            row.error_code = "configuration_superseded"
            row.error_message = "En nyere Display-konfigurationsrevision er ønsket"
            session.add(row)

    return queue_display_command(
        session,
        client_id=client_id,
        command_type="apply_configuration",
        payload={
            "schema_version": DISPLAY_CONFIGURATION_SCHEMA,
            "revision": desired.revision,
            "kiosk_url": desired.kiosk_url,
        },
        requested_by_user_id=desired.updated_by_user_id,
        ttl_seconds=600,
        idempotency_prefix=f"display-configuration-r{desired.revision}",
    )


def _epoch_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def display_read_projection(session: Session, client_id: int) -> dict[str, Any]:
    desired = get_display_desired_configuration(session, client_id)
    status = latest_display_status(session, client_id)
    status_payload = status.status_payload if status and isinstance(status.status_payload, dict) else {}
    runtime = _runtime_payload(status_payload)
    state = str(runtime.get("state") or "unknown").strip().lower()
    runtime_updated = _epoch_datetime(runtime.get("updated_at"))
    if state == "running":
        chrome_status = "Kiosk browser kører"
        chrome_color = "green"
        chrome_step = "start_chrome"
        chrome_running: bool | None = True
    elif state == "stopped":
        chrome_status = "Browser stoppet"
        chrome_color = "gray"
        chrome_step = "chrome_closed_programmatically"
        chrome_running = False
    elif state == "waiting_session":
        chrome_status = "Browser venter på aktiv kiosk-session"
        chrome_color = "orange"
        chrome_step = "browser_waiting_session"
        chrome_running = False
    elif state == "failed":
        detail = str(runtime.get("error") or "browser_runtime_failed")[:240]
        chrome_status = f"Browserfejl: {detail}"
        chrome_color = "red"
        chrome_step = "chrome_failed"
        chrome_running = False
    else:
        chrome_status = "Browserstatus ukendt"
        chrome_color = "orange"
        chrome_step = None
        chrome_running = None

    step_updated = runtime_updated
    power = status_payload.get("display_power") if isinstance(status_payload, dict) else None
    power = power if isinstance(power, dict) else {}
    power_state = str(power.get("state") or "unknown").strip().lower()
    power_updated = _epoch_datetime(power.get("updated_at"))
    if power_state in {"on", "off"} and power_updated is not None and (runtime_updated is None or power_updated >= runtime_updated):
        chrome_step = "display_wake_complete" if power_state == "on" else "display_sleep_complete"
        step_updated = power_updated

    active = active_display_control_command(session, client_id)
    pending = display_command_legacy_action(active)
    return {
        "kiosk_url": desired.kiosk_url if desired else None,
        "display_configuration_revision": desired.revision if desired else None,
        "chrome_status": chrome_status,
        "chrome_color": chrome_color,
        "chrome_step": chrome_step,
        "chrome_running": chrome_running,
        "chrome_last_updated": step_updated or (status.reported_at if status else None),
        "pending_chrome_action": pending,
        "pending_chrome_action_source": "display_command" if pending != "none" else None,
        "display_agent_version": status.agent_version if status else None,
        "display_power": power_state,
    }
