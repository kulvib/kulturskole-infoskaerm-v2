"""ClientFlow 1.2 Terminal-domain authentication and persisted session lifecycle."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
import uuid
from typing import Any, Optional

import jwt
from fastapi import HTTPException, status
from sqlmodel import Session, select

from .auth import verify_password
from .models import User
from .terminal_v2_models import (
    RootTerminalGrant,
    TerminalAgentStatus,
    TerminalClient,
    TerminalCredential,
    TerminalSession,
    TerminalSessionEvent,
)

DOMAIN = "terminal"
DOMAIN_TOKEN_TTL_SECONDS = min(
    max(60, int(os.getenv("CLIENTFLOW_TERMINAL_TOKEN_TTL_SECONDS", "600"))),
    3600,
)
TERMINAL_AUTH_ALGORITHM = "HS256"
TERMINAL_AUTH_ISSUER = (
    os.getenv("CLIENTFLOW_TERMINAL_AUTH_ISSUER")
    or "clientflow-terminal-auth"
).strip()
# Keep the on-device credential contract stable while the signing key is
# Terminal-owned. Existing ClientFlow 1.2 credentials are bound to this
# issuer independently of the platform JWT signing trust.
DOMAIN_TOKEN_ISSUER = (
    os.getenv("CLIENTFLOW_TERMINAL_TOKEN_ISSUER")
    or "planiq-display-api"
).strip()
STANDARD_SESSION_SECONDS = min(max(60, int(os.getenv("CLIENTFLOW_TERMINAL_STANDARD_SESSION_SECONDS", "1800"))), 1800)
ROOT_SESSION_SECONDS = min(max(60, int(os.getenv("CLIENTFLOW_TERMINAL_ROOT_SESSION_SECONDS", "600"))), 600)
ROOT_GRANT_AUDIENCE = "clientflow-root-terminal-broker"
ROOT_GRANT_ISSUER = "clientflow-backend"
ROOT_GRANT_ALGORITHM = "HS256"
ADMIN_STEP_UP_TTL_SECONDS = min(
    max(60, int(os.getenv("CLIENTFLOW_TERMINAL_ADMIN_STEP_UP_SECONDS", "600"))),
    1800,
)
ADMIN_STEP_UP_AUDIENCE = "planiq-display:terminal-admin-step-up"
ADMIN_STEP_UP_PURPOSE = "terminal_admin_step_up"


def _terminal_auth_signing_key() -> bytes:
    """Return Terminal's private signing key without falling back to platform auth."""
    raw_key = str(os.getenv("CLIENTFLOW_TERMINAL_AUTH_KEY_B64") or "").strip()
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Terminalens auth-signing key er ikke konfigureret",
        )
    try:
        key = base64.urlsafe_b64decode(raw_key + "=" * (-len(raw_key) % 4))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Terminalens auth-signing key er ugyldig",
        ) from exc
    if len(key) != 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Terminalens auth-signing key skal være 32 bytes",
        )
    return key


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _validate_credential_id(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt credential") from exc


def authenticate_terminal_credential(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    client_secret: str,
) -> TerminalCredential:
    credential_id = _validate_credential_id(credential_id)
    row = session.get(TerminalCredential, credential_id)
    client = session.get(TerminalClient, client_id)
    if (
        row is None
        or client is None
        or str(getattr(client, "status", "") or "").lower() != "approved"
        or row.client_id != client_id
        or row.revoked_at is not None
    ):
        raise HTTPException(status_code=401, detail="Ugyldigt credential")
    try:
        verified = verify_password(client_secret, row.secret_hash)
    except Exception:
        verified = False
    if not verified:
        raise HTTPException(status_code=401, detail="Ugyldigt credential")
    row.last_used_at = utcnow()
    session.add(row)
    return row


def create_terminal_domain_token(credential: TerminalCredential) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=DOMAIN_TOKEN_TTL_SECONDS)
    audience = f"clientflow-domain:{DOMAIN}"
    scope = f"clientflow:{DOMAIN}"
    claims = {
        "iss": DOMAIN_TOKEN_ISSUER,
        "sub": f"client:{credential.client_id}:{credential.id}",
        "principal": "client_domain",
        "client_id": credential.client_id,
        "credential_id": credential.id,
        "domain": DOMAIN,
        "scope": scope,
        "aud": audience,
        "token_version": credential.token_version,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, _terminal_auth_signing_key(), algorithm=TERMINAL_AUTH_ALGORITHM), expires_at


def issue_terminal_token_response(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    client_secret: str,
) -> dict[str, Any]:
    credential = authenticate_terminal_credential(
        session,
        client_id=client_id,
        credential_id=credential_id,
        client_secret=client_secret,
    )
    token, expires_at = create_terminal_domain_token(credential)
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


def verify_terminal_agent_token(
    session: Session,
    token: str,
    *,
    client_id: int,
) -> TerminalCredential:
    try:
        claims = jwt.decode(
            token,
            _terminal_auth_signing_key(),
            algorithms=[TERMINAL_AUTH_ALGORITHM],
            audience=f"clientflow-domain:{DOMAIN}",
            issuer=DOMAIN_TOKEN_ISSUER,
            options={"require": ["exp", "iat", "nbf", "jti", "sub", "client_id", "credential_id", "domain", "scope", "token_version"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt Terminal-agent token") from exc

    credential_id = str(claims.get("credential_id") or "")
    if (
        claims.get("principal") != "client_domain"
        or claims.get("domain") != DOMAIN
        or claims.get("scope") != f"clientflow:{DOMAIN}"
        or int(claims.get("client_id") or 0) != int(client_id)
        or claims.get("sub") != f"client:{client_id}:{credential_id}"
    ):
        raise HTTPException(status_code=403, detail="Token tilhører et andet Terminal-domæne eller klient")

    credential = session.get(TerminalCredential, credential_id)
    client = session.get(TerminalClient, client_id)
    if (
        credential is None
        or client is None
        or str(getattr(client, "status", "") or "").lower() != "approved"
        or credential.client_id != client_id
        or credential.revoked_at is not None
        or int(credential.token_version) != int(claims.get("token_version", -1))
    ):
        raise HTTPException(status_code=401, detail="Terminal credential er tilbagekaldt eller forældet")
    return credential


def bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token mangler")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token mangler")
    return token


def update_terminal_domain_status(
    session: Session,
    *,
    credential: TerminalCredential,
    schema_version: int,
    observed_state: str,
    status_payload: dict[str, Any],
    agent_version: Optional[str],
    boot_id: Optional[str],
) -> TerminalAgentStatus:
    if schema_version < 1:
        raise HTTPException(status_code=422, detail="schema_version skal være mindst 1")
    state = str(observed_state or "").strip()[:64]
    if not state:
        raise HTTPException(status_code=422, detail="observed_state mangler")
    now = utcnow()
    row = session.exec(
        select(TerminalAgentStatus).where(
            TerminalAgentStatus.client_id == credential.client_id,
        )
    ).first()
    if row is None:
        row = TerminalAgentStatus(
            id=str(uuid.uuid4()),
            client_id=credential.client_id,
            schema_version=schema_version,
            observed_state=state,
            status_payload=status_payload,
            agent_version=(str(agent_version).strip()[:64] if agent_version else None),
            boot_id=(str(boot_id).strip()[:128] if boot_id else None),
            credential_id=credential.id,
            reported_at=now,
        )
    else:
        row.schema_version = schema_version
        row.observed_state = state
        row.status_payload = status_payload
        row.agent_version = str(agent_version).strip()[:64] if agent_version else None
        row.boot_id = str(boot_id).strip()[:128] if boot_id else None
        row.credential_id = credential.id
        row.reported_at = now
    session.add(row)
    return row


def _event(
    session: Session,
    *,
    terminal_session_id: str,
    event_type: str,
    actor_user_id: Optional[int] = None,
    credential_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> TerminalSessionEvent:
    row = TerminalSessionEvent(
        id=str(uuid.uuid4()),
        terminal_session_id=terminal_session_id,
        event_type=str(event_type)[:128],
        actor_user_id=actor_user_id,
        credential_id=credential_id,
        created_at=utcnow(),
        details=dict(details or {}),
    )
    session.add(row)
    return row


def create_browser_terminal_session(
    session: Session,
    *,
    session_id: str,
    client_id: int,
    user: User,
    mode: str,
    source_ip: Optional[str],
    user_agent: Optional[str],
) -> TerminalSession:
    # Defense in depth: terminal session creation itself is superadmin-only,
    # independently of route/ticket guards. This applies to BOTH Bruger-terminal
    # (standard PTY) and Admin-terminal (root PTY).
    if not getattr(user, "is_superadmin", False) or not getattr(user, "is_active", False):
        raise HTTPException(status_code=403, detail="Kun superadministratorer må åbne Terminal")
    if session.get(TerminalSession, session_id) is not None:
        raise HTTPException(status_code=409, detail="Terminalsessionen findes allerede")
    terminal_client = session.get(TerminalClient, client_id)
    if terminal_client is None or terminal_client.status != "approved":
        raise HTTPException(status_code=404, detail="Terminal-klient ikke fundet eller ikke godkendt")
    privilege = "root" if mode == "admin" else "standard"
    if user.id is None:
        raise HTTPException(status_code=401, detail="Bruger mangler database-id")
    now = utcnow()
    seconds = ROOT_SESSION_SECONDS if privilege == "root" else STANDARD_SESSION_SECONDS
    row = TerminalSession(
        id=session_id,
        client_id=client_id,
        requested_by_user_id=int(user.id),
        privilege_level=privilege,
        # Retain the nullable legacy column for historical compatibility, but
        # new Terminal sessions do not require or collect a free-text reason.
        reason=None,
        source_ip=(str(source_ip)[:255] if source_ip else None),
        user_agent=(str(user_agent)[:2000] if user_agent else None),
        created_at=now,
        authorized_at=now,
        expires_at=now + timedelta(seconds=seconds),
        status="authorized",
    )
    session.add(row)
    _event(session, terminal_session_id=session_id, event_type="authorized", actor_user_id=int(user.id))
    _event(session, terminal_session_id=session_id, event_type="browser_connected", actor_user_id=int(user.id))
    return row


def _require_active_superadmin(user: User) -> None:
    if not getattr(user, "is_superadmin", False) or not getattr(user, "is_active", False):
        raise HTTPException(status_code=403, detail="Kun superadmin må åbne Admin-terminal")
    if user.id is None:
        raise HTTPException(status_code=401, detail="Bruger mangler database-id")


def verify_admin_terminal_step_up(
    user: User,
    password: Optional[str],
    *,
    auth_session_binding: str,
) -> tuple[datetime, str, datetime]:
    """Re-authenticate once and issue a 10-minute session-bound step-up token."""
    _require_active_superadmin(user)
    binding = str(auth_session_binding or "").strip()
    if not binding:
        raise HTTPException(status_code=401, detail="Admin-terminal mangler login-sessionens sikkerhedsbinding")
    raw = str(password or "")
    if not raw:
        raise HTTPException(status_code=401, detail="Admin-terminal kræver bekræftelse med din adgangskode")
    try:
        verified = verify_password(raw, user.hashed_password)
    except Exception:
        verified = False
    if not verified:
        raise HTTPException(status_code=401, detail="Adgangskoden til Admin-terminal er forkert")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ADMIN_STEP_UP_TTL_SECONDS)
    claims = {
        "iss": TERMINAL_AUTH_ISSUER,
        "aud": ADMIN_STEP_UP_AUDIENCE,
        "sub": str(user.username),
        "uid": int(user.id),
        "token_version": int(getattr(user, "token_version", 0) or 0),
        "purpose": ADMIN_STEP_UP_PURPOSE,
        "session_binding": binding,
        "auth_time": int(now.timestamp()),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, _terminal_auth_signing_key(), algorithm=TERMINAL_AUTH_ALGORITHM)
    return now.replace(tzinfo=None), token, expires_at


def verify_admin_terminal_step_up_token(
    user: User,
    token: Optional[str],
    *,
    auth_session_binding: str,
) -> datetime:
    """Validate a recent Admin-terminal step-up for the same login session."""
    _require_active_superadmin(user)
    raw = str(token or "").strip()
    binding = str(auth_session_binding or "").strip()
    if not raw or not binding:
        raise HTTPException(status_code=401, detail="Admin-terminal kræver ny step-up bekræftelse")
    try:
        claims = jwt.decode(
            raw,
            _terminal_auth_signing_key(),
            algorithms=[TERMINAL_AUTH_ALGORITHM],
            issuer=TERMINAL_AUTH_ISSUER,
            audience=ADMIN_STEP_UP_AUDIENCE,
            leeway=5,
            options={
                "require": [
                    "exp", "iat", "nbf", "jti", "iss", "aud", "sub",
                    "uid", "token_version", "purpose", "session_binding", "auth_time",
                ]
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Admin-terminal step-up er udløbet eller ugyldig") from exc

    try:
        uid = int(claims.get("uid"))
        token_version = int(claims.get("token_version"))
        auth_time = int(claims.get("auth_time"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Admin-terminal step-up er ugyldig") from exc

    if (
        uid != int(user.id)
        or str(claims.get("sub") or "") != str(user.username)
        or token_version != int(getattr(user, "token_version", 0) or 0)
        or str(claims.get("purpose") or "") != ADMIN_STEP_UP_PURPOSE
        or not secrets.compare_digest(str(claims.get("session_binding") or ""), binding)
    ):
        raise HTTPException(status_code=401, detail="Admin-terminal step-up matcher ikke den aktive login-session")

    return datetime.fromtimestamp(auth_time, tz=timezone.utc).replace(tzinfo=None)


def _root_signing_config() -> tuple[bytes, str]:
    raw_key = str(os.getenv("CLIENTFLOW_ROOT_TERMINAL_KEY_B64") or "").strip()
    key_id = str(os.getenv("CLIENTFLOW_ROOT_TERMINAL_KEY_ID") or "").strip()
    if not raw_key or not key_id or len(key_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin-terminalens root-grant nøgle er ikke konfigureret",
        )
    try:
        key = base64.urlsafe_b64decode(raw_key + "=" * (-len(raw_key) % 4))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Admin-terminalens root-grant nøgle er ugyldig") from exc
    if len(key) != 32:
        raise HTTPException(status_code=503, detail="Admin-terminalens root-grant nøgle skal være 32 bytes")
    return key, key_id


def issue_root_terminal_grant(
    session: Session,
    *,
    terminal_session: TerminalSession,
    user: User,
    credential: TerminalCredential,
    step_up_verified_at: Optional[datetime],
) -> str:
    if terminal_session.privilege_level != "root":
        raise HTTPException(status_code=400, detail="Root-grant kan kun udstedes til Admin-terminal")
    if user.id is None:
        raise HTTPException(status_code=401, detail="Bruger mangler database-id")
    if step_up_verified_at is None:
        raise HTTPException(status_code=401, detail="Admin-terminal kræver step-up bekræftelse")
    key, key_id = _root_signing_config()
    now = datetime.now(timezone.utc)
    expires_at = _aware(terminal_session.expires_at)
    grant_id = str(uuid.uuid4())
    claims = {
        "iss": ROOT_GRANT_ISSUER,
        "aud": ROOT_GRANT_AUDIENCE,
        "sub": f"root-terminal:{terminal_session.id}",
        "jti": str(uuid.uuid4()),
        "grant_id": grant_id,
        "session_id": terminal_session.id,
        "client_id": terminal_session.client_id,
        "credential_id": credential.id,
        "capability": "root_pty",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, key, algorithm=ROOT_GRANT_ALGORITHM, headers={"kid": key_id})
    grant = RootTerminalGrant(
        id=grant_id,
        terminal_session_id=terminal_session.id,
        client_id=terminal_session.client_id,
        user_id=int(user.id),
        grant_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        step_up_verified_at=step_up_verified_at,
        created_at=utcnow(),
        issued_at=utcnow(),
        expires_at=terminal_session.expires_at,
        capability="terminal_root",
        issued_to_credential_id=credential.id,
    )
    session.add(grant)
    return token


def terminal_session_start_message(
    terminal_session: TerminalSession,
    *,
    root_grant: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "session_start",
        "session_id": terminal_session.id,
        "privilege_level": terminal_session.privilege_level,
        "expires_at": _aware(terminal_session.expires_at).isoformat().replace("+00:00", "Z"),
    }
    if terminal_session.privilege_level == "root":
        if not root_grant:
            raise HTTPException(status_code=500, detail="Admin-terminal mangler root-grant")
        payload["root_grant"] = root_grant
    return payload


def record_terminal_agent_event(
    session: Session,
    *,
    credential: TerminalCredential,
    session_id: str,
    event_type: str,
    details: Optional[dict[str, Any]] = None,
    exit_code: Optional[int] = None,
    transcript_reference: Optional[str] = None,
    transcript_sha256: Optional[str] = None,
) -> TerminalSession:
    terminal_session = session.get(TerminalSession, session_id)
    if terminal_session is None or terminal_session.client_id != credential.client_id:
        raise HTTPException(status_code=404, detail="Terminalsession ikke fundet")
    now = utcnow()
    if terminal_session.expires_at <= now and terminal_session.status in {"requested", "authorized", "connected"}:
        terminal_session.status = "expired"
        terminal_session.disconnected_at = now
    terminal_session.last_activity_at = now

    clean_details = dict(details or {})
    if event_type == "pty_started":
        if terminal_session.status in {"requested", "authorized"}:
            terminal_session.connected_at = terminal_session.connected_at or now
            terminal_session.status = "connected"
    elif event_type == "pty_exited":
        terminal_session.exit_code = exit_code
        terminal_session.disconnected_at = terminal_session.disconnected_at or now
        if terminal_session.status not in {"revoked", "expired", "failed"}:
            terminal_session.status = "disconnected"
    elif event_type == "timeout":
        terminal_session.disconnected_at = terminal_session.disconnected_at or now
        if terminal_session.status != "revoked":
            terminal_session.status = "expired"
    elif event_type == "broker_rejected":
        terminal_session.disconnected_at = terminal_session.disconnected_at or now
        if terminal_session.status not in {"revoked", "expired"}:
            terminal_session.status = "failed"
    elif event_type == "transcript_stored":
        if transcript_reference:
            terminal_session.transcript_reference = str(transcript_reference)[:2000]
        if transcript_sha256:
            terminal_session.transcript_sha256 = str(transcript_sha256)[:128]
    elif event_type == "root_grant_consumed":
        grant = session.exec(
            select(RootTerminalGrant).where(RootTerminalGrant.terminal_session_id == session_id)
        ).first()
        if grant is not None and grant.consumed_at is None:
            grant_id = str(clean_details.get("grant_id") or "")
            if grant.id != grant_id:
                raise HTTPException(status_code=409, detail="Root-grant event matcher ikke sessionens grant")
            grant.consumed_at = now
            session.add(grant)

    session.add(terminal_session)
    event_details = clean_details
    if exit_code is not None:
        event_details = {**event_details, "exit_code": exit_code}
    if transcript_reference:
        event_details = {**event_details, "transcript_reference": str(transcript_reference)[:2000]}
    if transcript_sha256:
        event_details = {**event_details, "transcript_sha256": str(transcript_sha256)[:128]}
    _event(
        session,
        terminal_session_id=session_id,
        event_type=event_type,
        credential_id=credential.id,
        details=event_details,
    )
    return terminal_session


def mark_terminal_agent_disconnected(
    session: Session, *, session_id: str, credential_id: str
) -> None:
    row = session.get(TerminalSession, session_id)
    if row is None:
        return
    now = utcnow()
    if row.status in {"requested", "authorized", "connected"}:
        row.status = "disconnected"
        row.disconnected_at = now
        row.last_activity_at = now
        session.add(row)
    _event(
        session,
        terminal_session_id=session_id,
        event_type="agent_disconnected",
        credential_id=credential_id,
    )


def mark_browser_terminal_closed(session: Session, *, session_id: str, user_id: int) -> None:
    row = session.get(TerminalSession, session_id)
    if row is None:
        return
    now = utcnow()
    _event(session, terminal_session_id=session_id, event_type="browser_disconnected", actor_user_id=user_id)
    if row.status in {"requested", "authorized", "connected"}:
        row.status = "revoked"
        row.disconnected_at = now
        session.add(row)
        _event(session, terminal_session_id=session_id, event_type="revoked", actor_user_id=user_id)
    grant = session.exec(select(RootTerminalGrant).where(RootTerminalGrant.terminal_session_id == session_id)).first()
    if grant is not None and grant.consumed_at is None and grant.revoked_at is None:
        grant.revoked_at = now
        session.add(grant)
