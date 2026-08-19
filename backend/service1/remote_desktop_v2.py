"""Remote Desktop-owned authentication, status and persisted session lifecycle."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import os
import uuid
from typing import Any, Optional

import jwt
from fastapi import HTTPException, status
from sqlmodel import Session, select

from .auth import verify_password
from .models import User
from .remote_desktop_v2_models import (
    RemoteDesktopAgentStatus,
    RemoteDesktopClient,
    RemoteDesktopCredential,
)
from .remote_desktop_session_models import RemoteDesktopSession, RemoteDesktopSessionEvent

DOMAIN = "remote_desktop"
DOMAIN_TOKEN_TTL_SECONDS = min(
    max(60, int(os.getenv("CLIENTFLOW_REMOTE_DESKTOP_TOKEN_TTL_SECONDS", "600"))),
    3600,
)
REMOTE_DESKTOP_AUTH_ALGORITHM = "HS256"
# Keep the installed seq-1200 credential contract stable. The signing key is
# Remote-Desktop-owned even though the credential's issuer string is retained.
DOMAIN_TOKEN_ISSUER = (
    os.getenv("CLIENTFLOW_REMOTE_DESKTOP_TOKEN_ISSUER") or "planiq-display-api"
).strip()
SESSION_SECONDS = min(
    max(60, int(os.getenv("CLIENTFLOW_REMOTE_DESKTOP_SESSION_SECONDS", "3600"))),
    4 * 3600,
)


def _remote_desktop_auth_signing_key() -> bytes:
    raw_key = str(os.getenv("CLIENTFLOW_REMOTE_DESKTOP_AUTH_KEY_B64") or "").strip()
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Remote Desktop auth-signing key er ikke konfigureret",
        )
    try:
        key = base64.urlsafe_b64decode(raw_key + "=" * (-len(raw_key) % 4))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Remote Desktop auth-signing key er ugyldig") from exc
    if len(key) != 32:
        raise HTTPException(status_code=503, detail="Remote Desktop auth-signing key skal være 32 bytes")
    return key


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _validate_credential_id(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt Remote Desktop credential") from exc


def authenticate_remote_desktop_credential(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    client_secret: str,
) -> RemoteDesktopCredential:
    credential_id = _validate_credential_id(credential_id)
    credential = session.get(RemoteDesktopCredential, credential_id)
    client = session.get(RemoteDesktopClient, client_id)
    if (
        credential is None
        or client is None
        or str(client.status or "").lower() != "approved"
        or credential.client_id != client_id
        or credential.revoked_at is not None
    ):
        raise HTTPException(status_code=401, detail="Ugyldigt Remote Desktop credential")
    try:
        verified = verify_password(client_secret, credential.secret_hash)
    except Exception:
        verified = False
    if not verified:
        raise HTTPException(status_code=401, detail="Ugyldigt Remote Desktop credential")
    credential.last_used_at = utcnow()
    session.add(credential)
    return credential


def create_remote_desktop_domain_token(credential: RemoteDesktopCredential) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=DOMAIN_TOKEN_TTL_SECONDS)
    claims = {
        "iss": DOMAIN_TOKEN_ISSUER,
        "sub": f"client:{credential.client_id}:{credential.id}",
        "principal": "client_domain",
        "client_id": credential.client_id,
        "credential_id": credential.id,
        "domain": DOMAIN,
        "scope": f"clientflow:{DOMAIN}",
        "aud": f"clientflow-domain:{DOMAIN}",
        "token_version": credential.token_version,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, _remote_desktop_auth_signing_key(), algorithm=REMOTE_DESKTOP_AUTH_ALGORITHM)
    return token, expires_at


def issue_remote_desktop_token_response(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    client_secret: str,
) -> dict[str, Any]:
    credential = authenticate_remote_desktop_credential(
        session,
        client_id=client_id,
        credential_id=credential_id,
        client_secret=client_secret,
    )
    token, expires_at = create_remote_desktop_domain_token(credential)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": DOMAIN_TOKEN_TTL_SECONDS,
        "client_id": credential.client_id,
        "credential_id": credential.id,
        "domain": DOMAIN,
        "audience": f"clientflow-domain:{DOMAIN}",
        "scope": f"clientflow:{DOMAIN}",
        "issuer": DOMAIN_TOKEN_ISSUER,
        "token_version": credential.token_version,
        "expires_at": expires_at,
    }


def verify_remote_desktop_agent_token(
    session: Session,
    token: str,
    *,
    client_id: int,
) -> RemoteDesktopCredential:
    try:
        claims = jwt.decode(
            token,
            _remote_desktop_auth_signing_key(),
            algorithms=[REMOTE_DESKTOP_AUTH_ALGORITHM],
            audience=f"clientflow-domain:{DOMAIN}",
            issuer=DOMAIN_TOKEN_ISSUER,
            options={
                "require": [
                    "exp", "iat", "nbf", "jti", "sub", "client_id",
                    "credential_id", "domain", "scope", "token_version",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt Remote Desktop-agent token") from exc

    credential_id = str(claims.get("credential_id") or "")
    if (
        claims.get("principal") != "client_domain"
        or claims.get("domain") != DOMAIN
        or claims.get("scope") != f"clientflow:{DOMAIN}"
        or int(claims.get("client_id") or 0) != int(client_id)
        or claims.get("sub") != f"client:{client_id}:{credential_id}"
    ):
        raise HTTPException(status_code=403, detail="Token tilhører et andet Remote Desktop-domæne eller klient")

    credential = session.get(RemoteDesktopCredential, credential_id)
    client = session.get(RemoteDesktopClient, client_id)
    if (
        credential is None
        or client is None
        or str(client.status or "").lower() != "approved"
        or credential.client_id != client_id
        or credential.revoked_at is not None
        or int(credential.token_version) != int(claims.get("token_version", -1))
    ):
        raise HTTPException(status_code=401, detail="Remote Desktop credential er tilbagekaldt eller forældet")
    return credential


def bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token mangler")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token mangler")
    return token


def update_remote_desktop_agent_status(
    session: Session,
    *,
    credential: RemoteDesktopCredential,
    schema_version: int,
    observed_state: str,
    status_payload: dict[str, Any],
    agent_version: Optional[str],
    boot_id: Optional[str],
) -> RemoteDesktopAgentStatus:
    if schema_version < 1:
        raise HTTPException(status_code=422, detail="schema_version skal være mindst 1")
    state = str(observed_state or "").strip()[:80]
    if not state:
        raise HTTPException(status_code=422, detail="observed_state mangler")
    row = session.exec(
        select(RemoteDesktopAgentStatus).where(RemoteDesktopAgentStatus.client_id == credential.client_id)
    ).first()
    now = utcnow()
    if row is None:
        row = RemoteDesktopAgentStatus(
            id=str(uuid.uuid4()),
            client_id=credential.client_id,
            credential_id=credential.id,
            schema_version=schema_version,
            observed_state=state,
            status_payload=dict(status_payload or {}),
            agent_version=(str(agent_version)[:80] if agent_version else None),
            boot_id=(str(boot_id)[:128] if boot_id else None),
            reported_at=now,
        )
    else:
        row.credential_id = credential.id
        row.schema_version = schema_version
        row.observed_state = state
        row.status_payload = dict(status_payload or {})
        row.agent_version = str(agent_version)[:80] if agent_version else None
        row.boot_id = str(boot_id)[:128] if boot_id else None
        row.reported_at = now
    session.add(row)
    return row


def authorize_remote_desktop_session(
    session: Session,
    *,
    session_id: str,
    client_id: int,
    user: User,
    source_ip: Optional[str],
    user_agent: Optional[str],
) -> RemoteDesktopSession:
    try:
        session_id = str(uuid.UUID(str(session_id)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Remote Desktop session-id er ugyldigt") from exc
    if session.get(RemoteDesktopSession, session_id) is not None:
        raise HTTPException(status_code=409, detail="Remote Desktop-sessionen findes allerede")
    client = session.get(RemoteDesktopClient, client_id)
    if client is None or client.status != "approved":
        raise HTTPException(status_code=404, detail="Remote Desktop-klient ikke fundet eller ikke godkendt")
    if user.id is None:
        raise HTTPException(status_code=401, detail="Bruger mangler database-id")
    now = utcnow()
    row = RemoteDesktopSession(
        id=session_id,
        client_id=client_id,
        requested_by_user_id=int(user.id),
        source_ip=(str(source_ip)[:255] if source_ip else None),
        user_agent=(str(user_agent)[:2000] if user_agent else None),
        created_at=now,
        expires_at=now + timedelta(seconds=SESSION_SECONDS),
        status="authorized",
    )
    session.add(row)
    session.add(RemoteDesktopSessionEvent(
        id=str(uuid.uuid4()),
        remote_desktop_session_id=session_id,
        event_type="authorized",
        actor_user_id=int(user.id),
        created_at=now,
        details={},
    ))
    return row


def record_remote_desktop_event(
    session: Session,
    *,
    client_id: int,
    session_id: str,
    event_type: str,
    details: dict[str, Any],
    credential: Optional[RemoteDesktopCredential] = None,
    actor_user_id: Optional[int] = None,
) -> RemoteDesktopSessionEvent:
    row = session.get(RemoteDesktopSession, session_id)
    if row is None or row.client_id != client_id:
        raise HTTPException(status_code=404, detail="Remote Desktop-session ikke fundet")
    event_name = str(event_type or "").strip()[:80]
    if not event_name:
        raise HTTPException(status_code=422, detail="event_type mangler")
    now = utcnow()
    event = RemoteDesktopSessionEvent(
        id=str(uuid.uuid4()),
        remote_desktop_session_id=row.id,
        event_type=event_name,
        actor_user_id=actor_user_id,
        credential_id=(credential.id if credential else None),
        created_at=now,
        details=dict(details or {}),
    )
    row.last_activity_at = now
    if event_name in {"capture_started", "agent_ready"} and row.status in {"authorized", "requested"}:
        row.status = "connected"
        row.connected_at = row.connected_at or now
    elif event_name in {"session_closed", "browser_disconnected"}:
        row.status = "disconnected"
        row.disconnected_at = now
    elif event_name == "error":
        row.status = "failed"
        row.close_reason = str((details or {}).get("error") or "Remote Desktop-fejl")[:2000]
    session.add(row)
    session.add(event)
    return event


def close_remote_desktop_session(
    session: Session,
    *,
    client_id: int,
    session_id: str,
    actor_user_id: Optional[int],
    reason: str,
) -> None:
    row = session.get(RemoteDesktopSession, session_id)
    if row is None or row.client_id != client_id:
        return
    now = utcnow()
    # Preserve stronger terminal states already established by expiry/decommission.
    if row.status not in {"expired", "revoked", "failed"}:
        row.status = "disconnected"
    row.disconnected_at = row.disconnected_at or now
    row.last_activity_at = now
    row.close_reason = str(reason or "browser_disconnected")[:2000]
    session.add(row)
    session.add(RemoteDesktopSessionEvent(
        id=str(uuid.uuid4()),
        remote_desktop_session_id=session_id,
        event_type="browser_disconnected",
        actor_user_id=actor_user_id,
        created_at=now,
        details={"reason": row.close_reason, "final_status": row.status},
    ))
