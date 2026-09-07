"""Isolated Livestream v2 control plane for ClientFlow 1.2.

This module intentionally owns only the livestream domain.  It does not import
Terminal or Remote Desktop code and it stores commands, viewers, generations,
credentials and agent status in dedicated livestream_v2_* tables.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Optional
import uuid

import jwt
from fastapi import HTTPException, status
from sqlmodel import Session, select

from .auth import SECRET_KEY
from .client_activity import (
    active_livestream_activity_client_ids,
    active_livestream_activity_count,
    last_livestream_activity_ended_at,
)
from .db import engine
from .models import Client
from .livestream_v2_models import (
    LivestreamV2AgentStatus,
    LivestreamV2Command,
    LivestreamV2Credential,
    LivestreamV2Generation,
    LivestreamV2Viewer,
    utcnow,
)
from .routers.livestream_media import HLS_DIR, safe_client_dir

DOMAIN = "livestream"
ACTIVE_GENERATION_STATES = {"starting", "running", "stopping"}
FINAL_GENERATION_STATES = {"stopped", "failed", "superseded"}
VIEWER_HEARTBEAT_SECONDS = max(5, int(os.getenv("LIVESTREAM_V2_VIEWER_HEARTBEAT_SECONDS", "10")))
VIEWER_LEASE_SECONDS = max(15, int(os.getenv("LIVESTREAM_V2_VIEWER_LEASE_SECONDS", "30")))
VIEWER_STOP_GRACE_SECONDS = max(5, int(os.getenv("LIVESTREAM_V2_VIEWER_STOP_GRACE_SECONDS", "30")))
VIEWER_SWEEP_SECONDS = max(2, int(os.getenv("LIVESTREAM_V2_VIEWER_SWEEP_SECONDS", "5")))
MEDIA_STALE_SECONDS = max(15, int(os.getenv("LIVESTREAM_V2_MEDIA_STALE_SECONDS", "45")))
COMMAND_MAX_ATTEMPTS = max(1, int(os.getenv("LIVESTREAM_V2_COMMAND_MAX_ATTEMPTS", "5")))
MAX_HLS_FILE_BYTES = 64 * 1024 * 1024
CLIENT_TOKEN_TTL_SECONDS = min(max(60, int(os.getenv("LIVESTREAM_V2_CLIENT_TOKEN_TTL_SECONDS", "600"))), 3600)
TOKEN_ISSUER = os.getenv("LIVESTREAM_V2_TOKEN_ISSUER", "clientflow-api").strip() or "clientflow-api"



_ALLOWED_FILE_RE = re.compile(r"^(?:index\.m3u8|segment-\d{9}\.(?:ts|m4s)|init\.mp4)$")
_SEGMENT_RE = re.compile(r"^segment-(\d{9})\.(?:ts|m4s)$")
_sweeper_started = False
_sweeper_lock = threading.Lock()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _now() -> datetime:
    return utcnow()


def _credential_pepper() -> str:
    value = os.getenv("LIVESTREAM_V2_CREDENTIAL_PEPPER") or os.getenv("CREDENTIAL_PEPPER") or ""
    if len(value) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Livestream v2 credential pepper er ikke konfigureret",
        )
    return value


def credential_digest(secret: str) -> str:
    return hmac.new(
        _credential_pepper().encode("utf-8"),
        secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _bootstrap_credential_if_allowed(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    client_secret: str,
) -> LivestreamV2Credential | None:
    """One-time import path for the already installed, high-entropy credential.

    Only a SHA-256 fingerprint is configured in Render.  The raw secret remains
    on the Ubuntu client and is never stored or logged by this bootstrap path.
    Once the row exists, this branch is no longer used.
    """
    expected_client = str(os.getenv("LIVESTREAM_V2_BOOTSTRAP_CLIENT_ID", "")).strip()
    expected_credential = str(os.getenv("LIVESTREAM_V2_BOOTSTRAP_CREDENTIAL_ID", "")).strip()
    expected_sha = str(os.getenv("LIVESTREAM_V2_BOOTSTRAP_SECRET_SHA256", "")).strip().lower()
    if not expected_client or not expected_credential or not expected_sha:
        return None
    if str(client_id) != expected_client or credential_id != expected_credential:
        return None
    actual_sha = hashlib.sha256(client_secret.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(actual_sha, expected_sha):
        return None
    # Serialise the one-time bootstrap per client. Agent + uploader can request
    # their first token at the same time after deployment; the client row lock
    # prevents two inserts of the same credential.
    client = session.exec(select(Client).where(Client.id == client_id).with_for_update()).first()
    if client is None or str(getattr(client, "status", "") or "").lower() != "approved":
        return None
    existing = session.get(LivestreamV2Credential, credential_id)
    if existing is not None:
        return existing
    row = LivestreamV2Credential(
        id=credential_id,
        client_id=client_id,
        domain=DOMAIN,
        secret_digest=credential_digest(client_secret),
        token_version=1,
        created_at=_now(),
    )
    session.add(row)
    session.flush()
    return row


def authenticate_credential(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    domain: str,
    client_secret: str,
) -> LivestreamV2Credential:
    if domain != DOMAIN:
        # This isolated router must not become the auth implementation for
        # Terminal/Remote Desktop.  Before this integration the shared
        # /client-auth/token route did not exist in this repo, so preserve a
        # not-found boundary for every non-Livestream domain.
        raise HTTPException(status_code=404, detail="Domæne-endpoint ikke fundet")
    try:
        uuid.UUID(credential_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt credential") from exc
    row = session.get(LivestreamV2Credential, credential_id)
    if row is None:
        row = _bootstrap_credential_if_allowed(
            session,
            client_id=client_id,
            credential_id=credential_id,
            client_secret=client_secret,
        )
    client = session.get(Client, client_id)
    if (
        row is None
        or client is None
        or str(getattr(client, "status", "") or "").lower() != "approved"
        or getattr(client, "deleted_at", None) is not None
        or row.client_id != client_id
        or row.domain != DOMAIN
        or row.revoked_at is not None
        or not secrets.compare_digest(row.secret_digest, credential_digest(client_secret))
    ):
        raise HTTPException(status_code=401, detail="Ugyldigt credential")
    return row


def _create_bound_client_token(
    *,
    client_id: int,
    credential_id: str,
    token_version: int,
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=CLIENT_TOKEN_TTL_SECONDS)
    audience = f"clientflow-domain:{DOMAIN}"
    scope = f"clientflow:{DOMAIN}"
    claims = {
        "iss": TOKEN_ISSUER,
        "sub": f"client:{client_id}:{credential_id}",
        "principal": "client_domain",
        "client_id": client_id,
        "credential_id": credential_id,
        "domain": DOMAIN,
        "scope": scope,
        "aud": audience,
        "token_version": token_version,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, SECRET_KEY, algorithm="HS256"), expires_at


def create_client_token(credential: LivestreamV2Credential) -> tuple[str, datetime]:
    return _create_bound_client_token(
        client_id=credential.client_id,
        credential_id=credential.id,
        token_version=credential.token_version,
    )



def require_agent_token(
    session: Session, authorization: str | None, *, client_id: int
) -> LivestreamV2Credential | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token mangler")
    token = authorization[7:].strip()
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"],
            audience=f"clientflow-domain:{DOMAIN}",
            issuer=TOKEN_ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt livestream-agent token") from exc
    if (
        claims.get("principal") != "client_domain"
        or claims.get("domain") != DOMAIN
        or claims.get("scope") != f"clientflow:{DOMAIN}"
        or int(claims.get("client_id") or 0) != client_id
    ):
        raise HTTPException(status_code=403, detail="Token tilhører et andet livestream-domæne eller klient")

    credential = session.get(LivestreamV2Credential, str(claims.get("credential_id") or ""))
    client = session.get(Client, client_id)
    if (
        credential is None
        or client is None
        or str(getattr(client, "status", "") or "").lower() != "approved"
        or getattr(client, "deleted_at", None) is not None
        or credential.client_id != client_id
        or credential.domain != DOMAIN
        or credential.revoked_at is not None
        or credential.token_version != int(claims.get("token_version") or -1)
    ):
        raise HTTPException(status_code=401, detail="Livestream credential er tilbagekaldt, forældet eller klienten er deaktiveret")
    return credential


def current_generation(session: Session, client_id: int) -> LivestreamV2Generation | None:
    return session.exec(
        select(LivestreamV2Generation)
        .where(
            LivestreamV2Generation.client_id == client_id,
            LivestreamV2Generation.state.in_(ACTIVE_GENERATION_STATES),
        )
        .order_by(LivestreamV2Generation.created_at.desc())
        .limit(1)
    ).first()


def _lock_client(session: Session, client_id: int) -> Client:
    client = session.exec(select(Client).where(Client.id == client_id).with_for_update()).first()
    if client is None:
        raise HTTPException(status_code=404, detail="Klient ikke fundet")
    return client


def _require_livestream_start_allowed(client: Client) -> None:
    state = str(getattr(client, "state", "") or "").strip().lower()
    if (
        state in {"shutdown", "rebooting", "updating"}
        or bool(getattr(client, "pending_shutdown", False))
        or bool(getattr(client, "pending_reboot", False))
    ):
        raise HTTPException(status_code=409, detail="Livestream er blokeret under aktiv System-lifecycle")


def explicit_stop_latched(session: Session, client_id: int) -> bool:
    client = session.get(Client, client_id)
    if client is None:
        return False
    return str(getattr(client, "livestream_stop_reason", "") or "").lower().startswith(
        "explicit_stop:"
    )


def _principal_key(principal: object) -> str:
    principal_id = getattr(principal, "id", None)
    role = str(getattr(principal, "role", "") or "user")
    kind = "client" if getattr(principal, "is_client", False) else role
    return f"{kind}:{principal_id}"


def _normalise_viewer_id(value: str | None) -> str:
    viewer_id = str(value or "").strip()[:120]
    if not viewer_id:
        raise HTTPException(status_code=400, detail="viewer_id mangler")
    return viewer_id


def _expire_stale_viewers(session: Session, client_id: int, *, now: datetime) -> None:
    cutoff = now - timedelta(seconds=VIEWER_LEASE_SECONDS)
    rows = session.exec(
        select(LivestreamV2Viewer).where(
            LivestreamV2Viewer.client_id == client_id,
            LivestreamV2Viewer.ended_at.is_(None),
            LivestreamV2Viewer.last_seen_at < cutoff,
        )
    ).all()
    for row in rows:
        row.ended_at = row.last_seen_at + timedelta(seconds=VIEWER_LEASE_SECONDS)
        row.end_reason = "lease_expired"
        session.add(row)


def active_viewer_count(session: Session, client_id: int) -> int:
    now = _now()
    _expire_stale_viewers(session, client_id, now=now)
    return len(
        session.exec(
            select(LivestreamV2Viewer.id).where(
                LivestreamV2Viewer.client_id == client_id,
                LivestreamV2Viewer.ended_at.is_(None),
            )
        ).all()
    )


def viewer_heartbeat(
    session: Session,
    *,
    client_id: int,
    principal: object,
    viewer_id: str,
    source: str | None,
) -> tuple[LivestreamV2Viewer, LivestreamV2Generation | None, LivestreamV2Command | None]:
    client = _lock_client(session, client_id)
    _require_livestream_start_allowed(client)
    now = _now()
    viewer_id = _normalise_viewer_id(viewer_id)
    principal_key = _principal_key(principal)
    row = session.exec(
        select(LivestreamV2Viewer).where(
            LivestreamV2Viewer.client_id == client_id,
            LivestreamV2Viewer.viewer_id == viewer_id,
        )
    ).first()
    if row is None:
        row = LivestreamV2Viewer(
            client_id=client_id,
            viewer_id=viewer_id,
            principal_key=principal_key,
            source=str(source or "")[:120] or None,
            created_at=now,
            last_seen_at=now,
        )
    else:
        if row.principal_key != principal_key:
            raise HTTPException(status_code=409, detail="viewer_id tilhører en anden session")
        row.source = str(source or "")[:120] or None
        row.last_seen_at = now
        row.ended_at = None
        row.end_reason = None
    session.add(row)
    generation = current_generation(session, client_id)
    command = None
    if generation is None and not explicit_stop_latched(session, client_id):
        generation, command = request_start(session, client_id, source="viewer_present")
    return row, generation, command


def viewer_leave(
    session: Session,
    *,
    client_id: int,
    principal: object,
    viewer_id: str,
    source: str | None,
) -> LivestreamV2Viewer | None:
    _lock_client(session, client_id)
    row = session.exec(
        select(LivestreamV2Viewer).where(
            LivestreamV2Viewer.client_id == client_id,
            LivestreamV2Viewer.viewer_id == _normalise_viewer_id(viewer_id),
        )
    ).first()
    if row is None:
        return None
    if row.principal_key != _principal_key(principal):
        raise HTTPException(status_code=409, detail="viewer_id tilhører en anden session")
    if row.ended_at is None:
        row.ended_at = _now()
        row.end_reason = "leave"
        row.source = str(source or row.source or "")[:120] or None
        session.add(row)
    return row


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def cancel_queued_generation_commands(session: Session, client_id: int) -> None:
    now = _now()
    rows = session.exec(
        select(LivestreamV2Command).where(
            LivestreamV2Command.client_id == client_id,
            LivestreamV2Command.command_type.in_({"start", "restart", "reset_generation"}),
            LivestreamV2Command.state == "queued",
        )
    ).all()
    for command in rows:
        command.state = "cancelled"
        command.error_code = "superseded_intent"
        command.error_message = "Erstattet af en nyere Livestream-intent"
        command.retryable = False
        command.completed_at = now
        command.updated_at = now
        session.add(command)


def enqueue_command(
    session: Session,
    *,
    client_id: int,
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> LivestreamV2Command:
    command = LivestreamV2Command(
        id=str(uuid.uuid4()),
        client_id=client_id,
        command_type=command_type,
        payload=payload or {},
        schema_version=1,
        state="queued",
        attempts=0,
        available_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(command)
    return command


def _new_generation(
    session: Session,
    *,
    client_id: int,
    action: str,
    supersede_current: bool,
    source: str | None,
) -> tuple[LivestreamV2Generation, LivestreamV2Command]:
    client = _lock_client(session, client_id)
    _require_livestream_start_allowed(client)
    cancel_queued_generation_commands(session, client_id)
    now = _now()
    existing = current_generation(session, client_id)
    if existing is not None and supersede_current:
        existing.state = "superseded"
        existing.superseded_at = now
        session.add(existing)
    generation = LivestreamV2Generation(
        id=str(uuid.uuid4()),
        client_id=client_id,
        state="starting",
        requested_action=action,
        created_at=now,
    )
    session.add(generation)
    command = enqueue_command(
        session,
        client_id=client_id,
        command_type=action,
        payload={"generation_id": generation.id},
    )
    client.livestream_desired_state = "running"
    client.livestream_stop_reason = None
    client.livestream_status = "starting"
    session.add(client)
    _write_generation_marker(client_id, generation.id)
    return generation, command


def request_start(
    session: Session,
    client_id: int,
    *,
    source: str | None = None,
) -> tuple[LivestreamV2Generation, LivestreamV2Command | None]:
    # Lock before checking current state so concurrent browser/manual starts
    # coalesce to one generation just like concurrent viewer heartbeats.
    client = _lock_client(session, client_id)
    _require_livestream_start_allowed(client)
    existing = current_generation(session, client_id)
    if existing is not None:
        if existing.state in {"starting", "running"}:
            return existing, None
        raise HTTPException(status_code=409, detail="Livestream er ved at stoppe")
    return _new_generation(session, client_id=client_id, action="start", supersede_current=False, source=source)


def request_restart(session: Session, client_id: int, *, source: str | None = None) -> tuple[LivestreamV2Generation, LivestreamV2Command]:
    return _new_generation(session, client_id=client_id, action="restart", supersede_current=True, source=source)


def request_reset_generation(session: Session, client_id: int) -> tuple[LivestreamV2Generation, LivestreamV2Command]:
    return _new_generation(session, client_id=client_id, action="reset_generation", supersede_current=True, source="watchdog")


def request_stop(
    session: Session,
    client_id: int,
    *,
    source: str | None = None,
    explicit: bool = False,
) -> tuple[LivestreamV2Generation | None, LivestreamV2Command | None]:
    client = _lock_client(session, client_id)
    cancel_queued_generation_commands(session, client_id)
    generation = current_generation(session, client_id)
    existing_stop = session.exec(
        select(LivestreamV2Command).where(
            LivestreamV2Command.client_id == client_id,
            LivestreamV2Command.command_type == "stop",
            LivestreamV2Command.state.in_({"queued", "leased"}),
        ).limit(1)
    ).first()
    if generation is not None:
        generation.state = "stopping"
        session.add(generation)
    client.livestream_desired_state = "stopped"
    stop_reason = str(source or "viewer_absent")
    if explicit:
        client.livestream_stop_reason = f"explicit_stop:{stop_reason}"[:500]
    elif not explicit_stop_latched(session, client_id):
        client.livestream_stop_reason = stop_reason[:500]
    client.livestream_status = "stopping" if generation is not None else "stopped"
    session.add(client)
    if existing_stop is not None:
        return generation, None
    return generation, enqueue_command(
        session,
        client_id=client_id,
        command_type="stop",
        payload={"generation_id": generation.id} if generation else {},
    )


def _recover_expired_leases(session: Session, client_id: int) -> None:
    now = _now()
    rows = session.exec(
        select(LivestreamV2Command).where(
            LivestreamV2Command.client_id == client_id,
            LivestreamV2Command.state == "leased",
            LivestreamV2Command.lease_expires_at.is_not(None),
            LivestreamV2Command.lease_expires_at < now,
        )
    ).all()
    for command in rows:
        if command.attempts >= COMMAND_MAX_ATTEMPTS:
            command.state = "failed"
            command.error_code = "lease_expired"
            command.error_message = "Command lease udløb for mange gange"
            command.retryable = False
            command.completed_at = now
        else:
            command.state = "queued"
            command.available_at = now
            command.claim_token_digest = None
            command.lease_expires_at = None
        command.updated_at = now
        session.add(command)


def claim_command(session: Session, *, client_id: int, lease_seconds: int) -> dict[str, Any] | None:
    _recover_expired_leases(session, client_id)
    now = _now()
    command = session.exec(
        select(LivestreamV2Command)
        .where(
            LivestreamV2Command.client_id == client_id,
            LivestreamV2Command.state == "queued",
            LivestreamV2Command.available_at <= now,
        )
        .order_by(LivestreamV2Command.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if command is None:
        return None
    claim_token = secrets.token_urlsafe(32)
    command.state = "leased"
    command.attempts += 1
    command.claim_token_digest = _token_digest(claim_token)
    command.lease_expires_at = now + timedelta(seconds=lease_seconds)
    command.updated_at = now
    session.add(command)
    return {
        "command": {
            "id": command.id,
            "client_id": command.client_id,
            "command_type": command.command_type,
            "payload": command.payload or {},
            "schema_version": command.schema_version,
        },
        "claim_token": claim_token,
        "lease_expires_at": command.lease_expires_at,
    }


def _leased_command(session: Session, *, client_id: int, command_id: str, claim_token: str) -> LivestreamV2Command:
    command = session.exec(
        select(LivestreamV2Command).where(
            LivestreamV2Command.id == command_id,
            LivestreamV2Command.client_id == client_id,
        )
    ).first()
    if command is None:
        raise HTTPException(status_code=404, detail="Livestream-command ikke fundet")
    if command.state != "leased" or not command.claim_token_digest:
        raise HTTPException(status_code=409, detail="Livestream-command er ikke leased")
    if command.lease_expires_at is None or command.lease_expires_at < _now():
        raise HTTPException(status_code=409, detail="Livestream-command lease er udløbet")
    if not secrets.compare_digest(command.claim_token_digest, _token_digest(claim_token)):
        raise HTTPException(status_code=403, detail="Ugyldigt claim_token")
    return command


def renew_command(session: Session, *, client_id: int, command_id: str, claim_token: str, lease_seconds: int) -> None:
    command = _leased_command(session, client_id=client_id, command_id=command_id, claim_token=claim_token)
    command.lease_expires_at = _now() + timedelta(seconds=lease_seconds)
    command.updated_at = _now()
    session.add(command)


def complete_command(
    session: Session,
    *,
    client_id: int,
    command_id: str,
    claim_token: str,
    result: dict[str, Any],
) -> LivestreamV2Command:
    command = _leased_command(session, client_id=client_id, command_id=command_id, claim_token=claim_token)
    command.state = "completed"
    command.result = result or {}
    command.error_code = None
    command.error_message = None
    command.retryable = None
    command.claim_token_digest = None
    command.lease_expires_at = None
    command.updated_at = _now()
    command.completed_at = _now()
    session.add(command)
    return command


def fail_command(
    session: Session,
    *,
    client_id: int,
    command_id: str,
    claim_token: str,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> LivestreamV2Command:
    command = _leased_command(session, client_id=client_id, command_id=command_id, claim_token=claim_token)
    command.error_code = str(error_code or "agent_error")[:128]
    command.error_message = str(error_message or "")[:2000]
    command.retryable = bool(retryable)
    command.claim_token_digest = None
    command.lease_expires_at = None
    command.updated_at = _now()
    generation_id = str((command.payload or {}).get("generation_id") or "")
    generation = session.get(LivestreamV2Generation, generation_id) if generation_id else None
    current = current_generation(session, client_id)
    generation_state_is_stale = bool(
        generation is not None
        and (
            generation.state == "superseded"
            or (generation.state == "stopping" and command.command_type != "stop")
        )
    )
    stale_generation = bool(
        generation_id
        and (
            generation is None
            or current is None
            or current.id != generation_id
            or generation_state_is_stale
        )
    )
    if retryable and not stale_generation and command.attempts < COMMAND_MAX_ATTEMPTS:
        command.state = "queued"
        command.available_at = _now() + timedelta(seconds=min(60, 2 ** command.attempts))
    else:
        command.state = "failed"
        command.completed_at = _now()
        if generation is not None and generation.state not in FINAL_GENERATION_STATES and generation.state != "stopping":
            generation.state = "failed"
            generation.error_code = command.error_code
            session.add(generation)
    session.add(command)
    return command


def ensure_current_generation(
    session: Session,
    *,
    client_id: int,
    generation_id: str,
    allowed_states: set[str],
) -> LivestreamV2Generation:
    generation = session.get(LivestreamV2Generation, generation_id)
    current = current_generation(session, client_id)
    if (
        generation is None
        or generation.client_id != client_id
        or current is None
        or current.id != generation_id
        or generation.state not in allowed_states
    ):
        raise HTTPException(status_code=409, detail="Livestream-generation er ikke længere aktiv")
    return generation


def generation_started(session: Session, *, client_id: int, generation_id: str) -> LivestreamV2Generation:
    generation = ensure_current_generation(
        session,
        client_id=client_id,
        generation_id=generation_id,
        allowed_states={"starting", "running"},
    )
    generation.state = "running"
    if generation.started_at is None:
        generation.started_at = _now()
    session.add(generation)
    client = session.get(Client, client_id)
    if client is not None:
        client.livestream_status = "running"
        client.livestream_process_status = "running"
        client.livestream_desired_state = "running"
        client.livestream_stop_reason = None
        session.add(client)
    _write_generation_marker(client_id, generation_id)
    _clear_stop_marker(client_id)
    return generation


def generation_stopped(
    session: Session,
    *,
    client_id: int,
    generation_id: str,
    error_code: str | None,
) -> LivestreamV2Generation:
    generation = session.get(LivestreamV2Generation, generation_id)
    if generation is None or generation.client_id != client_id:
        raise HTTPException(status_code=404, detail="Livestream-generation ikke fundet")
    generation.state = "failed" if error_code else "stopped"
    generation.error_code = str(error_code or "")[:128] or None
    generation.stopped_at = _now()
    session.add(generation)
    client = session.get(Client, client_id)
    if client is not None:
        client.livestream_status = "stopped" if not error_code else "failed"
        client.livestream_process_status = "stopped"
        client.livestream_desired_state = "stopped"
        if error_code:
            client.livestream_last_error = str(error_code)[:500]
        session.add(client)
    _write_stop_marker(client_id, reason=error_code or "viewer_owned_stop", generation_id=generation_id)
    _clear_hls_media(client_id)
    return generation


def reconcile_stopping_generation_from_agent_status(
    session: Session,
    *,
    client_id: int,
    status_payload: dict[str, Any],
) -> bool:
    """Finalize a stranded stop only when the physical agent proves it is safe.

    A retryable stop timeout may leave the generation in ``stopping``.  We must
    not release that generation merely because a timer elapsed: a producer may
    still be running. Agent status is authoritative only when producer and
    uploader are physically quiesced and any differing uploader generation is
    already final for this same client.
    """
    generation = current_generation(session, client_id)
    if generation is None or generation.state != "stopping":
        return False

    payload = status_payload if isinstance(status_payload, dict) else {}
    producer = payload.get("producer")
    uploader = payload.get("uploader")
    if not isinstance(producer, dict) or not isinstance(uploader, dict):
        return False

    # The producer intentionally clears its in-memory generation_id after it has
    # published the final stopped status. Therefore a physically quiesced
    # producer may report generation_id=null here. A *different non-empty*
    # generation is still unsafe and must never reconcile this stop.
    producer_generation = str(producer.get("generation_id") or "")
    if producer_generation and producer_generation != generation.id:
        return False

    # The uploader can legitimately still name the last generation it actually
    # processed when a newer generation never reached the agent (for example, a
    # queued start was cancelled before claim and a later stop completed). In
    # that case its state must be idle, and any different non-empty generation
    # must already be final for this same client. Never reconcile across another
    # active/unknown generation.
    uploader_generation = str(uploader.get("generation_id") or "")
    if uploader_generation and uploader_generation != generation.id:
        previous = session.get(LivestreamV2Generation, uploader_generation)
        if (
            previous is None
            or previous.client_id != client_id
            or previous.state not in FINAL_GENERATION_STATES
        ):
            return False
    if str(producer.get("state") or "").lower() != "stopped":
        return False
    if producer.get("pid") is not None:
        return False
    if str(uploader.get("state") or "").lower() != "idle":
        return False

    # Do not race an agent that is still executing a leased stop.  Queued
    # retries are safe to cancel because the same agent status has already
    # proven that the generation is physically stopped.
    leased_stops = session.exec(
        select(LivestreamV2Command).where(
            LivestreamV2Command.client_id == client_id,
            LivestreamV2Command.command_type == "stop",
            LivestreamV2Command.state == "leased",
        )
    ).all()
    if any(str((command.payload or {}).get("generation_id") or "") == generation.id for command in leased_stops):
        return False

    now = _now()
    queued_stops = session.exec(
        select(LivestreamV2Command).where(
            LivestreamV2Command.client_id == client_id,
            LivestreamV2Command.command_type == "stop",
            LivestreamV2Command.state == "queued",
        )
    ).all()
    for command in queued_stops:
        if str((command.payload or {}).get("generation_id") or "") != generation.id:
            continue
        command.state = "cancelled"
        command.error_code = "reconciled_stopped"
        command.error_message = "Agentstatus bekræftede at Livestream allerede var stoppet"
        command.retryable = False
        command.completed_at = now
        command.updated_at = now
        session.add(command)

    generation_stopped(
        session,
        client_id=client_id,
        generation_id=generation.id,
        error_code=None,
    )
    # If any authenticated client activity is already present, do not wait for
    # the next heartbeat/sweeper tick. The old generation is now physically and
    # transactionally stopped, so enqueue the next generation immediately.
    viewer_active = active_viewer_count(session, client_id) > 0
    activity_active = active_livestream_activity_count(session, client_id) > 0
    if (
        not explicit_stop_latched(session, client_id)
        and (viewer_active or activity_active)
        and current_generation(session, client_id) is None
    ):
        request_start(
            session,
            client_id,
            source=(
                "viewer_returned_during_recovery"
                if viewer_active
                else "client_activity_returned_during_recovery"
            ),
        )
    return True


def update_agent_status(
    session: Session,
    *,
    client_id: int,
    observed_state: str,
    status_payload: dict[str, Any],
    agent_version: str,
    boot_id: str | None,
) -> LivestreamV2AgentStatus:
    row = session.exec(
        select(LivestreamV2AgentStatus).where(LivestreamV2AgentStatus.client_id == client_id)
    ).first()
    if row is None:
        row = LivestreamV2AgentStatus(
            client_id=client_id,
            observed_state=observed_state,
            status_payload=status_payload or {},
            agent_version=agent_version,
            boot_id=boot_id,
            updated_at=_now(),
        )
    else:
        row.observed_state = observed_state
        row.status_payload = status_payload or {}
        row.agent_version = agent_version
        row.boot_id = boot_id
        row.updated_at = _now()
    session.add(row)
    return row


def maybe_recover_stale_media(session: Session, client_id: int) -> bool:
    if (
        active_viewer_count(session, client_id) == 0
        and active_livestream_activity_count(session, client_id) == 0
    ):
        return False
    generation = current_generation(session, client_id)
    if generation is None or generation.state not in {"starting", "running"}:
        return False
    reference = generation.last_upload_at or generation.started_at or generation.created_at
    age = _as_utc(datetime.now(timezone.utc)) - _as_utc(reference)
    if age <= timedelta(seconds=MEDIA_STALE_SECONDS):
        return False
    pending = session.exec(
        select(LivestreamV2Command.id).where(
            LivestreamV2Command.client_id == client_id,
            LivestreamV2Command.command_type.in_({"start", "restart", "reset_generation"}),
            LivestreamV2Command.state.in_({"queued", "leased"}),
        ).limit(1)
    ).first()
    if pending:
        return False
    recent = session.exec(
        select(LivestreamV2Generation.id).where(
            LivestreamV2Generation.client_id == client_id,
            LivestreamV2Generation.requested_action == "reset_generation",
            LivestreamV2Generation.created_at >= _now() - timedelta(minutes=10),
        )
    ).all()
    if len(recent) >= 3:
        generation.state = "failed"
        generation.error_code = "media_stalled"
        session.add(generation)
        enqueue_command(session, client_id=client_id, command_type="stop", payload={})
        return True
    request_reset_generation(session, client_id)
    return True


def reconcile_viewer_lifecycle(session: Session, client_id: int) -> str | None:
    _lock_client(session, client_id)
    now = _now()
    _expire_stale_viewers(session, client_id, now=now)
    active_viewers = len(
        session.exec(
            select(LivestreamV2Viewer.id).where(
                LivestreamV2Viewer.client_id == client_id,
                LivestreamV2Viewer.ended_at.is_(None),
            )
        ).all()
    )
    active_client_activity = active_livestream_activity_count(session, client_id)
    generation = current_generation(session, client_id)

    # One shared client lifecycle: a visible Livestream viewer, Terminal browser
    # session, or Remote Desktop browser session can start/hold Livestream.
    # Domains publish only authenticated presence; they never call each other.
    if active_viewers > 0 or active_client_activity > 0:
        if generation is None:
            if explicit_stop_latched(session, client_id):
                return None
            request_start(
                session,
                client_id,
                source="viewer_reconcile" if active_viewers > 0 else "client_activity_reconcile",
            )
            return "start"
        return None

    if generation is None or generation.state == "stopping":
        return None

    last_viewer_ended = session.exec(
        select(LivestreamV2Viewer.ended_at)
        .where(
            LivestreamV2Viewer.client_id == client_id,
            LivestreamV2Viewer.ended_at.is_not(None),
        )
        .order_by(LivestreamV2Viewer.ended_at.desc())
        .limit(1)
    ).first()
    last_activity_ended = last_livestream_activity_ended_at(session, client_id)
    ended_candidates = [
        value for value in (last_viewer_ended, last_activity_ended) if value is not None
    ]
    absent_since = max(ended_candidates) if ended_candidates else generation.created_at
    if now - absent_since < timedelta(seconds=VIEWER_STOP_GRACE_SECONDS):
        return None
    request_stop(session, client_id, source="client_activity_grace_expired")
    return "stop"


def reconcile_all_viewer_lifecycles(session: Session) -> list[tuple[int, str]]:
    candidate_ids = set(
        session.exec(
            select(LivestreamV2Generation.client_id).where(
                LivestreamV2Generation.state.in_(ACTIVE_GENERATION_STATES)
            )
        ).all()
    )
    candidate_ids.update(
        session.exec(
            select(LivestreamV2Viewer.client_id).where(LivestreamV2Viewer.ended_at.is_(None))
        ).all()
    )
    candidate_ids.update(active_livestream_activity_client_ids(session))
    actions: list[tuple[int, str]] = []
    for client_id in sorted(candidate_ids):
        action = reconcile_viewer_lifecycle(session, int(client_id))
        if action:
            actions.append((int(client_id), action))
    return actions


def _sweeper_loop() -> None:
    while True:
        time.sleep(VIEWER_SWEEP_SECONDS)
        try:
            with Session(engine) as session:
                reconcile_all_viewer_lifecycles(session)
                session.commit()
        except Exception:
            # Deliberately isolated: a Livestream sweeper failure must never take
            # down the main app or another control domain.
            continue


def ensure_sweeper_started() -> None:
    global _sweeper_started
    with _sweeper_lock:
        if _sweeper_started:
            return
        _sweeper_started = True
        threading.Thread(
            target=_sweeper_loop,
            name="livestream-v2-viewer-sweeper",
            daemon=True,
        ).start()


def _generation_marker_path(client_id: int) -> Path:
    return Path(safe_client_dir(str(client_id))) / ".stream_generation.json"


def _stop_marker_path(client_id: int) -> Path:
    return Path(safe_client_dir(str(client_id))) / ".stream_stopped.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _write_generation_marker(client_id: int, generation_id: str) -> None:
    _atomic_json(
        _generation_marker_path(client_id),
        {
            "generation": generation_id,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
    )


def _write_stop_marker(client_id: int, *, reason: str, generation_id: str | None) -> None:
    _atomic_json(
        _stop_marker_path(client_id),
        {
            "stream_stopped": True,
            "client_id": str(client_id),
            "reason": reason,
            "generation": generation_id,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
    )


def _clear_stop_marker(client_id: int) -> None:
    try:
        _stop_marker_path(client_id).unlink()
    except FileNotFoundError:
        pass


def _clear_hls_media(client_id: int) -> None:
    directory = Path(safe_client_dir(str(client_id)))
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        name = path.name
        if path.is_file() and (
            name == "index.m3u8"
            or name == "init.mp4"
            or _SEGMENT_RE.fullmatch(name)
            or re.fullmatch(r"segment_\d+\.(?:ts|mp4)", name)
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def safe_hls_filename(filename: str) -> str:
    if not _ALLOWED_FILE_RE.fullmatch(filename or ""):
        raise HTTPException(status_code=400, detail="Ugyldigt Livestream HLS-filnavn")
    return filename


def validate_manifest(payload: bytes) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="HLS-manifest er ikke UTF-8") from exc
    if not text.startswith("#EXTM3U"):
        raise HTTPException(status_code=400, detail="HLS-manifest mangler EXTM3U")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "://" in line or line.startswith("/") or ".." in line or not _ALLOWED_FILE_RE.fullmatch(line):
            raise HTTPException(status_code=400, detail="HLS-manifest indeholder ugyldig reference")


def write_hls_file(
    session: Session,
    *,
    client_id: int,
    generation_id: str,
    filename: str,
    payload: bytes,
    sha256: str,
    sequence: int,
) -> Path:
    generation = ensure_current_generation(
        session,
        client_id=client_id,
        generation_id=generation_id,
        allowed_states={"starting", "running"},
    )
    if len(payload) > MAX_HLS_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Livestreamfil er for stor")
    actual = hashlib.sha256(payload).hexdigest()
    if not secrets.compare_digest(actual, str(sha256 or "").lower()):
        raise HTTPException(status_code=400, detail="Livestreamfil SHA-256 matcher ikke")
    safe_name = safe_hls_filename(filename)
    if safe_name == "index.m3u8":
        validate_manifest(payload)
    directory = Path(safe_client_dir(str(client_id)))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe_name
    tmp = directory / f".{safe_name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    now = _now()
    generation.last_upload_at = now
    if safe_name == "index.m3u8":
        generation.last_manifest_at = now
    if sequence >= 0:
        generation.last_sequence = max(int(generation.last_sequence or -1), int(sequence))
    session.add(generation)
    return path


ensure_sweeper_started()
