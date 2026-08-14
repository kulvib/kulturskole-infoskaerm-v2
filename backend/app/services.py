from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import secrets
from typing import Any
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Client, ClientCommand, LivestreamGeneration, LivestreamViewer, utcnow

DOMAIN = "livestream"
ACTIVE_GENERATION_STATES = {"starting", "running", "stopping"}
TERMINAL_GENERATION_STATES = {"stopped", "failed", "superseded"}
_SEGMENT_RE = re.compile(r"^segment-\d{9}\.(?:ts|m4s)$")
_ALLOWED_FILE_RE = re.compile(r"^(?:index\.m3u8|segment-\d{9}\.(?:ts|m4s)|init\.mp4)$")




def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_generation(db: Session, client_id: int) -> LivestreamGeneration | None:
    return db.scalar(
        select(LivestreamGeneration)
        .where(
            LivestreamGeneration.client_id == client_id,
            LivestreamGeneration.state.in_(ACTIVE_GENERATION_STATES),
        )
        .order_by(LivestreamGeneration.created_at.desc())
        .limit(1)
    )


def _lock_client(db: Session, client_id: int) -> None:
    db.scalar(select(Client.id).where(Client.id == client_id).with_for_update())


def active_viewer_count(db: Session, client_id: int, *, now: datetime | None = None) -> int:
    now = now or utcnow()
    cutoff = now - timedelta(seconds=settings.viewer_lease_seconds)
    return len(
        db.scalars(
            select(LivestreamViewer.id).where(
                LivestreamViewer.client_id == client_id,
                LivestreamViewer.ended_at.is_(None),
                LivestreamViewer.last_seen_at >= cutoff,
            )
        ).all()
    )


def viewer_enter(db: Session, *, client_id: int, user_id: int) -> tuple[LivestreamViewer, LivestreamGeneration | None, ClientCommand | None]:
    _lock_client(db, client_id)
    now = utcnow()
    viewer = LivestreamViewer(
        id=str(uuid.uuid4()),
        client_id=client_id,
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
    )
    db.add(viewer)
    db.flush()

    generation = current_generation(db, client_id)
    command = None
    if generation is None:
        generation, command = request_start(db, client_id)
    return viewer, generation, command


def viewer_heartbeat(
    db: Session,
    *,
    client_id: int,
    user_id: int,
    viewer_id: str,
) -> tuple[LivestreamViewer, LivestreamGeneration | None, ClientCommand | None]:
    _lock_client(db, client_id)
    viewer = db.get(LivestreamViewer, viewer_id)
    if viewer is None or viewer.client_id != client_id or viewer.user_id != user_id:
        raise HTTPException(status_code=404, detail="Viewer not found")
    if viewer.ended_at is not None:
        raise HTTPException(status_code=409, detail="Viewer lease has ended")

    now = utcnow()
    if now - _as_utc(viewer.last_seen_at) > timedelta(seconds=settings.viewer_lease_seconds):
        viewer.ended_at = _as_utc(viewer.last_seen_at) + timedelta(seconds=settings.viewer_lease_seconds)
        viewer.end_reason = "lease_expired"
        raise HTTPException(status_code=409, detail="Viewer lease expired")

    viewer.last_seen_at = now
    generation = current_generation(db, client_id)
    command = None
    if generation is None:
        generation, command = request_start(db, client_id)
    return viewer, generation, command


def viewer_leave(db: Session, *, client_id: int, user_id: int, viewer_id: str) -> LivestreamViewer | None:
    _lock_client(db, client_id)
    viewer = db.get(LivestreamViewer, viewer_id)
    if viewer is None or viewer.client_id != client_id or viewer.user_id != user_id:
        return None
    if viewer.ended_at is None:
        viewer.ended_at = utcnow()
        viewer.end_reason = "leave"
    return viewer


def _expire_stale_viewers(db: Session, client_id: int, *, now: datetime) -> None:
    cutoff = now - timedelta(seconds=settings.viewer_lease_seconds)
    rows = db.scalars(
        select(LivestreamViewer).where(
            LivestreamViewer.client_id == client_id,
            LivestreamViewer.ended_at.is_(None),
            LivestreamViewer.last_seen_at < cutoff,
        )
    ).all()
    for viewer in rows:
        viewer.ended_at = _as_utc(viewer.last_seen_at) + timedelta(seconds=settings.viewer_lease_seconds)
        viewer.end_reason = "lease_expired"


def reconcile_viewer_lifecycle(db: Session, client_id: int) -> str | None:
    """Expire viewer leases and stop/start Livestream from viewer ownership.

    Start is allowed only when at least one viewer is active. Stop occurs only
    after the last viewer has been absent for the configured grace period.
    """
    _lock_client(db, client_id)
    now = utcnow()
    _expire_stale_viewers(db, client_id, now=now)

    active = len(
        db.scalars(
            select(LivestreamViewer.id).where(
                LivestreamViewer.client_id == client_id,
                LivestreamViewer.ended_at.is_(None),
            )
        ).all()
    )
    generation = current_generation(db, client_id)

    if active > 0:
        if generation is None:
            request_start(db, client_id)
            return "start"
        return None

    if generation is None or generation.state == "stopping":
        return None

    last_ended = db.scalar(
        select(LivestreamViewer.ended_at)
        .where(
            LivestreamViewer.client_id == client_id,
            LivestreamViewer.ended_at.is_not(None),
        )
        .order_by(LivestreamViewer.ended_at.desc())
        .limit(1)
    )
    absent_since = _as_utc(last_ended) if last_ended is not None else _as_utc(generation.created_at)
    if now - absent_since < timedelta(seconds=settings.viewer_stop_grace_seconds):
        return None

    request_stop(db, client_id)
    return "stop"


def reconcile_all_viewer_lifecycles(db: Session) -> list[tuple[int, str]]:
    actions: list[tuple[int, str]] = []
    client_ids = db.scalars(select(Client.id).order_by(Client.id)).all()
    for client_id in client_ids:
        action = reconcile_viewer_lifecycle(db, client_id)
        if action:
            actions.append((client_id, action))
    return actions


def cancel_queued_generation_commands(db: Session, client_id: int) -> None:
    now = utcnow()
    rows = db.scalars(
        select(ClientCommand).where(
            ClientCommand.client_id == client_id,
            ClientCommand.domain == DOMAIN,
            ClientCommand.command_type.in_({"start", "restart", "reset_generation"}),
            ClientCommand.state == "queued",
        )
    ).all()
    for command in rows:
        command.state = "cancelled"
        command.error_code = "superseded_intent"
        command.error_message = "Replaced by a newer livestream intent"
        command.retryable = False
        command.completed_at = now
        command.updated_at = now


def enqueue_command(
    db: Session,
    *,
    client_id: int,
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> ClientCommand:
    command = ClientCommand(
        id=str(uuid.uuid4()),
        client_id=client_id,
        domain=DOMAIN,
        command_type=command_type,
        payload=payload or {},
        schema_version=1,
        state="queued",
    )
    db.add(command)
    return command


def _recover_expired_leases(db: Session, client_id: int) -> None:
    now = utcnow()
    rows = db.scalars(
        select(ClientCommand).where(
            ClientCommand.client_id == client_id,
            ClientCommand.domain == DOMAIN,
            ClientCommand.state == "leased",
            ClientCommand.lease_expires_at.is_not(None),
            ClientCommand.lease_expires_at < now,
        )
    ).all()
    for command in rows:
        if command.attempts >= settings.command_max_attempts:
            command.state = "failed"
            command.error_code = "lease_expired"
            command.error_message = "Command lease expired too many times"
            command.retryable = False
            command.completed_at = now
        else:
            command.state = "queued"
            command.available_at = now
            command.claim_token_digest = None
            command.lease_expires_at = None
        command.updated_at = now


def claim_command(db: Session, *, client_id: int, lease_seconds: int) -> dict[str, Any] | None:
    lease_seconds = min(max(int(lease_seconds), 10), 300)
    _recover_expired_leases(db, client_id)
    now = utcnow()
    command = db.scalar(
        select(ClientCommand)
        .where(
            ClientCommand.client_id == client_id,
            ClientCommand.domain == DOMAIN,
            ClientCommand.state == "queued",
            ClientCommand.available_at <= now,
        )
        .order_by(ClientCommand.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if command is None:
        return None
    claim_token = secrets.token_urlsafe(32)
    command.state = "leased"
    command.attempts += 1
    command.claim_token_digest = _token_digest(claim_token)
    command.lease_expires_at = now + timedelta(seconds=lease_seconds)
    command.updated_at = now
    return {
        "command": {
            "id": command.id,
            "client_id": command.client_id,
            "command_type": command.command_type,
            "payload": command.payload,
            "schema_version": command.schema_version,
        },
        "claim_token": claim_token,
    }


def _leased_command(db: Session, *, client_id: int, command_id: str, claim_token: str) -> ClientCommand:
    command = db.scalar(
        select(ClientCommand)
        .where(
            ClientCommand.id == command_id,
            ClientCommand.client_id == client_id,
            ClientCommand.domain == DOMAIN,
        )
        .with_for_update()
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if command.state != "leased" or not command.claim_token_digest:
        raise HTTPException(status_code=409, detail="Command is not leased")
    if command.lease_expires_at is None or _as_utc(command.lease_expires_at) < utcnow():
        raise HTTPException(status_code=409, detail="Command lease expired")
    if not secrets.compare_digest(command.claim_token_digest, _token_digest(claim_token)):
        raise HTTPException(status_code=409, detail="Claim token mismatch")
    return command


def renew_command(db: Session, *, client_id: int, command_id: str, claim_token: str, lease_seconds: int) -> None:
    command = _leased_command(db, client_id=client_id, command_id=command_id, claim_token=claim_token)
    lease_seconds = min(max(int(lease_seconds), 10), 300)
    command.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    command.updated_at = utcnow()


def complete_command(db: Session, *, client_id: int, command_id: str, claim_token: str, result: dict[str, Any]) -> ClientCommand:
    command = _leased_command(db, client_id=client_id, command_id=command_id, claim_token=claim_token)
    command.state = "completed"
    command.result = result
    command.retryable = None
    command.claim_token_digest = None
    command.lease_expires_at = None
    command.updated_at = utcnow()
    command.completed_at = utcnow()
    return command


def fail_command(
    db: Session,
    *,
    client_id: int,
    command_id: str,
    claim_token: str,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> ClientCommand:
    command = _leased_command(db, client_id=client_id, command_id=command_id, claim_token=claim_token)
    command.error_code = error_code[:128]
    command.error_message = error_message[:2000]
    command.retryable = bool(retryable)
    command.claim_token_digest = None
    command.lease_expires_at = None
    command.updated_at = utcnow()
    generation_id = str((command.payload or {}).get("generation_id") or "")
    generation = db.get(LivestreamGeneration, generation_id) if generation_id else None
    current = current_generation(db, client_id)
    stale_generation = bool(generation_id and (generation is None or current is None or current.id != generation_id or generation.state in {"stopping", "superseded"}))
    if retryable and not stale_generation and command.attempts < settings.command_max_attempts:
        command.state = "queued"
        command.available_at = utcnow() + timedelta(seconds=min(60, 2 ** command.attempts))
    else:
        command.state = "failed"
        command.completed_at = utcnow()
        if generation and generation.state not in TERMINAL_GENERATION_STATES and generation.state != "stopping":
            generation.state = "failed"
            generation.error_code = command.error_code
    return command


def _new_generation(db: Session, *, client_id: int, action: str, supersede_current: bool) -> tuple[LivestreamGeneration, ClientCommand]:
    cancel_queued_generation_commands(db, client_id)
    existing = current_generation(db, client_id)
    if existing and supersede_current:
        existing.state = "superseded"
        existing.superseded_at = utcnow()
    generation = LivestreamGeneration(
        id=str(uuid.uuid4()),
        client_id=client_id,
        state="starting",
        requested_action=action,
    )
    db.add(generation)
    command = enqueue_command(
        db,
        client_id=client_id,
        command_type=action,
        payload={"generation_id": generation.id},
    )
    return generation, command


def request_start(db: Session, client_id: int) -> tuple[LivestreamGeneration, ClientCommand | None]:
    existing = current_generation(db, client_id)
    if existing:
        if existing.state in {"starting", "running"}:
            return existing, None
        raise HTTPException(status_code=409, detail="Livestream is stopping")
    return _new_generation(db, client_id=client_id, action="start", supersede_current=False)


def request_restart(db: Session, client_id: int) -> tuple[LivestreamGeneration, ClientCommand]:
    return _new_generation(db, client_id=client_id, action="restart", supersede_current=True)


def request_reset_generation(db: Session, client_id: int) -> tuple[LivestreamGeneration, ClientCommand]:
    return _new_generation(db, client_id=client_id, action="reset_generation", supersede_current=True)


def request_stop(db: Session, client_id: int) -> tuple[LivestreamGeneration | None, ClientCommand | None]:
    cancel_queued_generation_commands(db, client_id)
    generation = current_generation(db, client_id)
    pending = db.scalar(
        select(ClientCommand)
        .where(
            ClientCommand.client_id == client_id,
            ClientCommand.domain == DOMAIN,
            ClientCommand.command_type == "stop",
            ClientCommand.state.in_({"queued", "leased"}),
        )
        .order_by(ClientCommand.created_at.desc())
        .limit(1)
    )
    if pending:
        return generation, pending
    if generation:
        generation.state = "stopping"
    return generation, enqueue_command(db, client_id=client_id, command_type="stop", payload={"generation_id": generation.id} if generation else {})


def ensure_current_generation(db: Session, *, client_id: int, generation_id: str, allowed_states: set[str]) -> LivestreamGeneration:
    generation = db.get(LivestreamGeneration, generation_id)
    current = current_generation(db, client_id)
    if (
        generation is None
        or generation.client_id != client_id
        or current is None
        or current.id != generation_id
        or generation.state not in allowed_states
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stale livestream generation")
    return generation


def generation_root(client_id: int, generation_id: str) -> Path:
    return settings.hls_root / str(client_id) / generation_id


def safe_hls_filename(filename: str) -> str:
    if not _ALLOWED_FILE_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid HLS filename")
    return filename


def validate_manifest(payload: bytes) -> None:
    if len(payload) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Manifest too large")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Manifest is not UTF-8") from exc
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" in line or line.startswith("/") or ".." in line or not _ALLOWED_FILE_RE.fullmatch(line):
            raise HTTPException(status_code=400, detail="Manifest contains an invalid URI")


def write_hls_file(*, client_id: int, generation_id: str, filename: str, payload: bytes, sha256: str) -> Path:
    filename = safe_hls_filename(filename)
    if len(payload) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="HLS file too large")
    actual = hashlib.sha256(payload).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256) or not secrets.compare_digest(actual, sha256):
        raise HTTPException(status_code=400, detail="sha256 mismatch")
    if filename == "index.m3u8":
        validate_manifest(payload)
    root = generation_root(client_id, generation_id)
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    temporary = root / f".{filename}.{secrets.token_hex(8)}.tmp"
    with open(temporary, "xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return target


def delete_generation_files(client_id: int, generation_id: str) -> None:
    root = generation_root(client_id, generation_id)
    if not root.exists():
        return
    for item in root.iterdir():
        if item.is_file() and not item.is_symlink():
            item.unlink(missing_ok=True)
    try:
        root.rmdir()
    except OSError:
        pass


def maybe_recover_stale_media(db: Session, client_id: int) -> bool:
    if active_viewer_count(db, client_id) == 0:
        return False
    generation = current_generation(db, client_id)
    if generation is None or generation.state not in {"starting", "running"}:
        return False
    reference = generation.last_upload_at or generation.started_at or generation.created_at
    if utcnow() - _as_utc(reference) <= timedelta(seconds=settings.media_stale_seconds):
        return False
    pending = db.scalar(
        select(ClientCommand.id)
        .where(
            ClientCommand.client_id == client_id,
            ClientCommand.domain == DOMAIN,
            ClientCommand.command_type.in_({"start", "restart", "reset_generation"}),
            ClientCommand.state.in_({"queued", "leased"}),
        )
        .limit(1)
    )
    if pending:
        return False
    recent_recoveries = db.scalars(
        select(LivestreamGeneration.id).where(
            LivestreamGeneration.client_id == client_id,
            LivestreamGeneration.requested_action == "reset_generation",
            LivestreamGeneration.created_at >= utcnow() - timedelta(minutes=10),
        )
    ).all()
    if len(recent_recoveries) >= 3:
        generation.state = "failed"
        generation.error_code = "media_stalled"
        enqueue_command(db, client_id=client_id, command_type="stop", payload={})
        return True
    request_reset_generation(db, client_id)
    return True
