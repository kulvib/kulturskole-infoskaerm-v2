"""Canonical System command producer and compatibility projection.

System owns privileged one-shot host operations.  The legacy ``Client``
aggregate is not command authority; commands live only in ``client_command``
with ``domain='system'`` and are consumed by the dedicated System agent/broker.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Any, Iterable

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException
from sqlmodel import Session, select

from .client_domain_models import ClientCommand, ClientDomainStatus
from .enrollment_models import ClientSystemEncryptionKey
from .models import Client

SYSTEM_DOMAIN = "system"
SYSTEM_COMMAND_TYPES = frozenset({"reboot", "shutdown", "update_os", "change_hostname", "change_password"})
SYSTEM_ACTIVE_STATUSES = frozenset({"queued", "claimed"})
SYSTEM_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "expired", "cancelled"})
LOCAL_MANAGEMENT_COMMANDS = frozenset({"change_hostname", "change_password"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def lock_system_client(session: Session, client_id: int) -> None:
    """Serialize System producers for a client."""
    row = session.exec(select(Client.id).where(Client.id == client_id).with_for_update()).first()
    if row is None:
        raise ValueError("System client findes ikke")


def latest_system_status(session: Session, client_id: int) -> ClientDomainStatus | None:
    return session.exec(
        select(ClientDomainStatus).where(
            ClientDomainStatus.client_id == client_id,
            ClientDomainStatus.domain == SYSTEM_DOMAIN,
        )
    ).first()


def system_status_has_broker(status: ClientDomainStatus | None) -> bool:
    if status is None or status.observed_state != "online":
        return False
    payload = status.status_payload if isinstance(status.status_payload, dict) else {}
    return payload.get("broker_socket") is True


def _commands(
    session: Session,
    client_id: int,
    *,
    command_types: Iterable[str] | None = None,
    active_only: bool = False,
    for_update: bool = False,
) -> list[ClientCommand]:
    query = select(ClientCommand).where(
        ClientCommand.client_id == client_id,
        ClientCommand.domain == SYSTEM_DOMAIN,
    )
    types = tuple(command_types or ())
    if types:
        query = query.where(ClientCommand.command_type.in_(types))
    if active_only:
        query = query.where(
            ClientCommand.status.in_(tuple(SYSTEM_ACTIVE_STATUSES)),
            ClientCommand.expires_at > utcnow(),
        )
    query = query.order_by(ClientCommand.requested_at.desc(), ClientCommand.id.desc())
    if for_update:
        query = query.with_for_update()
    return list(session.exec(query).all())


def active_system_command(session: Session, client_id: int, *, for_update: bool = False) -> ClientCommand | None:
    rows = _commands(session, client_id, active_only=True, for_update=for_update)
    return rows[0] if rows else None


def latest_system_command(
    session: Session,
    client_id: int,
    *,
    command_types: Iterable[str] | None = None,
) -> ClientCommand | None:
    rows = _commands(session, client_id, command_types=command_types)
    return rows[0] if rows else None


def queue_system_command(
    session: Session,
    *,
    client_id: int,
    command_type: str,
    payload: dict[str, Any] | None,
    requested_by_user_id: int | None,
    ttl_seconds: int,
    idempotency_prefix: str,
    command_id: str | None = None,
    payload_encryption_key_id: str | None = None,
    max_attempts: int = 3,
) -> ClientCommand:
    if command_type not in SYSTEM_COMMAND_TYPES:
        raise ValueError(f"Unsupported System command type: {command_type}")
    now = utcnow()
    row = ClientCommand(
        id=command_id or str(uuid.uuid4()),
        client_id=client_id,
        domain=SYSTEM_DOMAIN,
        command_type=command_type,
        schema_version=1,
        payload=dict(payload or {}),
        payload_encryption_key_id=payload_encryption_key_id,
        idempotency_key=f"{idempotency_prefix}:{uuid.uuid4()}",
        requested_by_user_id=requested_by_user_id,
        requested_at=now,
        available_at=now,
        expires_at=now + timedelta(seconds=max(30, int(ttl_seconds))),
        status="queued",
        max_attempts=min(max(int(max_attempts), 1), 10),
    )
    session.add(row)
    return row


def _active_system_encryption_key(
    session: Session,
    client_id: int,
    *,
    for_update: bool = False,
) -> ClientSystemEncryptionKey:
    query = select(ClientSystemEncryptionKey).where(
        ClientSystemEncryptionKey.client_id == client_id,
        ClientSystemEncryptionKey.revoked_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    row = session.exec(query).one_or_none()
    if row is None or row.algorithm != "RSA-OAEP-SHA256":
        raise HTTPException(status_code=409, detail="Klienten mangler en aktiv System encryption key")
    return row


def build_encrypted_password_payload(
    session: Session,
    *,
    client_id: int,
    command_id: str,
    new_password: str,
    target_user: str = "cfadmin",
) -> tuple[dict[str, Any], str]:
    """Encrypt a command-bound password envelope before it enters persistence."""
    key_row = _active_system_encryption_key(session, client_id, for_update=True)
    try:
        public_key = serialization.load_pem_public_key(key_row.public_key_pem.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError, UnsupportedAlgorithm) as exc:
        raise HTTPException(status_code=409, detail="Klientens System encryption key er ugyldig") from exc
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
        raise HTTPException(status_code=409, detail="Klientens System encryption key er ikke en gyldig RSA key")

    plaintext = json.dumps(
        {
            "target_user": target_user,
            "client_id": int(client_id),
            "command_id": command_id,
            "new_password": new_password,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest_size = hashes.SHA256().digest_size
    max_plaintext = public_key.key_size // 8 - (2 * digest_size) - 2
    if len(plaintext) > max_plaintext:
        raise HTTPException(status_code=400, detail="Adgangskoden er for lang til klientens System encryption key")
    ciphertext = public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return (
        {
            "target_user": target_user,
            "encrypted_payload": {
                "algorithm": "RSA-OAEP-SHA256",
                "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
            },
        },
        key_row.id,
    )



def apply_system_command_completion(session: Session, *, client_id: int, command_id: str) -> None:
    """Apply only control-plane metadata that is justified by broker success.

    Hostname execution remains owned by the System broker.  The human-facing
    Client.name is updated only after the authenticated System command has
    completed successfully; queuing the desired hostname does not claim that
    the host changed.
    """
    row = session.exec(
        select(ClientCommand).where(
            ClientCommand.id == command_id,
            ClientCommand.client_id == client_id,
            ClientCommand.domain == SYSTEM_DOMAIN,
            ClientCommand.status == "succeeded",
        )
    ).first()
    if row is None or row.command_type != "change_hostname":
        return
    payload = row.payload if isinstance(row.payload, dict) else {}
    client_name = str(payload.get("client_name") or "").strip()
    if not client_name or len(client_name) > 120 or any(ch in client_name for ch in ("\n", "\r", "\x00")):
        return
    client = session.exec(select(Client).where(Client.id == client_id).with_for_update()).first()
    if client is None:
        return
    client.name = client_name
    session.add(client)

def _command_status(row: ClientCommand | None) -> str:
    return str(row.status if row is not None else "").strip().lower()


def local_management_projection(session: Session, client_id: int) -> dict[str, Any]:
    row = latest_system_command(session, client_id, command_types=LOCAL_MANAGEMENT_COMMANDS)
    if row is None:
        return {
            "action": None,
            "request_id": None,
            "desired_hostname": None,
            "desired_client_name": None,
            "status": "ready",
            "message": "Ingen lokal klienthandling i gang",
            "requested_at": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
    status = _command_status(row)
    action = "hostname" if row.command_type == "change_hostname" else "cfadmin_password"
    public_status = {
        "queued": "pending",
        "claimed": "running",
        "succeeded": "success",
        "failed": "error",
        "expired": "error",
        "cancelled": "error",
    }.get(status, "error")
    payload = row.payload if isinstance(row.payload, dict) else {}
    if action == "hostname":
        base_message = "Lokalt hostname"
    else:
        base_message = "cfadmin-adgangskode"
    if public_status == "pending":
        message = f"Afventer System-agent: {base_message} ændres"
    elif public_status == "running":
        message = f"System-agent udfører: {base_message} ændres"
    elif public_status == "success":
        message = f"Gennemført: {base_message} er ændret"
    else:
        message = f"Fejl: {row.error_message or row.error_code or 'System-kommandoen fejlede'}"
    return {
        "action": action if public_status in {"pending", "running"} else action,
        "request_id": row.id,
        "desired_hostname": payload.get("hostname") if action == "hostname" else None,
        "desired_client_name": payload.get("client_name") if action == "hostname" else None,
        "status": public_status,
        "message": message[:500],
        "requested_at": row.requested_at,
        "started_at": row.claimed_at,
        "finished_at": row.completed_at,
        "error": (row.error_message or row.error_code) if public_status == "error" else None,
    }


def os_update_projection(session: Session, client_id: int) -> dict[str, Any]:
    row = latest_system_command(session, client_id, command_types={"update_os"})
    if row is None:
        return {
            "pending_os_update": False,
            "ubuntu_update_status": "ready",
            "ubuntu_update_step": None,
            "ubuntu_update_message": None,
            "ubuntu_update_error": None,
            "ubuntu_update_started_at": None,
            "ubuntu_update_updated_at": None,
            "ubuntu_update_finished_at": None,
            "ubuntu_update_progress": None,
            "ubuntu_update_package_count": None,
            "ubuntu_update_reboot_required": None,
        }
    status = _command_status(row)
    mapping = {
        "queued": ("requested", "os_update_requested", "Ubuntu-opdatering afventer System-agent", None),
        "claimed": ("installing", "os_update_installing", "Ubuntu-opdatering kører", None),
        "succeeded": ("success", "os_update_complete", "Ubuntu-opdatering gennemført", 100),
        "failed": ("error", "os_update_failed", "Ubuntu-opdatering fejlede", None),
        "expired": ("error", "os_update_failed", "Ubuntu-opdateringskommando udløb", None),
        "cancelled": ("error", "os_update_failed", "Ubuntu-opdateringskommando blev annulleret", None),
    }
    public_status, step, message, progress = mapping.get(status, ("error", "os_update_failed", "Ubuntu-opdateringsstatus er ukendt", None))
    error = (row.error_message or row.error_code) if public_status == "error" else None
    reboot_required: bool | None = None
    result = row.result if isinstance(row.result, dict) else {}
    output = str(result.get("output") or "")
    if "CLIENTFLOW_REBOOT_REQUIRED=1" in output:
        reboot_required = True
    elif "CLIENTFLOW_REBOOT_REQUIRED=0" in output:
        reboot_required = False
    if public_status == "success" and reboot_required is True:
        message = "Ubuntu-opdatering gennemført; genstart er påkrævet"
    return {
        "pending_os_update": status in SYSTEM_ACTIVE_STATUSES,
        "ubuntu_update_status": public_status,
        "ubuntu_update_step": step,
        "ubuntu_update_message": message,
        "ubuntu_update_error": error,
        "ubuntu_update_started_at": row.claimed_at,
        "ubuntu_update_updated_at": row.completed_at or row.claimed_at or row.requested_at,
        "ubuntu_update_finished_at": row.completed_at,
        "ubuntu_update_progress": progress,
        "ubuntu_update_package_count": None,
        "ubuntu_update_reboot_required": reboot_required,
    }


def power_projection(
    session: Session,
    client_id: int,
    *,
    current_boot_id: str | None,
    status_online: bool,
) -> dict[str, Any]:
    row = latest_system_command(session, client_id, command_types={"reboot", "shutdown"})
    result = {
        "pending_reboot": False,
        "pending_shutdown": False,
        "state": None,
        "last_power_event": None,
        "last_power_event_at": None,
        "last_power_event_source": None,
        "last_reboot_started_at": None,
        "last_shutdown_started_at": None,
    }
    if row is None:
        return result
    status = _command_status(row)
    payload = row.payload if isinstance(row.payload, dict) else {}
    action = row.command_type
    if action == "reboot":
        requested_boot_id = str(payload.get("requested_boot_id") or "") or None
        observed_new_boot = bool(
            status == "succeeded"
            and requested_boot_id
            and current_boot_id
            and current_boot_id != requested_boot_id
        )
        pending = status in SYSTEM_ACTIVE_STATUSES or (status == "succeeded" and not observed_new_boot)
        result["pending_reboot"] = pending
        result["state"] = "rebooting" if pending else ("error" if status in {"failed", "expired", "cancelled"} else "normal")
        result["last_power_event"] = "reboot_requested" if status == "queued" else "reboot_started"
        if observed_new_boot:
            result["last_power_event"] = "boot_completed"
        result["last_reboot_started_at"] = row.claimed_at or row.requested_at
    else:
        # systemctl --no-block poweroff returning successfully proves only that
        # systemd accepted the request. Canonical Status liveness must observe
        # either the host offline or, after a later physical power-on, a new
        # boot-id. The latter prevents an old successful shutdown from becoming
        # "pending" again when the machine comes back online.
        requested_boot_id = str(payload.get("requested_boot_id") or "") or None
        observed_offline = status == "succeeded" and not status_online
        observed_boot_after_shutdown = bool(
            status == "succeeded"
            and requested_boot_id
            and current_boot_id
            and current_boot_id != requested_boot_id
        )
        shutdown_complete = observed_offline or observed_boot_after_shutdown
        pending = status in SYSTEM_ACTIVE_STATUSES or (status == "succeeded" and not shutdown_complete)
        result["pending_shutdown"] = pending
        if status in {"failed", "expired", "cancelled"}:
            result["state"] = "error"
        elif observed_boot_after_shutdown:
            result["state"] = "normal"
        elif status in SYSTEM_ACTIVE_STATUSES | {"succeeded"}:
            result["state"] = "shutdown"
        result["last_power_event"] = "shutdown_requested" if status == "queued" else "shutdown_started"
        if observed_offline:
            result["last_power_event"] = "shutdown_completed"
        if observed_boot_after_shutdown:
            result["last_power_event"] = "boot_after_shutdown"
        result["last_shutdown_started_at"] = row.claimed_at or row.requested_at
    result["last_power_event_at"] = row.completed_at or row.claimed_at or row.requested_at
    result["last_power_event_source"] = str(payload.get("source") or "system_command")[:80]
    return result
